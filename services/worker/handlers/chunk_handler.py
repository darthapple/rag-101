"""
Chunk Handler

Processes document text extraction results and creates chunks for embedding.
Consumes from documents.chunk topic and publishes to embeddings.create topic.
"""

import asyncio
import logging
import re
from datetime import datetime
from typing import Dict, Any, List, Optional
import uuid

from langchain.text_splitter import RecursiveCharacterTextSplitter

from handlers.base import BaseHandler, MessageProcessingError
import sys
sys.path.append('/Users/fadriano/Projetos/Demos/rag-101')
from shared.models import DocumentChunk
from shared.logging import get_structured_logger


class ChunkProcessingError(Exception):
    """Exception raised during chunk processing"""
    pass


class ChunkHandler(BaseHandler):
    """
    Handler for document chunking workflow:
    1. Consume document text from documents.chunk topic
    2. Split text into chunks using RecursiveCharacterTextSplitter
    3. Extract metadata including diseases from chunks
    4. Publish chunks to embeddings.create topic
    """
    
    def __init__(self, handler_name: str = "chunk-handler", max_workers: int = 2, infra_manager=None):
        """
        Initialize chunk handler
        
        Args:
            handler_name: Handler identifier
            max_workers: Maximum concurrent workers
        """
        super().__init__(handler_name, max_workers, infra_manager)
        
        # Chunk processing configuration
        self.chunk_size = self.config.chunk_size
        self.chunk_overlap = self.config.chunk_overlap
        
        # Text splitter configuration
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
            separators=[
                "\n\n",  # Paragraph breaks
                "\n",    # Line breaks
                ". ",    # Sentence breaks
                "? ",    # Question breaks
                "! ",    # Exclamation breaks
                "; ",    # Semicolon breaks
                ", ",    # Comma breaks
                " ",     # Word breaks
                ""       # Character breaks
            ],
            keep_separator=True
        )
        
        # Medical terms for disease extraction (basic patterns)
        self.disease_patterns = [
            r'\b(?:diabetes|hipertensão|câncer|cancer|tumor|doença|síndrome|distúrbio)\b',
            r'\b(?:covid|tuberculose|hepatite|pneumonia|bronquite|asma)\b',
            r'\b(?:depressão|ansiedade|esquizofrenia|bipolar|alzheimer|parkinson)\b',
            r'\b(?:artrite|artrose|fibromialgia|lupus|artritis)\b',
            r'\b(?:cardiovascular|cardíaco|coronário|infarto|avc|derrame)\b'
        ]
        
        self.disease_regex = re.compile('|'.join(self.disease_patterns), re.IGNORECASE)
        
        self.logger.info(
            "Chunk handler initialized",
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            handler_name=handler_name,
            max_workers=max_workers
        )
    
    def get_subscription_subject(self) -> str:
        """Subscribe to document chunking requests"""
        return "documents.chunks"
    
    def get_consumer_config(self) -> Dict[str, Any]:
        """Consumer configuration for chunk processing"""
        return {
            'durable_name': 'document-chunk-worker',
            'manual_ack': True,
            'pending_msgs_limit': self.max_workers * 2,
            'ack_wait': 120  # 2 minutes for chunk processing
        }
    
    def get_result_subject(self, data: Dict[str, Any]) -> Optional[str]:
        """Handle publishing manually with delays - don't use base handler auto-publish"""
        return None
    
    async def process_message(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process document chunking request
        
        Args:
            data: Message data containing extracted document text and metadata
            
        Returns:
            Dict[str, Any]: Processing result with chunks for embedding
            
        Raises:
            MessageProcessingError: If processing fails
        """
        processing_start_time = datetime.now()
        try:
            # Extract the actual document data from the wrapped message
            # Messages from other handlers are wrapped with metadata
            if 'result' in data and isinstance(data['result'], dict):
                document_data = data['result']
            else:
                document_data = data
            
            # Extract request data
            job_id = document_data.get('job_id')
            url = document_data.get('url')
            pages = document_data.get('pages', [])
            document_title = document_data.get('document_title', '')
            file_info = document_data.get('file_info', {})
            metadata = document_data.get('metadata', {})
            
            if not job_id:
                raise MessageProcessingError("Missing 'job_id' in message data")
            
            if not pages:
                raise MessageProcessingError("Missing 'pages' in message data")
            
            self.logger.info(
                "Starting document chunking",
                url=url,
                job_id=job_id,
                page_count=len(pages),
                document_title=document_title,
                handler_name=self.handler_name
            )
            
            # Process all pages and create chunks
            all_chunks = []
            
            for page_data in pages:
                page_number = page_data.get('page_number', 1)
                text_content = page_data.get('text_content', '')
                page_metadata = page_data.get('metadata', {})
                
                if text_content.strip():
                    # Split page text into chunks
                    page_chunks = await self.chunk_page_text(
                        text_content, 
                        page_number, 
                        job_id, 
                        url,
                        document_title,
                        file_info,
                        metadata,
                        page_metadata
                    )
                    all_chunks.extend(page_chunks)
            
            if not all_chunks:
                raise ChunkProcessingError("No chunks generated from document pages")
            
            self.logger.log_operation(
                "chunk_processing",
                (datetime.now() - processing_start_time).total_seconds(),
                success=True,
                url=url,
                job_id=job_id,
                chunk_count=len(all_chunks),
                page_count=len(pages)
            )
            
            # Publish each chunk with a shorter 500ms delay for demo purposes
            published_count = 0
            for chunk in all_chunks:
                try:
                    # Apply shorter delay for chunk processing (500ms instead of 10s)
                    await asyncio.sleep(0.5)  # 500ms delay for chunks
                    
                    # Publish chunk message directly
                    message_id = f"{job_id}_{chunk['chunk_id']}"
                    chunk_message = {
                        'handler': self.handler_name,
                        'message_id': message_id,
                        'processed_at': datetime.now().isoformat(),
                        'result': chunk
                    }
                    
                    import json
                    payload = json.dumps(chunk_message, default=str).encode('utf-8')
                    await self.js.publish('documents.embeddings', payload)
                    published_count += 1
                    
                except Exception as e:
                    self.logger.error(f"Failed to publish chunk {chunk['chunk_id']}: {e}")
            
            self.logger.info(f"Published {published_count}/{len(all_chunks)} chunks to embedding topic with delays")
            
            return {
                'job_id': job_id,
                'url': url,
                'status': 'chunked',
                'chunk_count': len(all_chunks),
                'published_count': published_count,
                'document_title': document_title,
                'processing_time': datetime.now().isoformat()
            }
                
        except ChunkProcessingError as e:
            processing_time = (datetime.now() - processing_start_time).total_seconds()
            self.logger.log_operation(
                "chunk_processing",
                processing_time,
                success=False,
                url=url,
                job_id=job_id,
                error_type="chunk_error",
                error=e
            )
            raise MessageProcessingError(f"Chunking failed for {job_id}: {str(e)}")
            
        except Exception as e:
            processing_time = (datetime.now() - processing_start_time).total_seconds()
            self.logger.log_exception(
                f"Unexpected error chunking document {job_id}",
                exception=e,
                url=url,
                job_id=job_id,
                processing_time=processing_time,
                handler_name=self.handler_name
            )
            raise MessageProcessingError(f"Unexpected error chunking {job_id}: {str(e)}")
    
    async def chunk_page_text(
        self, 
        text_content: str, 
        page_number: int,
        job_id: str,
        url: str,
        document_title: str,
        file_info: Dict[str, Any],
        metadata: Dict[str, Any],
        page_metadata: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Chunk text content from a single page
        
        Args:
            text_content: Text to chunk
            page_number: Page number
            job_id: Job identifier
            url: Source URL
            document_title: Document title
            file_info: File information
            metadata: Additional metadata
            page_metadata: Page-specific metadata
            
        Returns:
            List[Dict[str, Any]]: Processed chunks with metadata
        """
        try:
            # Split text into chunks
            chunks = await asyncio.get_event_loop().run_in_executor(
                None, self.text_splitter.split_text, text_content
            )
            
            if not chunks:
                return []
            
            processed_chunks = []
            
            for i, chunk_text in enumerate(chunks):
                if not chunk_text.strip():
                    continue
                
                # Generate unique chunk ID
                chunk_id = f"{job_id}_{page_number}_{i}"
                
                # Extract diseases from chunk content
                diseases = self.extract_diseases(chunk_text)
                
                # Create chunk data
                chunk_data = {
                    'chunk_id': chunk_id,
                    'text_content': chunk_text.strip(),
                    'document_title': document_title,
                    'source_url': url,
                    'page_number': page_number,
                    'diseases': diseases,
                    'processed_at': datetime.now().isoformat(),
                    'job_id': job_id,
                    'metadata': {
                        'chunk_index': i,
                        'total_chunks_in_page': len(chunks),
                        'chunk_size': len(chunk_text),
                        'file_size': file_info.get('file_size', 0),
                        'total_pages': file_info.get('total_pages', 1),
                        **page_metadata
                    }
                }
                
                processed_chunks.append(chunk_data)
            
            self.logger.debug(f"Generated {len(processed_chunks)} chunks from page {page_number}")
            return processed_chunks
            
        except Exception as e:
            raise ChunkProcessingError(f"Page chunking failed for page {page_number}: {str(e)}")
    
    def extract_diseases(self, text: str) -> List[str]:
        """
        Extract medical conditions/diseases from text content
        
        Args:
            text: Text content to analyze
            
        Returns:
            List[str]: List of found diseases/conditions
        """
        try:
            diseases = set()
            
            # Find matches using regex patterns
            matches = self.disease_regex.findall(text.lower())
            diseases.update(matches)
            
            # Additional pattern-based extraction
            # Look for "doença de X" or "síndrome de X" patterns
            syndrome_pattern = re.compile(
                r'\b(?:doença|síndrome|distúrbio)\s+(?:de|do|da)\s+([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*)',
                re.IGNORECASE
            )
            
            syndrome_matches = syndrome_pattern.findall(text)
            for match in syndrome_matches:
                diseases.add(f"síndrome de {match.strip()}")
            
            # Convert to sorted list and limit results
            disease_list = sorted(list(diseases))[:10]  # Limit to 10 diseases
            
            return disease_list
            
        except Exception as e:
            self.logger.warning(f"Disease extraction failed: {e}")
            return []