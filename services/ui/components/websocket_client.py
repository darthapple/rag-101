"""
WebSocket Client Component

Handles WebSocket connections for real-time answer streaming in the Streamlit UI.
Manages connection lifecycle, message handling, and integration with chat interface.
"""

import asyncio
import json
import logging
import threading
import time
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime
import streamlit as st
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException


class WebSocketClient:
    """WebSocket client for real-time communication with RAG-101 API service"""
    
    def __init__(self, config: Dict[str, Any], session_id: str):
        """Initialize WebSocket client"""
        self.config = config
        self.session_id = session_id
        self.ws_base_url = config.get('ws_base_url', 'ws://localhost:8000')
        self.logger = logging.getLogger("ui.websocket_client")
        
        # Connection state
        self.websocket = None
        self.connected = False
        self.connecting = False
        self.connection_thread = None
        self.message_handlers: Dict[str, Callable] = {}
        
        # Event loop for asyncio operations
        self.loop = None
        self.should_run = False
        
        # Message queue for thread-safe communication
        self.message_queue = []
        self.queue_lock = threading.Lock()
    
    async def connect(self) -> bool:
        """
        Connect to WebSocket server
        
        Returns:
            bool: True if connection successful
        """
        if self.connected or self.connecting:
            return self.connected
        
        try:
            self.connecting = True
            self.logger.info(f"Connecting to WebSocket: {self.ws_base_url}")
            
            # Build WebSocket URL with session ID
            ws_url = f"{self.ws_base_url}/ws/connect?session_id={self.session_id}"
            
            # Connect to WebSocket
            self.websocket = await websockets.connect(
                ws_url,
                ping_interval=30,
                ping_timeout=10,
                close_timeout=10
            )
            
            self.connected = True
            self.connecting = False
            
            # Update session state
            st.session_state.websocket_connected = True
            
            self.logger.info("WebSocket connected successfully")
            
            # Send authentication message
            await self._send_auth_message()
            
            return True
            
        except Exception as e:
            self.logger.error(f"WebSocket connection failed: {e}")
            self.connected = False
            self.connecting = False
            st.session_state.websocket_connected = False
            return False
    
    async def disconnect(self):
        """Disconnect from WebSocket server"""
        try:
            self.should_run = False
            
            if self.websocket and not self.websocket.closed:
                await self.websocket.close()
            
            self.connected = False
            st.session_state.websocket_connected = False
            
            self.logger.info("WebSocket disconnected")
            
        except Exception as e:
            self.logger.error(f"Error disconnecting WebSocket: {e}")
    
    async def _send_auth_message(self):
        """Send authentication message to WebSocket server"""
        try:
            auth_message = {
                "type": "authenticate",
                "session_id": self.session_id
            }
            
            await self.websocket.send(json.dumps(auth_message))
            self.logger.info("Authentication message sent")
            
        except Exception as e:
            self.logger.error(f"Failed to send authentication: {e}")
    
    async def send_message(self, message: Dict[str, Any]) -> bool:
        """
        Send message to WebSocket server
        
        Args:
            message: Message dictionary to send
            
        Returns:
            bool: True if sent successfully
        """
        if not self.connected or not self.websocket:
            return False
        
        try:
            message_json = json.dumps(message)
            await self.websocket.send(message_json)
            self.logger.debug(f"Sent WebSocket message: {message}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to send WebSocket message: {e}")
            return False
    
    async def listen_for_messages(self):
        """Listen for incoming WebSocket messages"""
        if not self.websocket:
            return
        
        try:
            async for message in self.websocket:
                try:
                    # Parse message
                    data = json.loads(message)
                    await self._handle_message(data)
                    
                except json.JSONDecodeError as e:
                    self.logger.error(f"Invalid JSON received: {e}")
                    
                except Exception as e:
                    self.logger.error(f"Error handling message: {e}")
                    
        except ConnectionClosed:
            self.logger.info("WebSocket connection closed")
            self.connected = False
            st.session_state.websocket_connected = False
            
        except Exception as e:
            self.logger.error(f"Error listening for messages: {e}")
            self.connected = False
            st.session_state.websocket_connected = False
    
    async def _handle_message(self, data: Dict[str, Any]):
        """
        Handle incoming WebSocket message
        
        Args:
            data: Parsed message data
        """
        message_type = data.get('type', 'unknown')
        
        self.logger.debug(f"Received WebSocket message: {message_type}")
        
        # Handle different message types
        if message_type == 'answer_chunk':
            await self._handle_answer_chunk(data)
        elif message_type == 'answer_complete':
            await self._handle_answer_complete(data)
        elif message_type == 'authentication_success':
            await self._handle_auth_success(data)
        elif message_type == 'authentication_error':
            await self._handle_auth_error(data)
        elif message_type == 'error':
            await self._handle_error(data)
        elif message_type == 'pong':
            await self._handle_pong(data)
        else:
            self.logger.warning(f"Unknown message type: {message_type}")
    
    async def _handle_answer_chunk(self, data: Dict[str, Any]):
        """Handle streaming answer chunk"""
        try:
            question_id = data.get('question_id')
            chunk = data.get('chunk', '')
            
            # Add to message queue for main thread to process
            with self.queue_lock:
                self.message_queue.append({
                    'type': 'answer_chunk',
                    'question_id': question_id,
                    'chunk': chunk,
                    'timestamp': datetime.now()
                })
                
        except Exception as e:
            self.logger.error(f"Error handling answer chunk: {e}")
    
    async def _handle_answer_complete(self, data: Dict[str, Any]):
        """Handle complete answer message"""
        try:
            question_id = data.get('question_id')
            answer = data.get('answer', '')
            sources = data.get('sources', [])
            confidence = data.get('confidence_score')
            
            # Add to message queue
            with self.queue_lock:
                self.message_queue.append({
                    'type': 'answer_complete',
                    'question_id': question_id,
                    'answer': answer,
                    'sources': sources,
                    'confidence_score': confidence,
                    'timestamp': datetime.now()
                })
                
        except Exception as e:
            self.logger.error(f"Error handling complete answer: {e}")
    
    async def _handle_auth_success(self, data: Dict[str, Any]):
        """Handle authentication success"""
        self.logger.info("WebSocket authentication successful")
        st.session_state.websocket_authenticated = True
    
    async def _handle_auth_error(self, data: Dict[str, Any]):
        """Handle authentication error"""
        error_msg = data.get('message', 'Authentication failed')
        self.logger.error(f"WebSocket authentication failed: {error_msg}")
        st.session_state.websocket_authenticated = False
    
    async def _handle_error(self, data: Dict[str, Any]):
        """Handle error message"""
        error_msg = data.get('message', 'Unknown error')
        self.logger.error(f"WebSocket error: {error_msg}")
        
        # Add error to message queue
        with self.queue_lock:
            self.message_queue.append({
                'type': 'error',
                'message': error_msg,
                'timestamp': datetime.now()
            })
    
    async def _handle_pong(self, data: Dict[str, Any]):
        """Handle pong response"""
        self.logger.debug("Received pong from server")
    
    def get_queued_messages(self) -> List[Dict[str, Any]]:
        """
        Get and clear queued messages from WebSocket thread
        
        Returns:
            List of message dictionaries
        """
        with self.queue_lock:
            messages = self.message_queue.copy()
            self.message_queue.clear()
            return messages
    
    def start_background_connection(self):
        """Start WebSocket connection in background thread"""
        if self.connection_thread and self.connection_thread.is_alive():
            return
        
        self.should_run = True
        self.connection_thread = threading.Thread(target=self._run_websocket_loop)
        self.connection_thread.daemon = True
        self.connection_thread.start()
    
    def stop_background_connection(self):
        """Stop background WebSocket connection"""
        self.should_run = False
        
        if self.connection_thread and self.connection_thread.is_alive():
            self.connection_thread.join(timeout=5)
    
    def _run_websocket_loop(self):
        """Run WebSocket event loop in background thread"""
        try:
            # Create new event loop for this thread
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
            # Run the connection and message handling
            self.loop.run_until_complete(self._websocket_main_loop())
            
        except Exception as e:
            self.logger.error(f"WebSocket loop error: {e}")
        finally:
            if self.loop:
                self.loop.close()
    
    async def _websocket_main_loop(self):
        """Main WebSocket connection loop"""
        while self.should_run:
            try:
                # Attempt connection
                if not self.connected:
                    success = await self.connect()
                    if not success:
                        await asyncio.sleep(5)  # Wait before retry
                        continue
                
                # Listen for messages
                await self.listen_for_messages()
                
            except Exception as e:
                self.logger.error(f"WebSocket main loop error: {e}")
                self.connected = False
                st.session_state.websocket_connected = False
                await asyncio.sleep(5)  # Wait before retry
    
    async def send_ping(self) -> bool:
        """
        Send ping to keep connection alive
        
        Returns:
            bool: True if ping sent successfully
        """
        ping_message = {
            "type": "ping",
            "timestamp": datetime.now().isoformat()
        }
        
        return await self.send_message(ping_message)
    
    def get_connection_status(self) -> Dict[str, Any]:
        """Get current connection status"""
        return {
            'connected': self.connected,
            'connecting': self.connecting,
            'authenticated': st.session_state.get('websocket_authenticated', False),
            'session_id': self.session_id,
            'ws_url': f"{self.ws_base_url}/ws/connect"
        }


