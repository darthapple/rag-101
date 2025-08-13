"""
Base handler classes and interfaces for worker processors

Provides common functionality and interfaces for all handler types including
NATS message processing, error handling, logging, and lifecycle management.
"""

import asyncio
import logging
import signal
import sys
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Callable, Type
from datetime import datetime
import json
import traceback

# Add project root to Python path
sys.path.append('/Users/fadriano/Projetos/Demos/rag-101')

import nats
from nats.js import JetStreamContext
from nats.aio.msg import Msg

from shared.config import get_config
from shared.logging import get_structured_logger, StructuredLogger
from shared.models import serialize_for_nats, deserialize_from_nats, BaseModel

logger = logging.getLogger(__name__)


class HandlerError(Exception):
    """Base exception for handler errors"""
    pass


class MessageProcessingError(HandlerError):
    """Exception raised during message processing"""
    pass


class HandlerTimeoutError(HandlerError):
    """Exception raised when handler processing times out"""
    pass


class BaseHandler(ABC):
    """
    Abstract base class for all worker handlers
    
    Provides common functionality for NATS message processing, error handling,
    and lifecycle management. Each handler type inherits from this class.
    """
    
    def __init__(self, handler_name: str, max_workers: int = 2, infra_manager=None):
        """
        Initialize base handler
        
        Args:
            handler_name: Unique name for this handler type
            max_workers: Maximum number of concurrent workers
            infra_manager: Optional InfrastructureManager instance to reuse connections
        """
        self.handler_name = handler_name
        self.max_workers = max_workers
        self.config = get_config()
        self.infra_manager = infra_manager
        
        # Connection state
        self.nc: Optional[nats.NATS] = None
        self.js: Optional[JetStreamContext] = None
        self.is_running = False
        self.shutdown_requested = False
        
        # Message processing
        self.subscription = None
        self.message_count = 0
        self.error_count = 0
        self.start_time = datetime.now()
        
        # Semaphore for concurrent processing
        self.processing_semaphore = asyncio.Semaphore(max_workers)
        
        # Setup structured logging
        self.logger = get_structured_logger(f"worker.{handler_name}", "rag-worker")
        
    @abstractmethod
    async def process_message(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a single message
        
        Args:
            data: Deserialized message data
            
        Returns:
            Dict[str, Any]: Processing result
            
        Raises:
            MessageProcessingError: If processing fails
        """
        pass
    
    @abstractmethod
    def get_subscription_subject(self) -> str:
        """
        Get the NATS subject this handler should subscribe to
        
        Returns:
            str: NATS subject pattern
        """
        pass
    
    @abstractmethod
    def get_consumer_config(self) -> Dict[str, Any]:
        """
        Get consumer configuration for this handler
        
        Returns:
            Dict[str, Any]: Consumer configuration
        """
        pass
    
    def get_result_subject(self, data: Dict[str, Any]) -> Optional[str]:
        """
        Get the subject to publish results to (optional)
        
        Args:
            data: Original message data
            
        Returns:
            Optional[str]: Result subject, or None if no result should be published
        """
        return None
    
    async def connect(self) -> bool:
        """
        Connect to NATS server with comprehensive error handling and retry logic.
        Uses shared infrastructure manager connection if available.
        
        Returns:
            bool: True if connection successful
        """
        # Try to reuse connection from infrastructure manager
        if self.infra_manager and self.infra_manager.nc and not self.infra_manager.nc.is_closed:
            self.nc = self.infra_manager.nc
            self.js = self.infra_manager.js
            
            self.logger.info(
                "Reusing NATS connection from infrastructure manager",
                handler_name=self.handler_name,
                nats_url=self.config.nats_url
            )
            return True
        
        # Fall back to creating own connection
        max_retries = 3
        retry_delay = 2.0
        
        for attempt in range(max_retries):
            try:
                self.logger.info(
                    f"Attempting NATS connection (attempt {attempt + 1}/{max_retries})",
                    nats_url=self.config.nats_url,
                    handler_name=self.handler_name,
                    attempt=attempt + 1
                )
                
                self.nc = await nats.connect(
                    servers=[self.config.nats_url],
                    max_reconnect_attempts=self.config.max_reconnect_attempts,
                    reconnect_time_wait=self.config.reconnect_time_wait,
                    ping_interval=self.config.ping_interval,
                    max_outstanding_pings=self.config.max_outstanding_pings,
                    disconnected_cb=self._on_disconnected,
                    reconnected_cb=self._on_reconnected,
                    error_cb=self._on_error
                )
                
                self.js = self.nc.jetstream()
                
                self.logger.info(
                    "Successfully connected to NATS",
                    nats_url=self.config.nats_url,
                    handler_name=self.handler_name,
                    connection_info=self.nc.connected_url
                )
                return True
                
            except ConnectionRefusedError as e:
                self.logger.error(
                    f"NATS connection refused (attempt {attempt + 1})",
                    error=e,
                    nats_url=self.config.nats_url,
                    handler_name=self.handler_name,
                    attempt=attempt + 1,
                    max_retries=max_retries
                )
                
            except asyncio.TimeoutError as e:
                self.logger.error(
                    f"NATS connection timeout (attempt {attempt + 1})",
                    error=e,
                    nats_url=self.config.nats_url,
                    handler_name=self.handler_name,
                    attempt=attempt + 1,
                    max_retries=max_retries
                )
                
            except Exception as e:
                self.logger.error(
                    f"Unexpected NATS connection error (attempt {attempt + 1})",
                    error=e,
                    nats_url=self.config.nats_url,
                    handler_name=self.handler_name,
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    error_type=type(e).__name__
                )
            
            # Wait before retry (except on last attempt)
            if attempt < max_retries - 1:
                self.logger.warning(
                    f"Retrying NATS connection in {retry_delay} seconds",
                    retry_delay=retry_delay
                )
                await asyncio.sleep(retry_delay)
                retry_delay *= 1.5  # Exponential backoff
        
        self.logger.critical(
            "Failed to connect to NATS after all retry attempts",
            nats_url=self.config.nats_url,
            handler_name=self.handler_name,
            max_retries=max_retries
        )
        return False
    
    async def disconnect(self):
        """Disconnect from NATS server"""
        if self.subscription:
            await self.subscription.unsubscribe()
            self.subscription = None
            
        if self.nc and not self.nc.is_closed:
            await self.nc.close()
            self.logger.info("Disconnected from NATS")
    
    async def start(self) -> bool:
        """
        Start the handler and begin message processing
        
        Returns:
            bool: True if started successfully
        """
        if self.is_running:
            self.logger.warning("Handler already running")
            return False
        
        try:
            # Connect to NATS
            if not await self.connect():
                return False
            
            # Create subscription
            subject = self.get_subscription_subject()
            consumer_config = self.get_consumer_config()
            
            self.subscription = await self.js.subscribe(
                subject,
                durable=consumer_config.get('durable_name', f"{self.handler_name}-consumer"),
                cb=self._message_handler,
                manual_ack=consumer_config.get('manual_ack', True),
                pending_msgs_limit=consumer_config.get('pending_msgs_limit', self.max_workers * 2),
                pending_bytes_limit=consumer_config.get('pending_bytes_limit', 1024 * 1024)  # 1MB
            )
            
            self.is_running = True
            self.start_time = datetime.now()
            self.logger.info(f"Handler '{self.handler_name}' started, subscribed to '{subject}'")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start handler: {e}")
            await self.disconnect()
            return False
    
    async def stop(self):
        """Stop the handler gracefully"""
        if not self.is_running:
            return
        
        self.logger.info(f"Stopping handler '{self.handler_name}'...")
        self.shutdown_requested = True
        
        # Wait for current processing to complete
        for _ in range(self.max_workers):
            await self.processing_semaphore.acquire()
        
        # Release semaphores
        for _ in range(self.max_workers):
            self.processing_semaphore.release()
        
        # Disconnect
        await self.disconnect()
        
        self.is_running = False
        uptime = datetime.now() - self.start_time
        self.logger.info(
            f"Handler '{self.handler_name}' stopped. "
            f"Processed {self.message_count} messages ({self.error_count} errors) "
            f"in {uptime}"
        )
    
    async def _message_handler(self, msg: Msg):
        """
        Internal message handler that wraps user processing with common functionality
        
        Args:
            msg: NATS message
        """
        if self.shutdown_requested:
            return
        
        # Acquire processing slot
        async with self.processing_semaphore:
            await self._process_single_message(msg)
    
    async def _process_single_message(self, msg: Msg):
        """
        Process a single message with comprehensive error handling, logging, and retry logic
        
        Args:
            msg: NATS message
        """
        start_time = datetime.now()
        message_id = msg.headers.get('message-id', 'unknown') if msg.headers else 'unknown'
        retry_count = int(msg.headers.get('retry-count', '0') if msg.headers else 0)
        max_retries = self.config.max_retries
        
        try:
            # Deserialize message data
            try:
                data = json.loads(msg.data.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                self.logger.error(
                    "Message deserialization failed",
                    error=e,
                    message_id=message_id,
                    handler_name=self.handler_name,
                    error_type="deserialization_error",
                    raw_data_length=len(msg.data) if msg.data else 0
                )
                raise MessageProcessingError(f"Failed to deserialize message: {e}")
            
            self.logger.debug(
                "Processing message",
                message_id=message_id,
                handler_name=self.handler_name,
                retry_count=retry_count,
                data_keys=list(data.keys()) if isinstance(data, dict) else "non-dict-data"
            )
            
            # Process the message with timeout
            try:
                processing_timeout = getattr(self.config, f'{self.handler_name.replace("-", "_")}_timeout', 60.0)
                result = await asyncio.wait_for(
                    self.process_message(data),
                    timeout=processing_timeout
                )
            except asyncio.TimeoutError:
                self.logger.error(
                    "Message processing timeout",
                    message_id=message_id,
                    handler_name=self.handler_name,
                    timeout=processing_timeout,
                    retry_count=retry_count
                )
                raise MessageProcessingError(f"Processing timeout after {processing_timeout}s")
            
            # Publish result if needed
            result_subject = self.get_result_subject(data)
            if result_subject and result:
                await self._publish_result_with_retry(result_subject, result, message_id)
            
            # Acknowledge message
            await msg.ack()
            
            # Update statistics and log success
            self.message_count += 1
            processing_time = (datetime.now() - start_time).total_seconds()
            
            self.logger.log_operation(
                f"message_processing",
                processing_time,
                success=True,
                message_id=message_id,
                handler_name=self.handler_name,
                retry_count=retry_count,
                result_published=result_subject is not None
            )
            
        except MessageProcessingError as e:
            # Handle expected processing errors
            await self._handle_processing_error(msg, message_id, e, start_time, retry_count, max_retries, "processing_error")
            
        except ConnectionError as e:
            # Handle connection errors (NATS, external services)
            await self._handle_processing_error(msg, message_id, e, start_time, retry_count, max_retries, "connection_error")
            
        except Exception as e:
            # Handle unexpected errors
            await self._handle_processing_error(msg, message_id, e, start_time, retry_count, max_retries, "unexpected_error")
    
    async def _handle_processing_error(
        self,
        msg: Msg,
        message_id: str,
        error: Exception,
        start_time: datetime,
        retry_count: int,
        max_retries: int,
        error_category: str
    ):
        """
        Handle processing errors with retry logic and structured logging
        
        Args:
            msg: NATS message
            message_id: Message identifier
            error: Exception that occurred
            start_time: Processing start time
            retry_count: Current retry count
            max_retries: Maximum retries allowed
            error_category: Category of error for logging
        """
        self.error_count += 1
        processing_time = (datetime.now() - start_time).total_seconds()
        
        # Determine if we should retry
        should_retry = retry_count < max_retries and self._is_retryable_error(error)
        
        # Log error with structured data
        log_level = "warning" if should_retry else "error"
        getattr(self.logger, log_level)(
            f"Message processing {error_category}: {str(error)}",
            error=error,
            message_id=message_id,
            handler_name=self.handler_name,
            retry_count=retry_count,
            max_retries=max_retries,
            processing_time=processing_time,
            error_category=error_category,
            will_retry=should_retry,
            error_type=type(error).__name__
        )
        
        if should_retry:
            # Calculate exponential backoff delay
            base_delay = self.config.retry_delay
            backoff_delay = base_delay * (2 ** retry_count)
            
            # Negative acknowledge with retry
            try:
                await msg.nak(delay=backoff_delay)
                self.logger.info(
                    "Message scheduled for retry",
                    message_id=message_id,
                    retry_count=retry_count + 1,
                    max_retries=max_retries,
                    retry_delay=backoff_delay
                )
            except Exception as nak_error:
                self.logger.error(
                    "Failed to NAK message for retry",
                    error=nak_error,
                    message_id=message_id,
                    handler_name=self.handler_name
                )
        else:
            # Acknowledge to prevent infinite retries
            try:
                await msg.ack()
                self.logger.error(
                    "Message permanently failed after max retries",
                    message_id=message_id,
                    handler_name=self.handler_name,
                    retry_count=retry_count,
                    max_retries=max_retries,
                    final_error=str(error)
                )
            except Exception as ack_error:
                self.logger.error(
                    "Failed to ACK failed message",
                    error=ack_error,
                    message_id=message_id,
                    handler_name=self.handler_name
                )
        
        # Publish error notification
        await self._publish_error_with_context(
            message_id, str(error), traceback.format_exc(), 
            retry_count, should_retry, error_category
        )
    
    def _is_retryable_error(self, error: Exception) -> bool:
        """
        Determine if an error is retryable
        
        Args:
            error: Exception to check
            
        Returns:
            bool: True if error should be retried
        """
        # Non-retryable errors
        non_retryable_types = (
            MessageProcessingError,  # Typically validation/logic errors
            ValueError,              # Bad input data
            KeyError,               # Missing required fields
        )
        
        # Retryable errors
        retryable_types = (
            ConnectionError,        # Network/connection issues
            TimeoutError,          # Timeout issues
            OSError,               # I/O errors
        )
        
        if isinstance(error, non_retryable_types):
            return False
        
        if isinstance(error, retryable_types):
            return True
        
        # For other errors, check the error message for known patterns
        error_msg = str(error).lower()
        retryable_patterns = [
            'connection', 'timeout', 'network', 'temporary', 'unavailable',
            'busy', 'overloaded', 'rate limit', 'throttled'
        ]
        
        return any(pattern in error_msg for pattern in retryable_patterns)
    
    async def _publish_result_with_retry(self, subject: str, result: Dict[str, Any], message_id: str):
        """
        Publish processing result to NATS with retry logic
        
        Args:
            subject: NATS subject to publish to
            result: Result data
            message_id: Original message ID
        """
        # Add demo delay before publishing to next topic
        if hasattr(self.config, 'processing_delay') and self.config.processing_delay > 0:
            self.logger.debug(
                f"Delaying {self.config.processing_delay}s before publishing to {subject}",
                message_id=message_id,
                handler_name=self.handler_name,
                delay=self.config.processing_delay
            )
            await asyncio.sleep(self.config.processing_delay)
        
        max_retries = 3
        retry_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                # Add metadata
                result_data = {
                    'handler': self.handler_name,
                    'message_id': message_id,
                    'processed_at': datetime.now().isoformat(),
                    'result': result
                }
                
                # Serialize and publish
                payload = json.dumps(result_data, default=str).encode('utf-8')
                await self.js.publish(subject, payload)
                
                self.logger.debug(
                    "Published result successfully",
                    message_id=message_id,
                    subject=subject,
                    handler_name=self.handler_name,
                    attempt=attempt + 1,
                    result_size=len(payload)
                )
                return
                
            except Exception as e:
                self.logger.warning(
                    f"Failed to publish result (attempt {attempt + 1})",
                    error=e,
                    message_id=message_id,
                    subject=subject,
                    handler_name=self.handler_name,
                    attempt=attempt + 1,
                    max_retries=max_retries
                )
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
        
        self.logger.error(
            "Failed to publish result after all retries",
            message_id=message_id,
            subject=subject,
            handler_name=self.handler_name,
            max_retries=max_retries
        )
    
    async def _publish_error_with_context(
        self,
        message_id: str,
        error: str,
        traceback_str: str,
        retry_count: int,
        will_retry: bool,
        error_category: str
    ):
        """
        Publish enhanced error notification with context
        
        Args:
            message_id: Message ID that failed
            error: Error message
            traceback_str: Error traceback
            retry_count: Current retry count
            will_retry: Whether the message will be retried
            error_category: Category of error
        """
        try:
            error_data = {
                'handler': self.handler_name,
                'message_id': message_id,
                'error': error,
                'error_category': error_category,
                'traceback': traceback_str,
                'retry_count': retry_count,
                'will_retry': will_retry,
                'timestamp': datetime.now().isoformat(),
                'handler_stats': {
                    'message_count': self.message_count,
                    'error_count': self.error_count,
                    'uptime': (datetime.now() - self.start_time).total_seconds()
                }
            }
            
            subject = f"system.errors.{self.handler_name}"
            payload = json.dumps(error_data, default=str).encode('utf-8')
            await self.js.publish(subject, payload)
            
            self.logger.debug(
                "Published error notification",
                message_id=message_id,
                error_category=error_category,
                will_retry=will_retry
            )
            
        except Exception as e:
            self.logger.critical(
                "Failed to publish error notification",
                error=e,
                message_id=message_id,
                handler_name=self.handler_name,
                original_error=error
            )
    
    async def _on_disconnected(self):
        """Callback for NATS disconnection"""
        self.logger.warning("Disconnected from NATS server")
    
    async def _on_reconnected(self):
        """Callback for NATS reconnection"""
        self.logger.info("Reconnected to NATS server")
    
    async def _on_error(self, error):
        """Callback for NATS errors"""
        self.logger.error(f"NATS error: {error}")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get handler statistics
        
        Returns:
            Dict[str, Any]: Handler statistics
        """
        uptime = datetime.now() - self.start_time if self.is_running else None
        
        return {
            'handler_name': self.handler_name,
            'is_running': self.is_running,
            'max_workers': self.max_workers,
            'message_count': self.message_count,
            'error_count': self.error_count,
            'error_rate': self.error_count / max(self.message_count, 1),
            'uptime': uptime.total_seconds() if uptime else None,
            'start_time': self.start_time.isoformat() if self.is_running else None
        }


class WorkerPool:
    """
    Manages a pool of handler instances for concurrent processing
    """
    
    def __init__(self):
        """Initialize worker pool"""
        self.handlers: List[BaseHandler] = []
        self.is_running = False
        self.shutdown_event = asyncio.Event()
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        self.logger = get_structured_logger("worker.pool", "rag-worker")
    
    def add_handler(self, handler: BaseHandler):
        """
        Add a handler to the pool
        
        Args:
            handler: Handler instance to add
        """
        self.handlers.append(handler)
        self.logger.info(f"Added handler '{handler.handler_name}' to pool")
    
    async def start_all(self) -> bool:
        """
        Start all handlers in the pool
        
        Returns:
            bool: True if all handlers started successfully
        """
        self.logger.info(f"Starting {len(self.handlers)} handlers...")
        
        success_count = 0
        for handler in self.handlers:
            try:
                if await handler.start():
                    success_count += 1
                else:
                    self.logger.error(f"Failed to start handler '{handler.handler_name}'")
            except Exception as e:
                self.logger.error(f"Error starting handler '{handler.handler_name}': {e}")
        
        self.is_running = success_count > 0
        
        if self.is_running:
            self.logger.info(f"Started {success_count}/{len(self.handlers)} handlers successfully")
        else:
            self.logger.error("Failed to start any handlers")
        
        return self.is_running
    
    async def stop_all(self):
        """Stop all handlers in the pool"""
        self.logger.info("Stopping all handlers...")
        
        # Stop all handlers concurrently
        stop_tasks = [handler.stop() for handler in self.handlers]
        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)
        
        self.is_running = False
        self.logger.info("All handlers stopped")
    
    async def wait_for_shutdown(self):
        """Wait for shutdown signal"""
        await self.shutdown_event.wait()
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.shutdown_event.set()
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics for all handlers
        
        Returns:
            Dict[str, Any]: Pool statistics
        """
        handler_stats = [handler.get_stats() for handler in self.handlers]
        
        total_messages = sum(stats['message_count'] for stats in handler_stats)
        total_errors = sum(stats['error_count'] for stats in handler_stats)
        
        return {
            'pool_status': 'running' if self.is_running else 'stopped',
            'handler_count': len(self.handlers),
            'handlers': handler_stats,
            'totals': {
                'messages_processed': total_messages,
                'errors': total_errors,
                'error_rate': total_errors / max(total_messages, 1)
            }
        }