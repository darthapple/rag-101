"""
Completion Handler

Consumes embeddings from documents.complete topic and persists them to Milvus
using batch processing strategy for optimal performance.
"""

import asyncio
import logging
import sys
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import json
import uuid
import time

from handlers.base import BaseHandler, MessageProcessingError
sys.path.append('/Users/fadriano/Projetos/Demos/rag-101')
from shared.database import MilvusDatabase, MilvusConnectionError, MilvusOperationError
from shared.models import DocumentChunk


class CompletionStorageError(Exception):
    """Exception raised during completion storage operations"""
    pass


class CompletionHandler(BaseHandler):
    """
    Handler for completion workflow:
    1. Consume embedding data from documents.complete topic
    2. Collect embeddings into batches for optimal Milvus performance
    3. Batch persist embeddings to Milvus collection
    4. Handle completion notifications and cleanup
    """
    
    def __init__(self, handler_name: str = "completion-handler", max_workers: int = 2, infra_manager=None):
        """
        Initialize completion handler
        
        Args:
            handler_name: Handler identifier
            max_workers: Maximum concurrent workers
            infra_manager: Optional InfrastructureManager instance
        """
        super().__init__(handler_name, max_workers, infra_manager)
        
        # Configuration
        self.batch_size = self.config.batch_size
        self.batch_timeout = getattr(self.config, 'completion_batch_timeout', 10)  # 10 second timeout
        self.max_retries = self.config.max_retries
        
        # Message batch collector for individual embedding messages
        self.message_batch = []  # List of (msg, embedding_data) tuples
        self.batch_lock = asyncio.Lock()  # Protect batch collection
        self.last_batch_time = time.time()
        
        # Initialize Milvus database
        self.milvus_db = MilvusDatabase(
            host=self.config.milvus_host,
            port=self.config.milvus_port,
            alias=f"{self.handler_name}-milvus",
            timeout=self.config.connection_timeout
        )
        
        # Start batch timeout task
        self.batch_timeout_task = None
        
        self.logger.info(f"Completion handler initialized with batch_size={self.batch_size}, timeout={self.batch_timeout}s")
    
    async def _process_single_message(self, msg):
        """
        Override BaseHandler to collect messages into batches instead of immediate processing
        """
        try:
            # Deserialize message data
            data = json.loads(msg.data.decode('utf-8'))
            
            # Extract embedding data
            if 'result' in data and isinstance(data['result'], dict):
                embedding_data = data['result']
            else:
                embedding_data = data
            
            # Add message and embedding data to batch collector
            async with self.batch_lock:
                self.message_batch.append((msg, embedding_data))
                self.last_batch_time = time.time()
                
                self.logger.debug(f"Added message to completion batch, current size: {len(self.message_batch)}")
                
                # Process batch when it reaches batch_size
                if len(self.message_batch) >= self.batch_size:
                    await self._process_batch()
                    
        except Exception as e:
            self.logger.error(f"Error collecting message for completion batch: {e}")
            # ACK the message to prevent redelivery on collection errors
            await msg.ack()
    
    async def _process_batch(self):
        """
        Process collected batch of messages - persist embeddings to Milvus
        """
        if not self.message_batch:
            return
            
        self.logger.info(f"Processing completion batch of {len(self.message_batch)} embeddings")
        
        # Take a copy of the current batch and clear for next collection
        current_batch = self.message_batch.copy()
        self.message_batch.clear()
        self.last_batch_time = time.time()
        
        try:
            # Extract embedding data from messages
            embeddings_data = [embedding_data for _, embedding_data in current_batch]
            
            # Get job_id from first embedding (all embeddings in batch could have different job_ids)
            job_ids = list(set([emb.get('job_id', 'unknown') for emb in embeddings_data]))
            self.logger.info(f"Processing batch with {len(embeddings_data)} embeddings from {len(job_ids)} jobs")
            
            # Connect to Milvus
            await self._ensure_milvus_connection()
            
            # Store embeddings in Milvus
            stored_count = await self._store_embeddings_batch(embeddings_data)
            
            self.logger.info(f"Completion batch processed successfully: {stored_count} embeddings stored")
            
            # ACK all messages in the batch after successful processing
            for msg, _ in current_batch:
                await msg.ack()
                
            self.logger.debug(f"ACKed {len(current_batch)} messages in completion batch")
            
        except Exception as e:
            self.logger.error(f"Completion batch processing failed: {e}")
            
            # On batch failure, NACK all messages to trigger redelivery
            for msg, _ in current_batch:
                try:
                    await msg.nak()
                except Exception as nak_error:
                    self.logger.error(f"Error NAK-ing message: {nak_error}")
            
            # Re-raise exception to be handled by caller
            raise
    
    async def _batch_timeout_worker(self):
        """
        Background worker that processes incomplete batches after timeout
        """
        while self.is_running:
            try:
                await asyncio.sleep(5)  # Check every 5 seconds
                
                async with self.batch_lock:
                    if (self.message_batch and 
                        time.time() - self.last_batch_time >= self.batch_timeout):
                        
                        self.logger.info(
                            f"Processing partial completion batch due to timeout "
                            f"({len(self.message_batch)} messages, {time.time() - self.last_batch_time:.1f}s old)"
                        )
                        await self._process_batch()
                        
            except Exception as e:
                self.logger.error(f"Error in batch timeout worker: {e}")
                await asyncio.sleep(10)  # Back off on error
    
    def get_subscription_subject(self) -> str:
        """Subscribe to completion requests"""
        return "documents.complete"
    
    def get_consumer_config(self) -> Dict[str, Any]:
        """Consumer configuration for completion processing"""
        return {
            'durable_name': 'document-completion-worker',
            'manual_ack': True,
            # No pending_msgs_limit - let NATS handle queuing
            'ack_wait': self.batch_timeout * 3  # Triple timeout for ack wait
        }
    
    def get_result_subject(self, data: Dict[str, Any]) -> Optional[str]:
        """Handle publishing manually"""
        return None  # We don't publish results, just persist to Milvus
    
    async def process_message(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        This method won't be called since we override _process_single_message
        but keep it for interface compliance
        """
        # This should not be called since we override _process_single_message
        raise NotImplementedError("Use _process_single_message for batch processing")
    
    async def start(self) -> bool:
        """Start the completion handler"""
        success = await super().start()
        if success:
            # Start batch timeout worker
            self.batch_timeout_task = asyncio.create_task(self._batch_timeout_worker())
            self.logger.info("Completion handler started with batch timeout worker")
        return success
    
    async def stop(self):
        """Stop the handler and cleanup connections"""
        # Stop batch timeout worker
        if self.batch_timeout_task and not self.batch_timeout_task.done():
            self.batch_timeout_task.cancel()
            try:
                await self.batch_timeout_task
            except asyncio.CancelledError:
                pass
        
        # Process any remaining messages in the batch
        try:
            await self._process_final_batch()
        except Exception as e:
            self.logger.error(f"Error processing final completion batch: {e}")
        
        await super().stop()
        
        # Disconnect from Milvus
        try:
            if self.milvus_db:
                self.milvus_db.disconnect()
                self.logger.info("Disconnected from Milvus")
        except Exception as e:
            self.logger.error(f"Error disconnecting from Milvus: {e}")
    
    async def _ensure_milvus_connection(self):
        """Ensure Milvus connection is established"""
        try:
            if not self.milvus_db._connected:
                success = self.milvus_db.connect()
                if not success:
                    raise CompletionStorageError("Failed to connect to Milvus")
            
            # Ensure collection exists
            if not self.milvus_db.collection_exists():
                from shared.create_collection import ensure_collection_exists
                if not ensure_collection_exists():
                    raise CompletionStorageError("Failed to ensure Milvus collection exists")
            
        except Exception as e:
            raise CompletionStorageError(f"Milvus connection error: {e}")
    
    async def _store_embeddings_batch(
        self, 
        embeddings_data: List[Dict[str, Any]]
    ) -> int:
        """
        Store embeddings batch in Milvus collection
        
        Args:
            embeddings_data: List of embeddings with metadata
            
        Returns:
            int: Number of embeddings successfully stored
            
        Raises:
            CompletionStorageError: If storage fails
        """
        try:
            if not embeddings_data:
                return 0
            
            self.logger.debug(f"Storing {len(embeddings_data)} embeddings in Milvus")
            
            # Prepare data for Milvus insertion
            milvus_data = []
            
            for embedding_data in embeddings_data:
                # Convert to Milvus format
                # Handle processed_at conversion (in case it's an integer timestamp)
                processed_at = embedding_data.get('processed_at')
                if isinstance(processed_at, (int, float)):
                    processed_at = datetime.fromtimestamp(processed_at).isoformat()
                elif not processed_at:
                    processed_at = datetime.now().isoformat()
                
                milvus_record = {
                    'chunk_id': embedding_data.get('chunk_id', str(uuid.uuid4())),
                    'embedding': embedding_data.get('embedding'),
                    'text_content': embedding_data.get('text_content', ''),
                    'document_title': embedding_data.get('document_title', ''),
                    'source_url': embedding_data.get('source_url', ''),
                    'page_number': embedding_data.get('page_number', 1),
                    'diseases': json.dumps(embedding_data.get('diseases', [])),
                    'processed_at': processed_at,
                    'job_id': embedding_data.get('job_id', 'unknown')
                }
                
                milvus_data.append(milvus_record)
            
            # Debug: Log the first record to check processed_at format
            if milvus_data:
                self.logger.debug(f"Sample Milvus record processed_at type: {type(milvus_data[0].get('processed_at'))}, value: {milvus_data[0].get('processed_at')}")
            
            # Insert into Milvus with retry logic
            last_error = None
            for attempt in range(self.max_retries):
                try:
                    inserted_ids = self.milvus_db.batch_insert(milvus_data)
                    
                    if not inserted_ids:
                        raise CompletionStorageError("No embeddings were inserted")
                    
                    self.logger.debug(f"Successfully stored {len(inserted_ids)} embeddings")
                    return len(inserted_ids)
                    
                except (MilvusConnectionError, MilvusOperationError) as e:
                    last_error = e
                    self.logger.warning(f"Milvus insertion attempt {attempt + 1} failed: {e}")
                    
                    if attempt < self.max_retries - 1:
                        # Try to reconnect
                        try:
                            self.milvus_db.disconnect()
                            await asyncio.sleep(1.0)
                            await self._ensure_milvus_connection()
                        except Exception as reconnect_error:
                            self.logger.error(f"Reconnection failed: {reconnect_error}")
                    else:
                        raise CompletionStorageError(f"Failed after {self.max_retries} attempts: {last_error}")
            
            return 0
            
        except Exception as e:
            raise CompletionStorageError(f"Batch storage failed: {e}")
    
    async def _process_final_batch(self):
        """
        Process any remaining messages in batch when handler stops
        """
        async with self.batch_lock:
            if self.message_batch:
                self.logger.info(f"Processing final completion batch of {len(self.message_batch)} messages")
                await self._process_batch()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get handler statistics with completion-specific metrics"""
        base_stats = super().get_stats()
        
        # Add completion-specific stats
        base_stats.update({
            'batch_size': self.batch_size,
            'batch_timeout': self.batch_timeout,
            'current_batch_size': len(self.message_batch),
            'batch_age_seconds': time.time() - self.last_batch_time if self.message_batch else 0,
            'milvus_connected': self.milvus_db._connected if self.milvus_db else False
        })
        
        return base_stats