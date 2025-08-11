"""
Session Manager

Handles session lifecycle management using NATS Key-Value store with TTL-based expiration.
Provides session creation, validation, and cleanup functionality.
"""

import asyncio
import logging
import json
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass, field

import nats
from nats.aio.client import Client as NATS
from nats.js.api import KeyValueConfig, StorageType
from nats.js.errors import KeyNotFoundError, BucketNotFoundError

from .config import get_config


@dataclass
class Session:
    """Session data model"""
    session_id: str
    nickname: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    last_activity: datetime = field(default_factory=datetime.now)
    question_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert session to dictionary for storage"""
        return {
            'session_id': self.session_id,
            'nickname': self.nickname,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'metadata': self.metadata,
            'last_activity': self.last_activity.isoformat() if self.last_activity else None,
            'question_count': self.question_count
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Session':
        """Create session from dictionary"""
        return cls(
            session_id=data['session_id'],
            nickname=data.get('nickname'),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.now(),
            expires_at=datetime.fromisoformat(data['expires_at']) if data.get('expires_at') else None,
            metadata=data.get('metadata', {}),
            last_activity=datetime.fromisoformat(data['last_activity']) if data.get('last_activity') else datetime.now(),
            question_count=data.get('question_count', 0)
        )
    
    def is_expired(self) -> bool:
        """Check if session has expired"""
        if not self.expires_at:
            return False
        return datetime.now() > self.expires_at
    
    def is_active(self) -> bool:
        """Check if session is active (not expired)"""
        return not self.is_expired()
    
    def update_activity(self):
        """Update last activity timestamp"""
        self.last_activity = datetime.now()
    
    def increment_question_count(self):
        """Increment question count"""
        self.question_count += 1
        self.update_activity()


class SessionManagerError(Exception):
    """Base exception for session manager errors"""
    pass


class SessionNotFoundError(SessionManagerError):
    """Exception raised when session is not found"""
    pass


class SessionExpiredError(SessionManagerError):
    """Exception raised when session has expired"""
    pass


class SessionValidationError(SessionManagerError):
    """Exception raised when session validation fails"""
    pass


class NATSSessionManager:
    """
    NATS Key-Value based session manager for the RAG system.
    
    Provides session lifecycle management with automatic TTL-based cleanup.
    """
    
    def __init__(self, bucket_name: str = "sessions"):
        """
        Initialize NATS session manager
        
        Args:
            bucket_name: Name of the NATS KV bucket for sessions
        """
        self.config = get_config()
        self.logger = logging.getLogger("session.manager")
        self.bucket_name = bucket_name
        
        # NATS client and KV bucket
        self.nats_client: Optional[NATS] = None
        self.kv_bucket = None
        
        # Configuration
        self.default_ttl = self.config.session_ttl
        self.max_ttl = 86400  # 24 hours maximum
        self.min_ttl = 60     # 1 minute minimum
        
        self._connected = False
        self._connection_lock = asyncio.Lock()
        
        self.logger.info(f"Initialized NATS session manager with bucket '{bucket_name}'")
    
    async def connect(self) -> bool:
        """
        Connect to NATS and setup KV bucket
        
        Returns:
            bool: True if connected successfully
        """
        async with self._connection_lock:
            if self._connected:
                return True
            
            try:
                self.logger.info("Connecting to NATS for session management...")
                
                # Connect to NATS
                self.nats_client = await nats.connect(
                    servers=self.config.nats_servers,
                    max_reconnect_attempts=self.config.max_reconnect_attempts,
                    reconnect_time_wait=self.config.reconnect_time_wait,
                    ping_interval=self.config.ping_interval,
                    max_outstanding_pings=self.config.max_outstanding_pings
                )
                
                # Get JetStream context
                js = self.nats_client.jetstream()
                
                # Create or get KV bucket
                try:
                    self.kv_bucket = await js.key_value(self.bucket_name)
                    self.logger.info(f"Using existing KV bucket '{self.bucket_name}'")
                except BucketNotFoundError:
                    # Create new bucket
                    bucket_config = KeyValueConfig(
                        bucket=self.bucket_name,
                        description="Session storage for RAG-101 Q&A system",
                        max_value_size=10240,  # 10KB per session
                        storage=StorageType.MEMORY,  # Use memory storage for sessions
                        num_replicas=1,
                        ttl=self.default_ttl  # Default TTL for all keys
                    )
                    
                    self.kv_bucket = await js.create_key_value(bucket_config)
                    self.logger.info(f"Created new KV bucket '{self.bucket_name}'")
                
                self._connected = True
                self.logger.info("NATS session manager connected successfully")
                return True
                
            except Exception as e:
                self.logger.error(f"Failed to connect to NATS: {e}")
                self._connected = False
                return False
    
    async def disconnect(self):
        """Disconnect from NATS"""
        try:
            if self.nats_client and not self.nats_client.is_closed:
                await self.nats_client.close()
            
            self._connected = False
            self.nats_client = None
            self.kv_bucket = None
            
            self.logger.info("Disconnected from NATS session manager")
            
        except Exception as e:
            self.logger.error(f"Error disconnecting from NATS: {e}")
    
    async def _ensure_connected(self):
        """Ensure NATS connection is established"""
        if not self._connected:
            success = await self.connect()
            if not success:
                raise SessionManagerError("Failed to connect to NATS")
    
    async def create_session(
        self, 
        nickname: Optional[str] = None,
        ttl: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Session:
        """
        Create a new session
        
        Args:
            nickname: Optional session nickname
            ttl: Session TTL in seconds (uses default if not specified)
            metadata: Optional session metadata
            
        Returns:
            Session: Created session object
            
        Raises:
            SessionManagerError: If session creation fails
        """
        try:
            await self._ensure_connected()
            
            # Generate unique session ID
            session_id = str(uuid.uuid4())
            
            # Validate and set TTL
            if ttl is not None:
                ttl = max(self.min_ttl, min(ttl, self.max_ttl))
            else:
                ttl = self.default_ttl
            
            # Create session object
            now = datetime.now()
            session = Session(
                session_id=session_id,
                nickname=nickname,
                created_at=now,
                expires_at=now + timedelta(seconds=ttl),
                metadata=metadata or {},
                last_activity=now,
                question_count=0
            )
            
            # Store in NATS KV
            session_data = json.dumps(session.to_dict())
            await self.kv_bucket.put(session_id, session_data.encode())
            
            self.logger.info(f"Created session {session_id} with TTL {ttl}s")
            return session
            
        except Exception as e:
            self.logger.error(f"Failed to create session: {e}")
            raise SessionManagerError(f"Session creation failed: {e}")
    
    async def get_session(self, session_id: str) -> Session:
        """
        Get session by ID
        
        Args:
            session_id: Session identifier
            
        Returns:
            Session: Session object
            
        Raises:
            SessionNotFoundError: If session doesn't exist
            SessionExpiredError: If session has expired
            SessionManagerError: If retrieval fails
        """
        try:
            await self._ensure_connected()
            
            # Get from NATS KV
            try:
                entry = await self.kv_bucket.get(session_id)
                session_data = json.loads(entry.value.decode())
                session = Session.from_dict(session_data)
                
                # Check if session is expired
                if session.is_expired():
                    # Clean up expired session
                    try:
                        await self.kv_bucket.delete(session_id)
                    except:
                        pass  # Ignore cleanup errors
                    
                    raise SessionExpiredError(f"Session {session_id} has expired")
                
                return session
                
            except KeyNotFoundError:
                raise SessionNotFoundError(f"Session {session_id} not found")
            
        except (SessionNotFoundError, SessionExpiredError):
            raise
        except Exception as e:
            self.logger.error(f"Failed to get session {session_id}: {e}")
            raise SessionManagerError(f"Session retrieval failed: {e}")
    
    async def update_session(self, session: Session, ttl: Optional[int] = None) -> Session:
        """
        Update session data
        
        Args:
            session: Session object to update
            ttl: Optional new TTL (uses remaining TTL if not specified)
            
        Returns:
            Session: Updated session object
            
        Raises:
            SessionManagerError: If update fails
        """
        try:
            await self._ensure_connected()
            
            # Update last activity
            session.update_activity()
            
            # Calculate TTL
            if ttl is not None:
                # Use provided TTL
                ttl = max(self.min_ttl, min(ttl, self.max_ttl))
                session.expires_at = datetime.now() + timedelta(seconds=ttl)
            else:
                # Use remaining TTL
                if session.expires_at:
                    remaining = (session.expires_at - datetime.now()).total_seconds()
                    ttl = max(self.min_ttl, int(remaining))
                else:
                    ttl = self.default_ttl
            
            # Store updated session
            session_data = json.dumps(session.to_dict())
            await self.kv_bucket.put(session.session_id, session_data.encode())
            
            self.logger.debug(f"Updated session {session.session_id}")
            return session
            
        except Exception as e:
            self.logger.error(f"Failed to update session {session.session_id}: {e}")
            raise SessionManagerError(f"Session update failed: {e}")
    
    async def delete_session(self, session_id: str) -> bool:
        """
        Delete session by ID
        
        Args:
            session_id: Session identifier
            
        Returns:
            bool: True if deleted successfully
            
        Raises:
            SessionManagerError: If deletion fails
        """
        try:
            await self._ensure_connected()
            
            try:
                await self.kv_bucket.delete(session_id)
                self.logger.info(f"Deleted session {session_id}")
                return True
                
            except KeyNotFoundError:
                # Session already doesn't exist
                return True
            
        except Exception as e:
            self.logger.error(f"Failed to delete session {session_id}: {e}")
            raise SessionManagerError(f"Session deletion failed: {e}")
    
    async def validate_session(self, session_id: str) -> bool:
        """
        Validate that session exists and is active
        
        Args:
            session_id: Session identifier
            
        Returns:
            bool: True if session is valid and active
        """
        try:
            session = await self.get_session(session_id)
            return session.is_active()
            
        except (SessionNotFoundError, SessionExpiredError, SessionManagerError):
            return False
    
    async def extend_session(self, session_id: str, additional_seconds: int = 3600) -> Session:
        """
        Extend session TTL
        
        Args:
            session_id: Session identifier
            additional_seconds: Additional seconds to add to TTL
            
        Returns:
            Session: Updated session object
            
        Raises:
            SessionNotFoundError: If session doesn't exist
            SessionManagerError: If extension fails
        """
        try:
            session = await self.get_session(session_id)
            
            # Calculate new expiration
            if session.expires_at:
                new_expires = session.expires_at + timedelta(seconds=additional_seconds)
                ttl = max(self.min_ttl, int((new_expires - datetime.now()).total_seconds()))
            else:
                ttl = additional_seconds
            
            session.expires_at = datetime.now() + timedelta(seconds=ttl)
            
            return await self.update_session(session, ttl=ttl)
            
        except (SessionNotFoundError, SessionExpiredError):
            raise
        except Exception as e:
            self.logger.error(f"Failed to extend session {session_id}: {e}")
            raise SessionManagerError(f"Session extension failed: {e}")
    
    async def list_active_sessions(self, limit: int = 100) -> List[Session]:
        """
        List active sessions
        
        Args:
            limit: Maximum number of sessions to return
            
        Returns:
            List[Session]: List of active sessions
        """
        try:
            await self._ensure_connected()
            
            sessions = []
            keys = await self.kv_bucket.keys()
            for key in keys:
                if len(sessions) >= limit:
                    break
                
                try:
                    entry = await self.kv_bucket.get(key)
                    session_data = json.loads(entry.value.decode())
                    session = Session.from_dict(session_data)
                    
                    if session.is_active():
                        sessions.append(session)
                        
                except Exception as e:
                    self.logger.debug(f"Skipping invalid session {key}: {e}")
            
            return sessions
            
        except Exception as e:
            self.logger.error(f"Failed to list sessions: {e}")
            return []
    
    async def get_stats(self) -> Dict[str, Any]:
        """
        Get session manager statistics
        
        Returns:
            Dict[str, Any]: Statistics
        """
        try:
            await self._ensure_connected()
            
            active_sessions = await self.list_active_sessions()
            
            stats = {
                'connected': self._connected,
                'bucket_name': self.bucket_name,
                'active_sessions': len(active_sessions),
                'default_ttl': self.default_ttl,
                'total_questions': sum(s.question_count for s in active_sessions),
            }
            
            # Session activity analysis
            if active_sessions:
                now = datetime.now()
                recent_activity = [
                    s for s in active_sessions 
                    if (now - s.last_activity).total_seconds() < 300  # 5 minutes
                ]
                stats['recently_active_sessions'] = len(recent_activity)
                
                # Average session age
                avg_age = sum((now - s.created_at).total_seconds() for s in active_sessions) / len(active_sessions)
                stats['average_session_age_seconds'] = avg_age
            else:
                stats['recently_active_sessions'] = 0
                stats['average_session_age_seconds'] = 0
            
            return stats
            
        except Exception as e:
            self.logger.error(f"Failed to get stats: {e}")
            return {
                'connected': self._connected,
                'bucket_name': self.bucket_name,
                'error': str(e)
            }


# Global session manager instance
_session_manager: Optional[NATSSessionManager] = None


def get_session_manager() -> NATSSessionManager:
    """Get global session manager instance"""
    global _session_manager
    if _session_manager is None:
        _session_manager = NATSSessionManager()
    return _session_manager