# Global WebSocket client instance
_websocket_client: Optional[WebSocketClient] = None


def get_websocket_client(config: Dict[str, Any], session_id: str) -> WebSocketClient:
    """Get or create global WebSocket client instance"""
    global _websocket_client
    
    # Create new client if needed or session changed
    if (_websocket_client is None or 
        _websocket_client.session_id != session_id):
        
        # Stop old client if exists
        if _websocket_client:
            _websocket_client.stop_background_connection()
        
        # Create new client
        _websocket_client = WebSocketClient(config, session_id)
    
    return _websocket_client


def initialize_websocket_integration():
    """Initialize WebSocket integration in Streamlit session state"""
    if 'websocket_connected' not in st.session_state:
        st.session_state.websocket_connected = False
    
    if 'websocket_authenticated' not in st.session_state:
        st.session_state.websocket_authenticated = False
    
    if 'websocket_messages' not in st.session_state:
        st.session_state.websocket_messages = []


def process_websocket_messages(chat_interface):
    """Process queued WebSocket messages and update chat interface"""
    if not st.session_state.get('session_id'):
        return
    
    config = st.session_state.get('config', {})
    session_id = st.session_state.session_id
    
    # Get WebSocket client
    ws_client = get_websocket_client(config, session_id)
    
    # Get queued messages
    messages = ws_client.get_queued_messages()
    
    for message in messages:
        message_type = message.get('type')
        
        if message_type == 'answer_chunk':
            # Update streaming message
            chunk = message.get('chunk', '')
            chat_interface.add_streaming_message(chunk, is_complete=False)
            
        elif message_type == 'answer_complete':
            # Complete the streaming message
            answer = message.get('answer', '')
            sources = message.get('sources', [])
            confidence = message.get('confidence_score')
            
            # Add complete assistant message
            assistant_message = {
                'type': 'assistant',
                'content': answer,
                'timestamp': datetime.now().strftime("%H:%M:%S"),
                'sources': sources,
                'confidence_score': confidence,
                'complete': True
            }
            st.session_state.chat_history.append(assistant_message)
            
        elif message_type == 'error':
            # Add error message
            error_msg = message.get('message', 'WebSocket error')
            chat_interface._add_error_message(f"WebSocket: {error_msg}")
    
    # Trigger rerun if messages were processed
    if messages:
        st.rerun()


def ensure_websocket_connection():
    """Ensure WebSocket connection is active for current session"""
    if not st.session_state.get('session_id'):
        return False
    
    config = st.session_state.get('config', {})
    session_id = st.session_state.session_id
    
    # Get WebSocket client
    ws_client = get_websocket_client(config, session_id)
    
    # Start connection if not already running
    if not ws_client.connected and not ws_client.connecting:
        ws_client.start_background_connection()
        
    return ws_client.connected