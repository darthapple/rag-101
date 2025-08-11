"""
Embedding Handler

Processes document chunks from the document handler, generates vector embeddings
using Google Gemini API, and stores them in Milvus for similarity search.
"""

import asyncio
import logging
import sys
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import json
import uuid
import time

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from google.generativeai.types import GenerationConfig
import google.generativeai as genai

from handlers.base import BaseHandler, MessageProcessingError
sys.path.append('/Users/fadriano/Projetos/Demos/rag-101')
from shared.database import MilvusDatabase, MilvusConnectionError, MilvusOperationError
from shared.models import DocumentChunk


class EmbeddingGenerationError(Exception):
    """Exception raised during embedding generation"""
    pass


class EmbeddingStorageError(Exception):
    """Exception raised during embedding storage"""
    pass


class EmbeddingHandler(BaseHandler):
    """
    Handler for embedding generation workflow:
    1. Consume document chunks from documents.embeddings topic
    2. Generate embeddings using Google Gemini text-embedding-004
    3. Validate 768-dimensional vectors
    4. Store in Milvus collection with batch insertion
    5. Publish completion notifications
    """
    
    def __init__(self, handler_name: str = "embedding-handler", max_workers: int = 2, infra_manager=None):
        """
        Initialize embedding handler
        
        Args:
            handler_name: Handler identifier
            max_workers: Maximum concurrent workers
            infra_manager: Optional InfrastructureManager instance
        """
        super().__init__(handler_name, max_workers, infra_manager)
        
        # Configuration
        self.batch_size = self.config.batch_size
        self.embedding_timeout = self.config.embedding_timeout
        self.max_retries = self.config.max_retries
        
        # Embedding configuration
        self.embedding_model = self.config.embedding_model
        self.vector_dimension = self.config.vector_dimension
        
        # Initialize Google Gemini embeddings
        self.embeddings_client = None
        self._setup_gemini_client()
        
        # Initialize Milvus database
        self.milvus_db = MilvusDatabase(
            host=self.config.milvus_host,
            port=self.config.milvus_port,
            alias=f"{self.handler_name}-milvus",
            timeout=self.config.connection_timeout
        )
        
        self.logger.info(f"Embedding handler initialized with model {self.embedding_model}")
    
    def _setup_gemini_client(self):
        """Setup Google Gemini API client"""
        try:
            if not self.config.gemini_api_key:
                raise EmbeddingGenerationError("GEMINI_API_KEY not configured")
            
            # Configure Gemini API
            genai.configure(api_key=self.config.gemini_api_key)
            
            # Initialize embeddings client
            # Use the full model name for the newer API version
            self.embeddings_client = GoogleGenerativeAIEmbeddings(
                model=f"models/{self.embedding_model}",
                google_api_key=self.config.gemini_api_key
            )
            
            self.logger.info(f"Gemini embeddings client initialized with {self.embedding_model}")
            
        except Exception as e:
            self.logger.error(f"Failed to setup Gemini client: {e}")
            raise EmbeddingGenerationError(f"Gemini client setup failed: {e}")
    
    def get_subscription_subject(self) -> str:
        """Subscribe to embedding generation requests"""
        return "documents.embeddings"
    
    def get_consumer_config(self) -> Dict[str, Any]:
        """Consumer configuration for embedding processing"""
        return {
            'durable_name': 'document-embedding-worker',
            'manual_ack': True,
            'pending_msgs_limit': self.max_workers * 5,  # Higher limit for batch processing
            'ack_wait': self.embedding_timeout * 2  # Double timeout for ack wait
        }
    
    def get_result_subject(self, data: Dict[str, Any]) -> Optional[str]:
        """Publish completion notifications"""
        return "embeddings.complete"
    
    async def process_message(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process embedding generation request
        
        Args:
            data: Message data containing document chunks
            
        Returns:
            Dict[str, Any]: Processing result with embedding statistics
            
        Raises:
            MessageProcessingError: If processing fails
        """
        try:
            # Extract the actual document data from the wrapped message
            # Messages from other handlers are wrapped with metadata
            if 'result' in data and isinstance(data['result'], dict):
                chunk_data = data['result']
            else:
                chunk_data = data
            
            # Extract request data - now processing single chunk
            job_id = chunk_data.get('job_id', str(uuid.uuid4()))
            url = chunk_data.get('url', 'unknown')
            
            # Check if this is a single chunk (new format) or batch (old format)
            if 'chunks' in chunk_data:
                # Old batch format - process all chunks
                chunks_data = chunk_data.get('chunks', [])
            else:
                # New single chunk format - process one chunk
                chunks_data = [chunk_data]
            
            if not chunks_data:
                raise MessageProcessingError("No chunks provided for embedding generation")
            
            self.logger.info(f"Processing {len(chunks_data)} chunks for embeddings (job_id: {job_id})")
            
            # Connect to Milvus
            await self._ensure_milvus_connection()
            
            # Process chunks in batches
            total_embeddings = 0
            total_errors = 0
            batch_results = []
            
            for i in range(0, len(chunks_data), self.batch_size):
                batch_chunks = chunks_data[i:i + self.batch_size]
                batch_num = (i // self.batch_size) + 1
                total_batches = (len(chunks_data) + self.batch_size - 1) // self.batch_size
                
                self.logger.debug(f"Processing batch {batch_num}/{total_batches} ({len(batch_chunks)} chunks)")
                
                try:
                    # Generate embeddings for batch
                    embeddings = await self._generate_embeddings_batch(batch_chunks, job_id)
                    
                    # Store embeddings in Milvus
                    stored_count = await self._store_embeddings_batch(embeddings, job_id)
                    
                    batch_results.append({
                        'batch_num': batch_num,
                        'chunks_processed': len(batch_chunks),
                        'embeddings_generated': len(embeddings),
                        'embeddings_stored': stored_count,
                        'success': True
                    })
                    
                    total_embeddings += stored_count
                    
                except Exception as e:
                    self.logger.error(f"Batch {batch_num} failed: {e}")
                    batch_results.append({
                        'batch_num': batch_num,
                        'chunks_processed': len(batch_chunks),
                        'embeddings_generated': 0,
                        'embeddings_stored': 0,
                        'success': False,
                        'error': str(e)
                    })
                    total_errors += len(batch_chunks)
                
                # Small delay between batches to respect rate limits
                if i + self.batch_size < len(chunks_data):
                    await asyncio.sleep(0.1)
            
            success_rate = (total_embeddings / len(chunks_data)) if chunks_data else 0
            
            self.logger.info(
                f"Completed embedding generation for job {job_id}: "
                f"{total_embeddings}/{len(chunks_data)} embeddings stored "
                f"({success_rate:.1%} success rate)"
            )
            
            return {
                'job_id': job_id,
                'url': url,
                'status': 'completed' if total_errors == 0 else 'partial',
                'chunks_total': len(chunks_data),
                'embeddings_generated': total_embeddings,
                'errors': total_errors,
                'success_rate': success_rate,
                'batch_results': batch_results,
                'processed_at': datetime.now().isoformat()
            }
            
        except EmbeddingGenerationError as e:
            error_msg = f"Embedding generation failed: {str(e)}"
            self.logger.error(error_msg)
            raise MessageProcessingError(error_msg)
            
        except EmbeddingStorageError as e:
            error_msg = f"Embedding storage failed: {str(e)}"
            self.logger.error(error_msg)
            raise MessageProcessingError(error_msg)
            
        except Exception as e:
            error_msg = f"Unexpected error in embedding processing: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise MessageProcessingError(error_msg)
    
    async def _ensure_milvus_connection(self):
        """Ensure Milvus connection is established"""
        try:
            if not self.milvus_db._connected:
                success = self.milvus_db.connect()
                if not success:
                    raise EmbeddingStorageError("Failed to connect to Milvus")
            
            # Ensure collection exists
            if not self.milvus_db.collection_exists():
                from shared.create_collection import ensure_collection_exists
                if not ensure_collection_exists():
                    raise EmbeddingStorageError("Failed to ensure Milvus collection exists")
            
        except Exception as e:
            raise EmbeddingStorageError(f"Milvus connection error: {e}")
    
    async def _generate_embeddings_batch(
        self, 
        batch_chunks: List[Dict[str, Any]], 
        job_id: str
    ) -> List[Dict[str, Any]]:
        """
        Generate embeddings for a batch of chunks
        
        Args:
            batch_chunks: List of chunk data dictionaries
            job_id: Job identifier for tracking
            
        Returns:
            List[Dict[str, Any]]: Chunks with embeddings added
            
        Raises:
            EmbeddingGenerationError: If generation fails
        """
        try:
            # Extract text content for embedding
            texts = [chunk.get('text_content', '') for chunk in batch_chunks]
            
            # Filter out empty texts
            valid_indices = [i for i, text in enumerate(texts) if text.strip()]
            valid_texts = [texts[i] for i in valid_indices]
            
            if not valid_texts:
                raise EmbeddingGenerationError("No valid text content for embedding generation")
            
            self.logger.debug(f"Generating embeddings for {len(valid_texts)} text chunks")
            
            # Generate embeddings using Gemini API with retry logic
            embeddings = None
            last_error = None
            
            for attempt in range(self.max_retries):
                try:
                    # Use asyncio to run the sync embedding method
                    embeddings = await asyncio.get_event_loop().run_in_executor(
                        None,
                        self.embeddings_client.embed_documents,
                        valid_texts
                    )
                    break
                    
                except Exception as e:
                    last_error = e
                    self.logger.warning(f"Embedding attempt {attempt + 1} failed: {e}")
                    
                    if attempt < self.max_retries - 1:
                        # Exponential backoff
                        wait_time = (2 ** attempt) * 1.0
                        await asyncio.sleep(wait_time)
                    else:
                        raise EmbeddingGenerationError(f"Failed after {self.max_retries} attempts: {last_error}")
            
            if not embeddings:
                raise EmbeddingGenerationError("No embeddings generated")
            
            # Validate embeddings
            if len(embeddings) != len(valid_texts):
                raise EmbeddingGenerationError(
                    f"Embedding count mismatch: {len(embeddings)} != {len(valid_texts)}"
                )
            
            # Validate embedding dimensions
            for i, embedding in enumerate(embeddings):
                if len(embedding) != self.vector_dimension:
                    raise EmbeddingGenerationError(
                        f"Invalid embedding dimension at index {i}: {len(embedding)} != {self.vector_dimension}"
                    )
            
            # Combine chunks with embeddings
            result_chunks = []
            embedding_index = 0
            
            for i, chunk in enumerate(batch_chunks):
                if i in valid_indices:
                    # Add embedding to chunk
                    chunk_with_embedding = chunk.copy()
                    chunk_with_embedding['embedding'] = embeddings[embedding_index]
                    result_chunks.append(chunk_with_embedding)
                    embedding_index += 1
                else:
                    # Skip chunks without valid text
                    self.logger.warning(f"Skipping chunk {i} due to empty text content")
            
            self.logger.debug(f"Successfully generated {len(result_chunks)} embeddings")
            return result_chunks
            
        except Exception as e:
            raise EmbeddingGenerationError(f"Batch embedding generation failed: {e}")
    
    async def _store_embeddings_batch(
        self, 
        embeddings_data: List[Dict[str, Any]], 
        job_id: str
    ) -> int:
        """
        Store embeddings batch in Milvus collection
        
        Args:
            embeddings_data: List of chunks with embeddings
            job_id: Job identifier
            
        Returns:
            int: Number of embeddings successfully stored
            
        Raises:
            EmbeddingStorageError: If storage fails
        """
        try:
            if not embeddings_data:
                return 0
            
            self.logger.debug(f"Storing {len(embeddings_data)} embeddings in Milvus")
            
            # Prepare data for Milvus insertion
            milvus_data = []
            
            for chunk_data in embeddings_data:
                # Convert to Milvus format
                milvus_record = {
                    'chunk_id': chunk_data.get('chunk_id', str(uuid.uuid4())),
                    'embedding': chunk_data.get('embedding'),
                    'text_content': chunk_data.get('text_content', ''),
                    'document_title': chunk_data.get('document_title', ''),
                    'source_url': chunk_data.get('source_url', ''),
                    'page_number': chunk_data.get('page_number', 1),
                    'diseases': json.dumps(chunk_data.get('diseases', [])),
                    'processed_at': chunk_data.get('processed_at', int(datetime.now().timestamp())),
                    'job_id': chunk_data.get('job_id', job_id)
                }
                
                milvus_data.append(milvus_record)
            
            # Insert into Milvus with retry logic
            last_error = None
            for attempt in range(self.max_retries):
                try:
                    inserted_ids = self.milvus_db.batch_insert(milvus_data)
                    
                    if not inserted_ids:
                        raise EmbeddingStorageError("No embeddings were inserted")
                    
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
                        raise EmbeddingStorageError(f"Failed after {self.max_retries} attempts: {last_error}")
            
            return 0
            
        except Exception as e:
            raise EmbeddingStorageError(f"Batch storage failed: {e}")
    
    async def stop(self):
        """Stop the handler and cleanup connections"""
        await super().stop()
        
        # Disconnect from Milvus
        try:
            if self.milvus_db:
                self.milvus_db.disconnect()
                self.logger.info("Disconnected from Milvus")
        except Exception as e:
            self.logger.error(f"Error disconnecting from Milvus: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get handler statistics with embedding-specific metrics"""
        base_stats = super().get_stats()
        
        # Add embedding-specific stats
        base_stats.update({
            'embedding_model': self.embedding_model,
            'vector_dimension': self.vector_dimension,
            'batch_size': self.batch_size,
            'milvus_connected': self.milvus_db._connected if self.milvus_db else False
        })
        
        return base_stats