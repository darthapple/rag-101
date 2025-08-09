"""
WebSocket Connection Manager

Manages WebSocket connections for real-time answer delivery in the RAG system.
Provides session-based routing, connection lifecycle management, and NATS integration.
"""

import asyncio
import logging
import json
import uuid
import weakref
from typing import Dict, Set, Optional, Any, List, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
import websockets
from websockets.server import WebSocketServerProtocol
from websockets.exceptions import ConnectionClosed, WebSocketException

import nats
from nats.aio.client import Client as NATS
from nats.js.api import ConsumerConfig, DeliverPolicy, AckPolicy

from .config import get_config


class ConnectionState(Enum):
    """WebSocket connection states"""
    CONNECTING = "connecting"
    CONNECTED = "connected" 
    AUTHENTICATED = "authenticated"
    DISCONNECTING = "disconnecting"
    DISCONNECTED = "disconnected"
    ERROR = "error"


@dataclass
class WebSocketConnection:
    """Represents a WebSocket connection with metadata"""
    connection_id: str
    websocket: WebSocketServerProtocol
    session_id: Optional[str] = None
    state: ConnectionState = ConnectionState.CONNECTING
    connected_at: datetime = field(default_factory=datetime.now)
    last_heartbeat: Optional[datetime] = None
    last_activity: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_alive(self) -> bool:
        """Check if connection is alive and healthy"""
        return (
            self.state in [ConnectionState.CONNECTED, ConnectionState.AUTHENTICATED] and
            not self.websocket.closed
        )
    
    def update_activity(self):
        """Update last activity timestamp"""
        self.last_activity = datetime.now()
    
    def get_uptime(self) -> timedelta:
        """Get connection uptime"""
        return datetime.now() - self.connected_at


class WebSocketConnectionError(Exception):
    """Base exception for WebSocket connection errors"""
    pass


class AuthenticationError(WebSocketConnectionError):
    """Authentication-related errors"""
    pass


class MessageDeliveryError(WebSocketConnectionError):
    """Message delivery errors"""
    pass


