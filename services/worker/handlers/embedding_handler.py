"""
Embedding Handler

Processes document chunks from the document handler, generates vector embeddings
using Google Gemini API, and stores them in Milvus for similarity search.
"""

import asyncio
import logging
import sys
from typing import Dict, Any, Optional
from datetime import datetime
# Removed json import - no longer needed
import uuid
import time

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from google.generativeai.types import GenerationConfig
import google.generativeai as genai

from handlers.base import BaseHandler, MessageProcessingError
sys.path.append('/Users/fadriano/Projetos/Demos/rag-101')
# Removed Milvus imports - completion handler now handles persistence
from shared.models import DocumentChunk


class EmbeddingGenerationError(Exception):
    """Exception raised during embedding generation"""
    pass


# Removed EmbeddingStorageError - no longer needed


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
        
        # Removed batch collection and Milvus database - completion handler now handles this
        
        self.logger.info(f"Embedding handler initialized with model {self.embedding_model}")
    
    # Removed batch collection override - now use standard single message processing
    
    # Removed batch processing method - now handled by completion handler
    
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
                model=self.embedding_model,
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
            # No pending_msgs_limit - let NATS handle queuing
            'ack_wait': self.embedding_timeout * 2  # Double timeout for ack wait
        }
    
    def get_result_subject(self, data: Dict[str, Any] = None) -> Optional[str]:
        """Publish embeddings to completion queue"""
        return "documents.complete"
    
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
            
            # Process single chunk only (no more bulk processing in embedding handler)
            if not chunk_data.get('text_content'):
                raise MessageProcessingError("No text content in chunk data for embedding generation")
            
            self.logger.info(f"Processing single chunk for embedding (job_id: {job_id})")
            
            # Start timing for performance metrics
            processing_start_time = datetime.now()
            
            # Generate embedding for single chunk
            embedding_result = await self._generate_single_embedding(chunk_data, job_id)
            
            # Log completion with performance metrics  
            processing_time = (datetime.now() - processing_start_time).total_seconds()
            
            self.logger.info(
                f"Completed embedding generation for job {job_id} in {processing_time:.2f}s"
            )
            
            return embedding_result
            
        except EmbeddingGenerationError as e:
            error_msg = f"Embedding generation failed: {str(e)}"
            self.logger.error(error_msg)
            raise MessageProcessingError(error_msg)
            
        # EmbeddingStorageError removed - completion handler now handles storage
            
        except Exception as e:
            error_msg = f"Unexpected error in embedding processing: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise MessageProcessingError(error_msg)
    
    # Removed Milvus connection method - completion handler now handles this
    
    async def _generate_single_embedding(
        self, 
        chunk_data: Dict[str, Any], 
        job_id: str
    ) -> Dict[str, Any]:
        """
        Generate embedding for a single chunk
        
        Args:
            chunk_data: Single chunk data dictionary
            job_id: Job identifier for tracking
            
        Returns:
            Dict[str, Any]: Chunk with embedding added
            
        Raises:
            EmbeddingGenerationError: If generation fails
        """
        try:
            # Extract text content for embedding
            text_content = chunk_data.get('text_content', '')
            
            if not text_content.strip():
                raise EmbeddingGenerationError("No valid text content for embedding generation")
            
            self.logger.debug(f"Generating embedding for chunk {chunk_data.get('chunk_id', 'unknown')}")
            
            # Generate embedding using Gemini API with retry logic
            embedding = None
            last_error = None
            
            for attempt in range(self.max_retries):
                try:
                    # Use asyncio to run the sync embedding method
                    embeddings = await asyncio.get_event_loop().run_in_executor(
                        None,
                        self.embeddings_client.embed_documents,
                        [text_content]
                    )
                    
                    if embeddings and len(embeddings) > 0:
                        embedding = embeddings[0]
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
            
            if not embedding:
                raise EmbeddingGenerationError("No embedding generated")
            
            # Validate embedding dimensions
            if len(embedding) != self.vector_dimension:
                raise EmbeddingGenerationError(
                    f"Invalid embedding dimension: {len(embedding)} != {self.vector_dimension}"
                )
            
            # Add embedding to chunk data
            result_chunk = chunk_data.copy()
            result_chunk['embedding'] = embedding
            result_chunk['embedding_generated_at'] = datetime.now().isoformat()
            
            self.logger.debug(f"Successfully generated embedding for chunk {result_chunk.get('chunk_id')}")
            return result_chunk
            
        except Exception as e:
            raise EmbeddingGenerationError(f"Single embedding generation failed: {e}")
    
    # Removed storage method - completion handler now handles Milvus persistence
    
    # Removed batch processing methods - standard cleanup now suffices
    
    async def stop(self):
        """Stop the handler and cleanup connections"""
        await super().stop()
        self.logger.info("Embedding handler stopped")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get handler statistics with embedding-specific metrics"""
        base_stats = super().get_stats()
        
        # Add embedding-specific stats
        base_stats.update({
            'embedding_model': self.embedding_model,
            'vector_dimension': self.vector_dimension
        })
        
        return base_stats