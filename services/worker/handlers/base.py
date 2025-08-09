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
    
    def __init__(self, handler_name: str, max_workers: int = 2):
        """
        Initialize base handler
        
        Args:
            handler_name: Unique name for this handler type
            max_workers: Maximum number of concurrent workers
        """
        self.handler_name = handler_name
        self.max_workers = max_workers
        self.config = get_config()
        
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
        
        # Setup logging
        self.logger = logging.getLogger(f"worker.{handler_name}")
        
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
        Connect to NATS server
        
        Returns:
            bool: True if connection successful
        """
        try:
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
            self.logger.info(f"Connected to NATS at {self.config.nats_url}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to connect to NATS: {e}")
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
        Process a single message with error handling and logging
        
        Args:
            msg: NATS message
        """
        start_time = datetime.now()
        message_id = msg.headers.get('message-id', 'unknown') if msg.headers else 'unknown'
        
        try:
            # Deserialize message data
            try:
                data = json.loads(msg.data.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise MessageProcessingError(f"Failed to deserialize message: {e}")
            
            self.logger.debug(f"Processing message {message_id}: {data}")
            
            # Process the message
            result = await self.process_message(data)
            
            # Publish result if needed
            result_subject = self.get_result_subject(data)
            if result_subject and result:
                await self._publish_result(result_subject, result, message_id)
            
            # Acknowledge message
            await msg.ack()
            
            # Update statistics
            self.message_count += 1
            processing_time = (datetime.now() - start_time).total_seconds()
            
            self.logger.info(
                f"Message {message_id} processed successfully in {processing_time:.2f}s"
            )
            
        except Exception as e:
            # Handle processing error
            self.error_count += 1
            processing_time = (datetime.now() - start_time).total_seconds()
            
            error_msg = f"Error processing message {message_id}: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            
            # Negative acknowledge with retry
            try:
                await msg.nak(delay=self.config.retry_delay)
            except Exception as nak_error:
                self.logger.error(f"Failed to NAK message: {nak_error}")
            
            # Publish error notification if configured
            await self._publish_error(message_id, str(e), traceback.format_exc())
    
    async def _publish_result(self, subject: str, result: Dict[str, Any], message_id: str):
        """
        Publish processing result to NATS
        
        Args:
            subject: NATS subject to publish to
            result: Result data
            message_id: Original message ID
        """
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
            
            self.logger.debug(f"Published result for message {message_id} to {subject}")
            
        except Exception as e:
            self.logger.error(f"Failed to publish result: {e}")
    
    async def _publish_error(self, message_id: str, error: str, traceback_str: str):
        """
        Publish error notification
        
        Args:
            message_id: Message ID that failed
            error: Error message
            traceback_str: Error traceback
        """
        try:
            error_data = {
                'handler': self.handler_name,
                'message_id': message_id,
                'error': error,
                'traceback': traceback_str,
                'timestamp': datetime.now().isoformat()
            }
            
            subject = f"system.errors.{self.handler_name}"
            payload = json.dumps(error_data, default=str).encode('utf-8')
            await self.js.publish(subject, payload)
            
        except Exception as e:
            self.logger.error(f"Failed to publish error notification: {e}")
    
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
        
        self.logger = logging.getLogger("worker.pool")
    
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