class WebSocketConnectionManager:
    """
    Manages WebSocket connections for real-time answer delivery.
    
    Features:
    - Connection lifecycle management
    - Session-based message routing
    - NATS JetStream integration
    - Heartbeat monitoring
    - Connection pooling and limits
    """
    
    def __init__(self):
        """Initialize WebSocket connection manager"""
        self.config = get_config()
        self.logger = logging.getLogger("websocket.manager")
        
        # Connection storage
        self.connections: Dict[str, WebSocketConnection] = {}
        self.session_connections: Dict[str, Set[str]] = {}  # session_id -> connection_ids
        
        # NATS client for message routing
        self.nats_client: Optional[NATS] = None
        self.nats_subscription = None
        
        # Configuration
        self.max_connections = getattr(self.config, 'max_websocket_connections', 1000)
        self.max_connections_per_session = getattr(self.config, 'max_connections_per_session', 5)
        self.heartbeat_interval = getattr(self.config, 'websocket_heartbeat_interval', 30)
        self.connection_timeout = getattr(self.config, 'websocket_connection_timeout', 300)
        self.auth_timeout = getattr(self.config, 'websocket_auth_timeout', 10)
        
        # Background tasks
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Statistics
        self.stats = {
            'connections_created': 0,
            'connections_authenticated': 0,
            'connections_closed': 0,
            'messages_sent': 0,
            'messages_failed': 0,
            'heartbeats_sent': 0,
            'cleanup_runs': 0
        }
        
        self.logger.info("WebSocket connection manager initialized")
    
    async def start(self) -> bool:
        """
        Start the WebSocket connection manager
        
        Returns:
            bool: True if started successfully
        """
        try:
            self.logger.info("Starting WebSocket connection manager...")
            
            # Connect to NATS
            if not await self._connect_nats():
                return False
            
            # Setup NATS subscription for answer routing
            if not await self._setup_nats_subscription():
                return False
            
            # Start background tasks
            self._running = True
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            
            self.logger.info("WebSocket connection manager started successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start WebSocket connection manager: {e}")
            await self.stop()
            return False
    
    async def stop(self):
        """Stop the WebSocket connection manager"""
        try:
            self.logger.info("Stopping WebSocket connection manager...")
            
            # Stop background tasks
            self._running = False
            
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except asyncio.CancelledError:
                    pass
            
            if self._cleanup_task:
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except asyncio.CancelledError:
                    pass
            
            # Close all connections
            await self._close_all_connections()
            
            # Disconnect from NATS
            if self.nats_client:
                await self.nats_client.close()
                self.nats_client = None
            
            self.logger.info("WebSocket connection manager stopped")
            
        except Exception as e:
            self.logger.error(f"Error stopping WebSocket connection manager: {e}")
    
    async def register_connection(
        self, 
        websocket: WebSocketServerProtocol,
        session_id: Optional[str] = None
    ) -> str:
        """
        Register a new WebSocket connection
        
        Args:
            websocket: WebSocket connection
            session_id: Optional session ID for authentication
            
        Returns:
            str: Connection ID
            
        Raises:
            WebSocketConnectionError: If registration fails
        """
        try:
            # Check connection limits
            if len(self.connections) >= self.max_connections:
                raise WebSocketConnectionError("Maximum connections exceeded")
            
            # Generate connection ID
            connection_id = str(uuid.uuid4())
            
            # Create connection object
            connection = WebSocketConnection(
                connection_id=connection_id,
                websocket=websocket,
                session_id=session_id,
                state=ConnectionState.CONNECTED
            )
            
            # Store connection
            self.connections[connection_id] = connection
            
            # Update session mapping if session_id provided
            if session_id:
                if session_id not in self.session_connections:
                    self.session_connections[session_id] = set()
                
                # Check per-session limits
                if len(self.session_connections[session_id]) >= self.max_connections_per_session:
                    # Remove oldest connection for this session
                    await self._cleanup_oldest_session_connection(session_id)
                
                self.session_connections[session_id].add(connection_id)
            
            self.stats['connections_created'] += 1
            
            self.logger.info(f"Registered WebSocket connection {connection_id} for session {session_id}")
            return connection_id
            
        except Exception as e:
            self.logger.error(f"Failed to register connection: {e}")
            raise WebSocketConnectionError(f"Connection registration failed: {e}")
    
    async def authenticate_connection(self, connection_id: str, session_id: str) -> bool:
        """
        Authenticate a WebSocket connection with session ID
        
        Args:
            connection_id: Connection identifier
            session_id: Session identifier for authentication
            
        Returns:
            bool: True if authentication successful
        """
        try:
            connection = self.connections.get(connection_id)
            if not connection:
                raise AuthenticationError("Connection not found")
            
            if not connection.is_alive():
                raise AuthenticationError("Connection is not alive")
            
            # TODO: Add session validation logic here
            # For now, we'll accept any non-empty session_id
            if not session_id or not session_id.strip():
                raise AuthenticationError("Invalid session ID")
            
            # Update connection
            old_session_id = connection.session_id
            connection.session_id = session_id
            connection.state = ConnectionState.AUTHENTICATED
            connection.update_activity()
            
            # Update session mappings
            if old_session_id and old_session_id != session_id:
                # Remove from old session
                if old_session_id in self.session_connections:
                    self.session_connections[old_session_id].discard(connection_id)
                    if not self.session_connections[old_session_id]:
                        del self.session_connections[old_session_id]
            
            # Add to new session
            if session_id not in self.session_connections:
                self.session_connections[session_id] = set()
            
            self.session_connections[session_id].add(connection_id)
            
            self.stats['connections_authenticated'] += 1
            
            self.logger.info(f"Authenticated connection {connection_id} for session {session_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Authentication failed for connection {connection_id}: {e}")
            return False
    
    async def unregister_connection(self, connection_id: str):
        """
        Unregister a WebSocket connection
        
        Args:
            connection_id: Connection identifier
        """
        try:
            connection = self.connections.get(connection_id)
            if not connection:
                return
            
            # Update state
            connection.state = ConnectionState.DISCONNECTING
            
            # Remove from session mapping
            if connection.session_id:
                session_connections = self.session_connections.get(connection.session_id, set())
                session_connections.discard(connection_id)
                
                if not session_connections:
                    self.session_connections.pop(connection.session_id, None)
            
            # Remove connection
            self.connections.pop(connection_id, None)
            
            self.stats['connections_closed'] += 1
            
            self.logger.info(f"Unregistered connection {connection_id}")
            
        except Exception as e:
            self.logger.error(f"Error unregistering connection {connection_id}: {e}")
    
    async def send_message_to_session(
        self, 
        session_id: str, 
        message: Dict[str, Any]
    ) -> int:
        """
        Send message to all connections for a specific session
        
        Args:
            session_id: Target session ID
            message: Message to send
            
        Returns:
            int: Number of successful deliveries
        """
        try:
            connection_ids = self.session_connections.get(session_id, set())
            if not connection_ids:
                self.logger.debug(f"No connections found for session {session_id}")
                return 0
            
            # Prepare message
            message_text = json.dumps(message)
            successful_deliveries = 0
            failed_connections = []
            
            # Send to all connections for this session
            for connection_id in list(connection_ids):  # Create copy to avoid modification during iteration
                try:
                    connection = self.connections.get(connection_id)
                    if not connection or not connection.is_alive():
                        failed_connections.append(connection_id)
                        continue
                    
                    await connection.websocket.send(message_text)
                    connection.update_activity()
                    successful_deliveries += 1
                    
                except (ConnectionClosed, WebSocketException) as e:
                    self.logger.debug(f"Connection {connection_id} closed: {e}")
                    failed_connections.append(connection_id)
                    
                except Exception as e:
                    self.logger.error(f"Failed to send message to connection {connection_id}: {e}")
                    failed_connections.append(connection_id)
                    self.stats['messages_failed'] += 1
            
            # Clean up failed connections
            for connection_id in failed_connections:
                await self.unregister_connection(connection_id)
            
            self.stats['messages_sent'] += successful_deliveries
            
            self.logger.debug(
                f"Sent message to session {session_id}: "
                f"{successful_deliveries}/{len(connection_ids)} successful"
            )
            
            return successful_deliveries
            
        except Exception as e:
            self.logger.error(f"Error sending message to session {session_id}: {e}")
            self.stats['messages_failed'] += 1
            return 0
    
    async def send_message_to_connection(
        self, 
        connection_id: str, 
        message: Dict[str, Any]
    ) -> bool:
        """
        Send message to a specific connection
        
        Args:
            connection_id: Target connection ID
            message: Message to send
            
        Returns:
            bool: True if delivery successful
        """
        try:
            connection = self.connections.get(connection_id)
            if not connection or not connection.is_alive():
                return False
            
            message_text = json.dumps(message)
            await connection.websocket.send(message_text)
            connection.update_activity()
            
            self.stats['messages_sent'] += 1
            return True
            
        except (ConnectionClosed, WebSocketException):
            await self.unregister_connection(connection_id)
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to send message to connection {connection_id}: {e}")
            self.stats['messages_failed'] += 1
            return False
    
    def get_connection_count(self) -> int:
        """Get total number of active connections"""
        return len(self.connections)
    
    def get_session_count(self) -> int:
        """Get number of sessions with active connections"""
        return len(self.session_connections)
    
    def get_connections_for_session(self, session_id: str) -> List[str]:
        """Get all connection IDs for a session"""
        return list(self.session_connections.get(session_id, set()))
    
    def get_connection_info(self, connection_id: str) -> Optional[Dict[str, Any]]:
        """Get connection information"""
        connection = self.connections.get(connection_id)
        if not connection:
            return None
        
        return {
            'connection_id': connection.connection_id,
            'session_id': connection.session_id,
            'state': connection.state.value,
            'connected_at': connection.connected_at.isoformat(),
            'uptime': connection.get_uptime().total_seconds(),
            'last_activity': connection.last_activity.isoformat(),
            'is_alive': connection.is_alive(),
            'metadata': connection.metadata
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get connection manager statistics"""
        return {
            **self.stats,
            'active_connections': len(self.connections),
            'active_sessions': len(self.session_connections),
            'nats_connected': self.nats_client is not None and not self.nats_client.is_closed,
            'manager_running': self._running
        }
    
    async def _connect_nats(self) -> bool:
        """Connect to NATS for message routing"""
        try:
            self.nats_client = await nats.connect(self.config.nats_url)
            self.logger.info("Connected to NATS for WebSocket message routing")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to connect to NATS: {e}")
            return False
    
    async def _setup_nats_subscription(self) -> bool:
        """Setup NATS subscription for answer routing"""
        try:
            if not self.nats_client:
                return False
            
            # Get JetStream context
            js = self.nats_client.jetstream()
            
            # Subscribe to answers.* wildcard pattern
            self.nats_subscription = await js.subscribe(
                "answers.*",
                cb=self._handle_nats_message,
                config=ConsumerConfig(
                    durable_name="websocket-router",
                    deliver_policy=DeliverPolicy.NEW,
                    ack_policy=AckPolicy.EXPLICIT
                )
            )
            
            self.logger.info("Setup NATS subscription for answer routing")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to setup NATS subscription: {e}")
            return False
    
    async def _handle_nats_message(self, msg):
        """Handle incoming NATS messages for routing"""
        try:
            # Extract session ID from subject (answers.{session_id})
            subject_parts = msg.subject.split('.')
            if len(subject_parts) != 2 or subject_parts[0] != 'answers':
                await msg.ack()
                return
            
            session_id = subject_parts[1]
            
            # Parse message data
            try:
                message_data = json.loads(msg.data.decode())
            except json.JSONDecodeError as e:
                self.logger.error(f"Invalid JSON in NATS message: {e}")
                await msg.ack()
                return
            
            # Route to WebSocket connections
            delivered = await self.send_message_to_session(session_id, message_data)
            
            if delivered > 0:
                self.logger.debug(f"Routed answer to {delivered} connections for session {session_id}")
            else:
                self.logger.debug(f"No active connections for session {session_id}")
            
            await msg.ack()
            
        except Exception as e:
            self.logger.error(f"Error handling NATS message: {e}")
            # Still acknowledge to avoid redelivery
            await msg.ack()
    
    async def _heartbeat_loop(self):
        """Background task for sending heartbeats"""
        while self._running:
            try:
                await self._send_heartbeats()
                await asyncio.sleep(self.heartbeat_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in heartbeat loop: {e}")
                await asyncio.sleep(5)  # Brief pause on error
    
    async def _send_heartbeats(self):
        """Send heartbeat messages to all connections"""
        if not self.connections:
            return
        
        heartbeat_message = {
            'type': 'heartbeat',
            'timestamp': datetime.now().isoformat()
        }
        
        failed_connections = []
        successful_heartbeats = 0
        
        for connection_id, connection in self.connections.items():
            if not connection.is_alive():
                failed_connections.append(connection_id)
                continue
            
            try:
                await connection.websocket.ping()
                connection.last_heartbeat = datetime.now()
                successful_heartbeats += 1
                
            except (ConnectionClosed, WebSocketException):
                failed_connections.append(connection_id)
                
            except Exception as e:
                self.logger.debug(f"Heartbeat failed for connection {connection_id}: {e}")
                failed_connections.append(connection_id)
        
        # Clean up failed connections
        for connection_id in failed_connections:
            await self.unregister_connection(connection_id)
        
        if successful_heartbeats > 0:
            self.stats['heartbeats_sent'] += successful_heartbeats
            self.logger.debug(f"Sent heartbeat to {successful_heartbeats} connections")
    
    async def _cleanup_loop(self):
        """Background task for connection cleanup"""
        while self._running:
            try:
                await self._cleanup_stale_connections()
                await asyncio.sleep(60)  # Run cleanup every minute
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in cleanup loop: {e}")
                await asyncio.sleep(5)
    
    async def _cleanup_stale_connections(self):
        """Clean up stale and inactive connections"""
        if not self.connections:
            return
        
        current_time = datetime.now()
        timeout_threshold = current_time - timedelta(seconds=self.connection_timeout)
        
        stale_connections = []
        
        for connection_id, connection in self.connections.items():
            # Check if connection is stale
            if (connection.last_activity < timeout_threshold or 
                not connection.is_alive()):
                stale_connections.append(connection_id)
        
        # Remove stale connections
        for connection_id in stale_connections:
            await self.unregister_connection(connection_id)
            self.logger.debug(f"Cleaned up stale connection {connection_id}")
        
        if stale_connections:
            self.logger.info(f"Cleaned up {len(stale_connections)} stale connections")
        
        self.stats['cleanup_runs'] += 1
    
    async def _cleanup_oldest_session_connection(self, session_id: str):
        """Remove oldest connection for a session to enforce limits"""
        connection_ids = self.session_connections.get(session_id, set())
        if not connection_ids:
            return
        
        # Find oldest connection
        oldest_connection_id = None
        oldest_time = datetime.now()
        
        for connection_id in connection_ids:
            connection = self.connections.get(connection_id)
            if connection and connection.connected_at < oldest_time:
                oldest_time = connection.connected_at
                oldest_connection_id = connection_id
        
        if oldest_connection_id:
            await self.unregister_connection(oldest_connection_id)
            self.logger.info(f"Removed oldest connection {oldest_connection_id} for session {session_id}")
    
    async def _close_all_connections(self):
        """Close all active connections"""
        if not self.connections:
            return
        
        connection_ids = list(self.connections.keys())
        close_message = {
            'type': 'server_shutdown',
            'message': 'Server is shutting down'
        }
        
        # Send close message to all connections
        for connection_id in connection_ids:
            try:
                connection = self.connections.get(connection_id)
                if connection and connection.is_alive():
                    await connection.websocket.send(json.dumps(close_message))
                    await connection.websocket.close()
            except Exception as e:
                self.logger.debug(f"Error closing connection {connection_id}: {e}")
            
            await self.unregister_connection(connection_id)
        
        self.logger.info(f"Closed {len(connection_ids)} connections")


# Global instance (singleton pattern)
_websocket_manager: Optional[WebSocketConnectionManager] = None


def get_websocket_manager() -> WebSocketConnectionManager:
    """Get global WebSocket connection manager instance"""
    global _websocket_manager
    if _websocket_manager is None:
        _websocket_manager = WebSocketConnectionManager()
    return _websocket_manager