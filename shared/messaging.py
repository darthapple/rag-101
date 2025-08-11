import os
import json
import asyncio
import logging
from typing import Dict, Any, Optional, List, Callable, Union
from datetime import datetime, timedelta
import nats
from nats.js import JetStreamContext
from nats.js.kv import KeyValue
from nats.errors import TimeoutError, NoServersError, ConnectionClosedError

logger = logging.getLogger(__name__)


class NATSConnectionError(Exception):
    """Custom exception for NATS connection errors"""
    pass


class NATSOperationError(Exception):
    """Custom exception for NATS operation errors"""
    pass


class NATSClient:
    """
    NATS client for ephemeral messaging operations
    
    Handles connection management, JetStream operations, pub/sub patterns,
    and KV store operations with TTL-based cleanup.
    """
    
    def __init__(self, 
                 servers: Union[str, List[str]] = None,
                 max_reconnect_attempts: int = 10,
                 reconnect_time_wait: float = 2.0,
                 ping_interval: float = 120.0,
                 max_outstanding_pings: int = 2):
        """
        Initialize NATS client
        
        Args:
            servers: NATS server URLs (default from env NATS_URL)
            max_reconnect_attempts: Maximum reconnection attempts
            reconnect_time_wait: Time to wait between reconnection attempts
            ping_interval: Ping interval in seconds
            max_outstanding_pings: Max outstanding pings
        """
        # Server configuration
        if servers is None:
            default_url = os.getenv('NATS_URL', 'nats://localhost:4222')
            self.servers = [default_url] if isinstance(default_url, str) else default_url
        else:
            self.servers = [servers] if isinstance(servers, str) else servers
        
        # Connection configuration
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_time_wait = reconnect_time_wait
        self.ping_interval = ping_interval
        self.max_outstanding_pings = max_outstanding_pings
        
        # Connection state
        self._nc: Optional[nats.NATS] = None
        self._js: Optional[JetStreamContext] = None
        self._kv: Optional[KeyValue] = None
        self._connected = False
        self._connection_lock = asyncio.Lock()
        
        # TTL configuration
        self.default_message_ttl = int(os.getenv('MESSAGE_TTL', '3600'))  # 1 hour
        self.default_session_ttl = int(os.getenv('SESSION_TTL', '3600'))  # 1 hour
        
        # Topic configuration
        self.topics = {
            'questions': 'questions',
            'answers': 'answers',
            'documents': 'documents.download',
            'embeddings': 'embeddings.create',
            'metrics': 'system.metrics'
        }
    
    async def connect(self) -> bool:
        """
        Establish connection to NATS server with retry logic
        
        Returns:
            bool: True if connection successful
            
        Raises:
            NATSConnectionError: If connection fails after retries
        """
        async with self._connection_lock:
            if self._connected and self._nc and not self._nc.is_closed:
                logger.info("Already connected to NATS")
                return True
            
            try:
                # Connection options
                options = {
                    "servers": self.servers,
                    "max_reconnect_attempts": self.max_reconnect_attempts,
                    "reconnect_time_wait": self.reconnect_time_wait,
                    "ping_interval": self.ping_interval,
                    "max_outstanding_pings": self.max_outstanding_pings,
                    "error_cb": self._error_cb,
                    "disconnected_cb": self._disconnected_cb,
                    "reconnected_cb": self._reconnected_cb,
                    "closed_cb": self._closed_cb
                }
                
                # Connect to NATS
                self._nc = await nats.connect(**options)
                
                # Initialize JetStream
                self._js = self._nc.jetstream()
                
                # Initialize KV store
                try:
                    self._kv = await self._js.key_value("sessions")
                except Exception:
                    # Create KV bucket if it doesn't exist
                    await self._js.create_key_value(
                        bucket="sessions",
                        ttl=self.default_session_ttl
                    )
                    self._kv = await self._js.key_value("sessions")
                
                self._connected = True
                logger.info(f"Successfully connected to NATS servers: {self.servers}")
                return True
                
            except Exception as e:
                logger.error(f"Failed to connect to NATS: {str(e)}")
                raise NATSConnectionError(f"NATS connection failed: {str(e)}")
    
    async def disconnect(self):
        """Disconnect from NATS server"""
        if self._nc and not self._nc.is_closed:
            try:
                await self._nc.close()
                self._connected = False
                self._js = None
                self._kv = None
                logger.info("Disconnected from NATS")
            except Exception as e:
                logger.error(f"Error during disconnect: {str(e)}")
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Check NATS connection and server health
        
        Returns:
            dict: Health check results with status and details
        """
        try:
            if not self._connected or not self._nc or self._nc.is_closed:
                await self.connect()
            
            # Check server info
            server_info = self._nc.connected_server_version
            
            # Check JetStream account info
            js_account_info = None
            if self._js:
                try:
                    js_account_info = await self._js.account_info()
                except Exception as e:
                    logger.warning(f"Could not get JetStream account info: {e}")
            
            # Check KV store
            kv_status = None
            if self._kv:
                try:
                    kv_status = await self._kv.status()
                except Exception as e:
                    logger.warning(f"Could not get KV status: {e}")
            
            return {
                'status': 'healthy',
                'timestamp': datetime.now().isoformat(),
                'connection': {
                    'servers': self.servers,
                    'connected': self._connected,
                    'server_version': server_info
                },
                'jetstream': {
                    'enabled': js_account_info is not None,
                    'account_info': js_account_info._asdict() if js_account_info else None
                },
                'kv_store': {
                    'enabled': kv_status is not None,
                    'bucket': 'sessions',
                    'status': kv_status._asdict() if kv_status else None
                }
            }
            
        except Exception as e:
            logger.error(f"Health check failed: {str(e)}")
            return {
                'status': 'unhealthy',
                'timestamp': datetime.now().isoformat(),
                'error': str(e)
            }
    
    # Connection event callbacks
    async def _error_cb(self, e):
        """Handle connection errors"""
        logger.error(f"NATS error: {e}")
    
    async def _disconnected_cb(self):
        """Handle disconnection"""
        logger.warning("NATS disconnected")
        self._connected = False
    
    async def _reconnected_cb(self):
        """Handle reconnection"""
        logger.info("NATS reconnected")
        self._connected = True
    
    async def _closed_cb(self):
        """Handle connection closure"""
        logger.info("NATS connection closed")
        self._connected = False
    
    @property
    def is_connected(self) -> bool:
        """Check if connected to NATS"""
        return self._connected and self._nc and not self._nc.is_closed
    
    @property
    def jetstream(self) -> Optional[JetStreamContext]:
        """Get JetStream context"""
        return self._js
    
    @property
    def kv_store(self) -> Optional[KeyValue]:
        """Get KV store"""
        return self._kv
    
    async def __aenter__(self):
        """Async context manager entry"""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.disconnect()
    
    async def create_stream(self, 
                          name: str, 
                          subjects: List[str],
                          max_age: Optional[int] = None,
                          max_msgs: int = 1000000,
                          storage: str = "memory") -> bool:
        """
        Create JetStream stream if it doesn't exist
        
        Args:
            name: Stream name
            subjects: List of subjects for the stream
            max_age: Maximum age in seconds (default: message TTL)
            max_msgs: Maximum number of messages
            storage: Storage type ("memory" or "file")
            
        Returns:
            bool: True if stream created or already exists
        """
        try:
            if not self._js:
                await self.connect()
            
            # Set default max age
            if max_age is None:
                max_age = self.default_message_ttl
            
            # Check if stream already exists
            try:
                stream_info = await self._js.stream_info(name)
                logger.info(f"Stream '{name}' already exists")
                return True
            except Exception:
                # Stream doesn't exist, create it
                pass
            
            # Create stream configuration
            from nats.js.api import StreamConfig
            
            config = StreamConfig(
                name=name,
                subjects=subjects,
                max_age=max_age,  # In seconds
                max_msgs=max_msgs,
                storage=storage
            )
            
            # Create stream
            await self._js.add_stream(config)
            logger.info(f"Created stream '{name}' with subjects {subjects}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create stream '{name}': {str(e)}")
            raise NATSOperationError(f"Stream creation failed: {str(e)}")
    
    async def create_consumer(self,
                            stream_name: str,
                            consumer_name: str,
                            subject_filter: Optional[str] = None,
                            durable: bool = True,
                            deliver_policy: str = "new",
                            ack_policy: str = "explicit",
                            max_deliver: int = 3) -> bool:
        """
        Create JetStream consumer
        
        Args:
            stream_name: Name of the stream
            consumer_name: Name of the consumer
            subject_filter: Subject filter for consumer
            durable: Whether consumer is durable
            deliver_policy: Delivery policy ("all", "last", "new")
            ack_policy: Acknowledgment policy ("explicit", "all", "none")
            max_deliver: Maximum delivery attempts
            
        Returns:
            bool: True if consumer created or already exists
        """
        try:
            if not self._js:
                await self.connect()
            
            # Check if consumer already exists
            try:
                consumer_info = await self._js.consumer_info(stream_name, consumer_name)
                logger.info(f"Consumer '{consumer_name}' already exists on stream '{stream_name}'")
                return True
            except Exception:
                # Consumer doesn't exist, create it
                pass
            
            # Create consumer configuration
            from nats.js.api import ConsumerConfig
            
            config = ConsumerConfig(
                name=consumer_name if durable else None,
                durable_name=consumer_name if durable else None,
                filter_subject=subject_filter,
                deliver_policy=deliver_policy,
                ack_policy=ack_policy,
                max_deliver=max_deliver,
                ack_wait=30,  # 30 seconds ack wait
                replay_policy="instant"
            )
            
            # Create consumer
            await self._js.add_consumer(stream_name, config)
            logger.info(f"Created consumer '{consumer_name}' on stream '{stream_name}'")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create consumer '{consumer_name}': {str(e)}")
            raise NATSOperationError(f"Consumer creation failed: {str(e)}")
    
    async def setup_default_streams(self):
        """Set up default streams for the RAG system"""
        try:
            # Questions stream
            await self.create_stream(
                name="questions",
                subjects=["questions", "questions.*"],
                max_age=self.default_message_ttl,
                storage="memory"
            )
            
            # Answers stream  
            await self.create_stream(
                name="answers",
                subjects=["answers.*"],
                max_age=self.default_message_ttl,
                storage="memory"
            )
            
            # Documents stream
            await self.create_stream(
                name="documents",
                subjects=["documents.*"],
                max_age=self.default_message_ttl,
                storage="memory"
            )
            
            # Embeddings stream
            await self.create_stream(
                name="embeddings",
                subjects=["embeddings.*"],
                max_age=self.default_message_ttl,
                storage="memory"
            )
            
            # System metrics stream
            await self.create_stream(
                name="system",
                subjects=["system.*"],
                max_age=300,  # 5 minutes for metrics
                storage="memory"
            )
            
            logger.info("Default streams set up successfully")
            
        except Exception as e:
            logger.error(f"Failed to set up default streams: {str(e)}")
            raise NATSOperationError(f"Default streams setup failed: {str(e)}")
    
    async def subscribe_to_stream(self,
                                stream_name: str,
                                consumer_name: str,
                                callback: Callable[[Dict[str, Any]], None],
                                subject_filter: Optional[str] = None,
                                batch_size: int = 1) -> bool:
        """
        Subscribe to JetStream with durable consumer
        
        Args:
            stream_name: Name of the stream
            consumer_name: Name of the consumer
            callback: Message callback function
            subject_filter: Subject filter for messages
            batch_size: Number of messages to fetch at once
            
        Returns:
            bool: True if subscription successful
        """
        try:
            if not self._js:
                await self.connect()
            
            # Create consumer if it doesn't exist
            await self.create_consumer(
                stream_name=stream_name,
                consumer_name=consumer_name,
                subject_filter=subject_filter
            )
            
            # Create pull subscription
            subscription = await self._js.pull_subscribe(
                subject=subject_filter or f"{stream_name}.*",
                durable=consumer_name,
                stream=stream_name
            )
            
            # Start consuming messages
            async def message_handler():
                while True:
                    try:
                        messages = await subscription.fetch(batch_size, timeout=30)
                        
                        for msg in messages:
                            try:
                                # Parse message data
                                if msg.data:
                                    data = json.loads(msg.data.decode())
                                    
                                    # Add message metadata
                                    data['_meta'] = {
                                        'subject': msg.subject,
                                        'sequence': msg.metadata.sequence.stream,
                                        'timestamp': msg.metadata.timestamp.isoformat(),
                                        'consumer': consumer_name
                                    }
                                    
                                    # Call user callback
                                    await callback(data)
                                    
                                    # Acknowledge message
                                    await msg.ack()
                                    
                            except Exception as e:
                                logger.error(f"Error processing message: {e}")
                                # Negative acknowledgment for retry
                                await msg.nak()
                                
                    except TimeoutError:
                        # Normal timeout, continue polling
                        continue
                    except Exception as e:
                        logger.error(f"Error fetching messages: {e}")
                        await asyncio.sleep(5)  # Back off on error
            
            # Start message handler as background task
            asyncio.create_task(message_handler())
            
            logger.info(f"Subscribed to stream '{stream_name}' with consumer '{consumer_name}'")
            return True
            
        except Exception as e:
            logger.error(f"Failed to subscribe to stream: {str(e)}")
            raise NATSOperationError(f"Stream subscription failed: {str(e)}")
    
    async def publish_message(self,
                            subject: str,
                            data: Dict[str, Any],
                            headers: Optional[Dict[str, str]] = None,
                            timeout: float = 30.0) -> str:
        """
        Publish message to NATS JetStream
        
        Args:
            subject: Subject to publish to
            data: Message data (will be JSON serialized)
            headers: Optional message headers
            timeout: Publish timeout in seconds
            
        Returns:
            str: Message sequence number
        """
        try:
            if not self._js:
                await self.connect()
            
            # Prepare message data
            message_data = json.dumps(data, default=str).encode('utf-8')
            
            # Add timestamp to headers
            if headers is None:
                headers = {}
            headers['timestamp'] = datetime.now().isoformat()
            headers['subject'] = subject
            
            # Publish message
            ack = await self._js.publish(
                subject=subject,
                payload=message_data,
                headers=headers,
                timeout=timeout
            )
            
            sequence = str(ack.seq)
            logger.debug(f"Published message to '{subject}' with sequence {sequence}")
            return sequence
            
        except Exception as e:
            logger.error(f"Failed to publish message to '{subject}': {str(e)}")
            raise NATSOperationError(f"Message publish failed: {str(e)}")
    
    async def publish_question(self, 
                             session_id: str,
                             question: str,
                             context: Optional[Dict[str, Any]] = None) -> str:
        """
        Publish question message for processing
        
        Args:
            session_id: Session identifier
            question: Question text
            context: Additional context
            
        Returns:
            str: Message sequence number
        """
        message_data = {
            'session_id': session_id,
            'question': question,
            'context': context or {},
            'timestamp': datetime.now().isoformat()
        }
        
        return await self.publish_message(
            subject=self.topics['questions'],
            data=message_data,
            headers={'session_id': session_id}
        )
    
    async def publish_answer(self,
                           session_id: str,
                           answer: str,
                           sources: Optional[List[Dict[str, Any]]] = None,
                           metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Publish answer message to session-specific topic
        
        Args:
            session_id: Session identifier
            answer: Answer text
            sources: Source documents used
            metadata: Additional metadata
            
        Returns:
            str: Message sequence number
        """
        message_data = {
            'session_id': session_id,
            'answer': answer,
            'sources': sources or [],
            'metadata': metadata or {},
            'timestamp': datetime.now().isoformat()
        }
        
        # Publish to session-specific answer topic
        answer_subject = f"{self.topics['answers']}.{session_id}"
        
        return await self.publish_message(
            subject=answer_subject,
            data=message_data,
            headers={'session_id': session_id}
        )
    
    async def publish_document_request(self,
                                     url: str,
                                     job_id: str,
                                     metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Publish document processing request
        
        Args:
            url: Document URL to process
            job_id: Processing job identifier
            metadata: Additional metadata
            
        Returns:
            str: Message sequence number
        """
        message_data = {
            'url': url,
            'job_id': job_id,
            'metadata': metadata or {},
            'timestamp': datetime.now().isoformat()
        }
        
        return await self.publish_message(
            subject=self.topics['documents'],
            data=message_data,
            headers={'job_id': job_id}
        )
    
    async def publish_embedding_request(self,
                                      chunks: List[Dict[str, Any]],
                                      job_id: str) -> str:
        """
        Publish embedding generation request
        
        Args:
            chunks: Text chunks to embed
            job_id: Processing job identifier
            
        Returns:
            str: Message sequence number
        """
        message_data = {
            'chunks': chunks,
            'job_id': job_id,
            'timestamp': datetime.now().isoformat()
        }
        
        return await self.publish_message(
            subject=self.topics['embeddings'],
            data=message_data,
            headers={'job_id': job_id}
        )
    
    async def publish_metrics(self,
                            metrics_type: str,
                            metrics_data: Dict[str, Any]) -> str:
        """
        Publish system metrics
        
        Args:
            metrics_type: Type of metrics (e.g., "processing", "health")
            metrics_data: Metrics data
            
        Returns:
            str: Message sequence number
        """
        message_data = {
            'type': metrics_type,
            'data': metrics_data,
            'timestamp': datetime.now().isoformat()
        }
        
        return await self.publish_message(
            subject=f"{self.topics['metrics']}.{metrics_type}",
            data=message_data,
            headers={'metrics_type': metrics_type}
        )
    
    async def subscribe_to_questions(self,
                                   callback: Callable[[Dict[str, Any]], None],
                                   consumer_name: str = "question_processor") -> bool:
        """
        Subscribe to questions for processing
        
        Args:
            callback: Function to handle question messages
            consumer_name: Consumer name for durable subscription
            
        Returns:
            bool: True if subscription successful
        """
        return await self.subscribe_to_stream(
            stream_name="questions",
            consumer_name=consumer_name,
            callback=callback,
            subject_filter="questions"
        )
    
    async def subscribe_to_answers(self,
                                 session_id: str,
                                 callback: Callable[[Dict[str, Any]], None],
                                 consumer_name: Optional[str] = None) -> bool:
        """
        Subscribe to answers for a specific session
        
        Args:
            session_id: Session identifier
            callback: Function to handle answer messages
            consumer_name: Consumer name (defaults to session-based name)
            
        Returns:
            bool: True if subscription successful
        """
        if consumer_name is None:
            consumer_name = f"answer_consumer_{session_id}"
        
        return await self.subscribe_to_stream(
            stream_name="answers",
            consumer_name=consumer_name,
            callback=callback,
            subject_filter=f"answers.{session_id}"
        )
    
    async def subscribe_to_documents(self,
                                   callback: Callable[[Dict[str, Any]], None],
                                   consumer_name: str = "document_processor") -> bool:
        """
        Subscribe to document processing requests
        
        Args:
            callback: Function to handle document messages
            consumer_name: Consumer name for durable subscription
            
        Returns:
            bool: True if subscription successful
        """
        return await self.subscribe_to_stream(
            stream_name="documents",
            consumer_name=consumer_name,
            callback=callback,
            subject_filter="documents.*"
        )
    
    async def subscribe_to_embeddings(self,
                                    callback: Callable[[Dict[str, Any]], None],
                                    consumer_name: str = "embedding_processor") -> bool:
        """
        Subscribe to embedding generation requests
        
        Args:
            callback: Function to handle embedding messages
            consumer_name: Consumer name for durable subscription
            
        Returns:
            bool: True if subscription successful
        """
        return await self.subscribe_to_stream(
            stream_name="embeddings",
            consumer_name=consumer_name,
            callback=callback,
            subject_filter="embeddings.*"
        )
    
    async def create_session(self,
                           session_id: str,
                           session_data: Dict[str, Any],
                           ttl: Optional[int] = None) -> bool:
        """
        Create or update a session in KV store
        
        Args:
            session_id: Session identifier
            session_data: Session data to store
            ttl: Time to live in seconds (default: session TTL)
            
        Returns:
            bool: True if session created successfully
        """
        try:
            if not self._kv:
                await self.connect()
            
            # Prepare session data with metadata
            full_session_data = {
                'session_id': session_id,
                'data': session_data,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
                'ttl': ttl or self.default_session_ttl
            }
            
            # Store in KV
            session_json = json.dumps(full_session_data, default=str)
            await self._kv.put(session_id, session_json.encode('utf-8'))
            
            logger.debug(f"Created session '{session_id}'")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create session '{session_id}': {str(e)}")
            raise NATSOperationError(f"Session creation failed: {str(e)}")
    
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve session data from KV store
        
        Args:
            session_id: Session identifier
            
        Returns:
            dict: Session data or None if not found
        """
        try:
            if not self._kv:
                await self.connect()
            
            # Get from KV store
            entry = await self._kv.get(session_id)
            
            if entry is None:
                logger.debug(f"Session '{session_id}' not found")
                return None
            
            # Parse session data
            session_data = json.loads(entry.value.decode('utf-8'))
            
            # Update last accessed time
            session_data['last_accessed_at'] = datetime.now().isoformat()
            await self.update_session(session_id, session_data['data'])
            
            logger.debug(f"Retrieved session '{session_id}'")
            return session_data
            
        except Exception as e:
            logger.error(f"Failed to get session '{session_id}': {str(e)}")
            return None
    
    async def update_session(self,
                           session_id: str,
                           session_data: Dict[str, Any]) -> bool:
        """
        Update existing session data
        
        Args:
            session_id: Session identifier
            session_data: Updated session data
            
        Returns:
            bool: True if session updated successfully
        """
        try:
            if not self._kv:
                await self.connect()
            
            # Get existing session
            existing_session = await self.get_session(session_id)
            
            if existing_session is None:
                # Create new session if it doesn't exist
                return await self.create_session(session_id, session_data)
            
            # Update session data
            existing_session['data'].update(session_data)
            existing_session['updated_at'] = datetime.now().isoformat()
            
            # Store updated data
            session_json = json.dumps(existing_session, default=str)
            await self._kv.put(session_id, session_json.encode('utf-8'))
            
            logger.debug(f"Updated session '{session_id}'")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update session '{session_id}': {str(e)}")
            return False
    
    async def delete_session(self, session_id: str) -> bool:
        """
        Delete session from KV store
        
        Args:
            session_id: Session identifier
            
        Returns:
            bool: True if session deleted successfully
        """
        try:
            if not self._kv:
                await self.connect()
            
            # Delete from KV store
            await self._kv.delete(session_id)
            
            logger.debug(f"Deleted session '{session_id}'")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete session '{session_id}': {str(e)}")
            return False
    
    async def list_sessions(self,
                          prefix: Optional[str] = None,
                          limit: int = 100) -> List[Dict[str, Any]]:
        """
        List all sessions in KV store
        
        Args:
            prefix: Optional prefix filter for session IDs
            limit: Maximum number of sessions to return
            
        Returns:
            list: List of session data
        """
        try:
            if not self._kv:
                await self.connect()
            
            # Get all keys
            keys = await self._kv.keys()
            
            # Filter by prefix if provided
            if prefix:
                keys = [key for key in keys if key.startswith(prefix)]
            
            # Limit results
            keys = keys[:limit]
            
            # Get session data for each key
            sessions = []
            for key in keys:
                session_data = await self.get_session(key)
                if session_data:
                    sessions.append(session_data)
            
            logger.debug(f"Listed {len(sessions)} sessions")
            return sessions
            
        except Exception as e:
            logger.error(f"Failed to list sessions: {str(e)}")
            return []
    
    async def session_exists(self, session_id: str) -> bool:
        """
        Check if session exists in KV store
        
        Args:
            session_id: Session identifier
            
        Returns:
            bool: True if session exists
        """
        try:
            if not self._kv:
                await self.connect()
            
            entry = await self._kv.get(session_id)
            return entry is not None
            
        except Exception as e:
            logger.error(f"Failed to check session existence '{session_id}': {str(e)}")
            return False
    
    async def get_session_metadata(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get session metadata without full data
        
        Args:
            session_id: Session identifier
            
        Returns:
            dict: Session metadata or None if not found
        """
        session_data = await self.get_session(session_id)
        
        if session_data is None:
            return None
        
        # Return only metadata, not full session data
        return {
            'session_id': session_data.get('session_id'),
            'created_at': session_data.get('created_at'),
            'updated_at': session_data.get('updated_at'),
            'last_accessed_at': session_data.get('last_accessed_at'),
            'ttl': session_data.get('ttl'),
            'has_data': bool(session_data.get('data'))
        }
    
    async def cleanup_expired_sessions(self) -> int:
        """
        Cleanup expired sessions from KV store
        
        Note: NATS KV TTL handles automatic cleanup, but this provides 
        manual cleanup capability and metrics
        
        Returns:
            int: Number of sessions cleaned up
        """
        try:
            if not self._kv:
                await self.connect()
            
            cleaned_count = 0
            sessions = await self.list_sessions()
            
            for session in sessions:
                session_id = session.get('session_id')
                created_at = session.get('created_at')
                ttl = session.get('ttl', self.default_session_ttl)
                
                if created_at:
                    # Parse creation time
                    created_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    expiry_time = created_time + timedelta(seconds=ttl)
                    
                    # Check if expired
                    if datetime.now() >= expiry_time:
                        await self.delete_session(session_id)
                        cleaned_count += 1
                        logger.debug(f"Cleaned up expired session '{session_id}'")
            
            if cleaned_count > 0:
                logger.info(f"Cleaned up {cleaned_count} expired sessions")
            
            return cleaned_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup expired sessions: {str(e)}")
            return 0
    
    async def get_stream_info(self, stream_name: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed stream information including TTL settings
        
        Args:
            stream_name: Name of the stream
            
        Returns:
            dict: Stream information or None if not found
        """
        try:
            if not self._js:
                await self.connect()
            
            stream_info = await self._js.stream_info(stream_name)
            
            return {
                'name': stream_info.config.name,
                'subjects': stream_info.config.subjects,
                'storage': stream_info.config.storage.value,
                'max_age': stream_info.config.max_age,
                'max_msgs': stream_info.config.max_msgs,
                'num_messages': stream_info.state.messages,
                'num_subjects': stream_info.state.num_subjects,
                'created': stream_info.created.isoformat(),
                'bytes': stream_info.state.bytes,
                'first_seq': stream_info.state.first_seq,
                'last_seq': stream_info.state.last_seq
            }
            
        except Exception as e:
            logger.error(f"Failed to get stream info for '{stream_name}': {str(e)}")
            return None
    
    async def get_consumer_info(self, stream_name: str, consumer_name: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed consumer information
        
        Args:
            stream_name: Name of the stream
            consumer_name: Name of the consumer
            
        Returns:
            dict: Consumer information or None if not found
        """
        try:
            if not self._js:
                await self.connect()
            
            consumer_info = await self._js.consumer_info(stream_name, consumer_name)
            
            return {
                'stream_name': consumer_info.stream_name,
                'name': consumer_info.name,
                'created': consumer_info.created.isoformat(),
                'config': {
                    'durable_name': consumer_info.config.durable_name,
                    'deliver_policy': consumer_info.config.deliver_policy.value,
                    'ack_policy': consumer_info.config.ack_policy.value,
                    'ack_wait': consumer_info.config.ack_wait,
                    'max_deliver': consumer_info.config.max_deliver,
                    'filter_subject': consumer_info.config.filter_subject,
                    'replay_policy': consumer_info.config.replay_policy.value
                },
                'delivered': {
                    'consumer_seq': consumer_info.delivered.consumer_seq,
                    'stream_seq': consumer_info.delivered.stream_seq
                },
                'ack_floor': {
                    'consumer_seq': consumer_info.ack_floor.consumer_seq,
                    'stream_seq': consumer_info.ack_floor.stream_seq
                },
                'num_pending': consumer_info.num_pending,
                'num_redelivered': consumer_info.num_redelivered
            }
            
        except Exception as e:
            logger.error(f"Failed to get consumer info for '{consumer_name}': {str(e)}")
            return None
    
    async def update_stream_ttl(self, stream_name: str, new_max_age: int) -> bool:
        """
        Update TTL (max_age) for an existing stream
        
        Args:
            stream_name: Name of the stream
            new_max_age: New maximum age in seconds
            
        Returns:
            bool: True if update successful
        """
        try:
            if not self._js:
                await self.connect()
            
            # Get current stream config
            stream_info = await self._js.stream_info(stream_name)
            config = stream_info.config
            
            # Update max_age (in seconds)
            config.max_age = new_max_age
            
            # Update stream
            await self._js.update_stream(config)
            
            logger.info(f"Updated stream '{stream_name}' TTL to {new_max_age} seconds")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update stream TTL for '{stream_name}': {str(e)}")
            return False
    
    async def purge_stream(self, stream_name: str, 
                         subject_filter: Optional[str] = None,
                         sequence: Optional[int] = None,
                         keep: Optional[int] = None) -> bool:
        """
        Manually purge messages from stream (immediate cleanup)
        
        Args:
            stream_name: Name of the stream
            subject_filter: Optional subject filter for selective purging
            sequence: Purge up to this sequence number
            keep: Keep this many messages
            
        Returns:
            bool: True if purge successful
        """
        try:
            if not self._js:
                await self.connect()
            
            # Build purge request
            purge_request = {}
            if subject_filter:
                purge_request['filter'] = subject_filter
            if sequence:
                purge_request['seq'] = sequence
            if keep:
                purge_request['keep'] = keep
            
            # Purge stream
            purge_response = await self._js.purge_stream(stream_name, **purge_request)
            
            logger.info(f"Purged stream '{stream_name}', purged: {purge_response.purged}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to purge stream '{stream_name}': {str(e)}")
            return False
    
    async def get_ttl_stats(self) -> Dict[str, Any]:
        """
        Get TTL and cleanup statistics for all streams and KV stores
        
        Returns:
            dict: TTL statistics and configuration
        """
        try:
            stats = {
                'timestamp': datetime.now().isoformat(),
                'streams': {},
                'kv_stores': {},
                'configuration': {
                    'default_message_ttl': self.default_message_ttl,
                    'default_session_ttl': self.default_session_ttl
                }
            }
            
            # Get stream stats
            stream_names = ["questions", "answers", "documents", "embeddings", "system"]
            for stream_name in stream_names:
                stream_info = await self.get_stream_info(stream_name)
                if stream_info:
                    stats['streams'][stream_name] = {
                        'max_age_seconds': stream_info['max_age'],
                        'num_messages': stream_info['num_messages'],
                        'bytes': stream_info['bytes'],
                        'created': stream_info['created']
                    }
            
            # Get KV store stats
            if self._kv:
                try:
                    kv_status = await self._kv.status()
                    stats['kv_stores']['sessions'] = {
                        'bucket': 'sessions',
                        'ttl_seconds': self.default_session_ttl,
                        'values': kv_status.values,
                        'bytes': kv_status.bytes
                    }
                except Exception as e:
                    logger.warning(f"Could not get KV store stats: {e}")
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get TTL stats: {str(e)}")
            return {
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }


# Utility functions for easy client access
def create_nats_client(servers: Union[str, List[str]] = None) -> NATSClient:
    """
    Create a NATSClient instance with default configuration
    
    Args:
        servers: NATS server URLs
        
    Returns:
        NATSClient: Configured NATS client instance
    """
    return NATSClient(servers=servers)


def get_nats_client() -> NATSClient:
    """
    Get a singleton NATSClient instance
    
    Returns:
        NATSClient: NATS client instance
    """
    if not hasattr(get_nats_client, '_instance'):
        get_nats_client._instance = NATSClient()
    
    return get_nats_client._instance


# Monitoring and metrics utilities
async def monitor_nats_health(client: NATSClient) -> Dict[str, Any]:
    """
    Comprehensive NATS health monitoring
    
    Args:
        client: NATSClient instance
        
    Returns:
        dict: Complete health and performance metrics
    """
    try:
        health_data = await client.health_check()
        ttl_stats = await client.get_ttl_stats()
        
        # Combine health check and TTL stats
        monitoring_data = {
            'timestamp': datetime.now().isoformat(),
            'overall_status': health_data.get('status', 'unknown'),
            'connection_health': health_data.get('connection', {}),
            'jetstream_health': health_data.get('jetstream', {}),
            'kv_health': health_data.get('kv_store', {}),
            'ttl_stats': ttl_stats,
            'error': health_data.get('error')
        }
        
        # Add performance metrics if available
        if client.is_connected:
            monitoring_data['performance'] = {
                'connected_servers': len(client.servers),
                'reconnection_config': {
                    'max_attempts': client.max_reconnect_attempts,
                    'wait_time': client.reconnect_time_wait,
                    'ping_interval': client.ping_interval
                }
            }
        
        return monitoring_data
        
    except Exception as e:
        logger.error(f"NATS health monitoring failed: {str(e)}")
        return {
            'timestamp': datetime.now().isoformat(),
            'overall_status': 'error',
            'error': str(e)
        }