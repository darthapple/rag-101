"""
Document Handler

Processes document download requests, extracts text from PDFs, chunks content,
and publishes to embeddings topic for vector generation.
"""

import asyncio
import logging
import tempfile
import os
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from urllib.parse import urlparse
import uuid
import json

import aiohttp
import aiofiles
from langchain.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document as LangChainDocument

from handlers.base import BaseHandler, MessageProcessingError
import sys
sys.path.append('/Users/fadriano/Projetos/Demos/rag-101')
from shared.models import Document, DocumentChunk, DocumentStatus
from shared.logging import get_structured_logger


class DocumentDownloadError(Exception):
    """Exception raised during document download"""
    pass


class DocumentProcessingError(Exception):
    """Exception raised during document processing"""
    pass


class DocumentHandler(BaseHandler):
    """
    Handler for document processing workflow:
    1. Download PDF from URL
    2. Extract text using PyPDFLoader
    3. Chunk text using RecursiveCharacterTextSplitter
    4. Extract metadata (title, diseases, page numbers)
    5. Publish chunks to embeddings.create topic
    """
    
    def __init__(self, handler_name: str = "document-handler", max_workers: int = 2):
        """
        Initialize document handler
        
        Args:
            handler_name: Handler identifier
            max_workers: Maximum concurrent workers
        """
        super().__init__(handler_name, max_workers)
        
        # Document processing configuration
        self.chunk_size = self.config.chunk_size
        self.chunk_overlap = self.config.chunk_overlap
        self.max_file_size = self.config.max_file_size
        self.download_timeout = self.config.document_processing_timeout
        
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
            "Document handler initialized",
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            max_file_size=self.max_file_size,
            download_timeout=self.download_timeout,
            handler_name=handler_name,
            max_workers=max_workers
        )
    
    def get_subscription_subject(self) -> str:
        """Subscribe to document download requests"""
        return "documents.download"
    
    def get_consumer_config(self) -> Dict[str, Any]:
        """Consumer configuration for document processing"""
        return {
            'durable_name': 'document-processor',
            'manual_ack': True,
            'pending_msgs_limit': self.max_workers * 2,
            'ack_wait': self.download_timeout * 2  # Double timeout for ack wait
        }
    
    def get_result_subject(self, data: Dict[str, Any]) -> Optional[str]:
        """Publish results to embeddings topic"""
        return "embeddings.create"
    
    async def process_message(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process document download and chunking request
        
        Args:
            data: Message data containing URL and job information
            
        Returns:
            Dict[str, Any]: Processing result with chunks for embedding
            
        Raises:
            MessageProcessingError: If processing fails
        """
        processing_start_time = datetime.now()
        try:
            # Extract request data
            url = data.get('url')
            job_id = data.get('job_id', str(uuid.uuid4()))
            metadata = data.get('metadata', {})
            
            if not url:
                raise MessageProcessingError("Missing 'url' in message data")
            
            self.logger.info(
                "Starting document processing",
                url=url,
                job_id=job_id,
                metadata_keys=list(metadata.keys()) if metadata else [],
                handler_name=self.handler_name
            )
            
            # Download PDF
            file_path, file_info = await self.download_pdf(url, job_id)
            
            try:
                # Process PDF and extract text
                documents = await self.process_pdf(file_path, url, job_id, file_info)
                
                # Chunk documents
                chunks = await self.chunk_documents(documents, url, job_id)
                
                # Extract metadata from chunks
                processed_chunks = await self.process_chunks(chunks, url, job_id, metadata)
                
                self.logger.log_operation(
                    "document_processing",
                    (datetime.now() - processing_start_time).total_seconds(),
                    success=True,
                    url=url,
                    job_id=job_id,
                    chunk_count=len(processed_chunks),
                    file_size=file_info.get('file_size', 0)
                )
                
                return {
                    'job_id': job_id,
                    'url': url,
                    'status': 'completed',
                    'chunk_count': len(processed_chunks),
                    'chunks': processed_chunks,
                    'file_info': file_info,
                    'processing_time': (datetime.now().isoformat())
                }
                
            finally:
                # Clean up temporary file
                await self.cleanup_file(file_path)
                
        except DocumentDownloadError as e:
            processing_time = (datetime.now() - processing_start_time).total_seconds()
            self.logger.log_operation(
                "document_processing",
                processing_time,
                success=False,
                url=url,
                job_id=job_id,
                error_type="download_error",
                error=e
            )
            raise MessageProcessingError(f"Download failed for {url}: {str(e)}")
            
        except DocumentProcessingError as e:
            processing_time = (datetime.now() - processing_start_time).total_seconds()
            self.logger.log_operation(
                "document_processing",
                processing_time,
                success=False,
                url=url,
                job_id=job_id,
                error_type="processing_error",
                error=e
            )
            raise MessageProcessingError(f"Processing failed for {url}: {str(e)}")
            
        except Exception as e:
            processing_time = (datetime.now() - processing_start_time).total_seconds()
            self.logger.log_exception(
                f"Unexpected error processing document {url}",
                exception=e,
                url=url,
                job_id=job_id,
                processing_time=processing_time,
                handler_name=self.handler_name
            )
            raise MessageProcessingError(f"Unexpected error processing {url}: {str(e)}")
    
    async def download_pdf(self, url: str, job_id: str) -> Tuple[str, Dict[str, Any]]:
        """
        Download PDF from URL with validation and error handling
        
        Args:
            url: PDF URL to download
            job_id: Job identifier for tracking
            
        Returns:
            Tuple[str, Dict[str, Any]]: (file_path, file_info)
            
        Raises:
            DocumentDownloadError: If download fails
        """
        try:
            # Validate URL
            parsed_url = urlparse(url)
            if not parsed_url.scheme or not parsed_url.netloc:
                raise DocumentDownloadError(f"Invalid URL format: {url}")
            
            # Create temporary file
            temp_dir = tempfile.gettempdir()
            temp_file = tempfile.NamedTemporaryFile(
                delete=False,
                suffix='.pdf',
                prefix=f'doc_{job_id}_',
                dir=temp_dir
            )
            temp_path = temp_file.name
            temp_file.close()
            
            self.logger.debug(f"Downloading {url} to {temp_path}")
            
            # Download with timeout and size limit
            timeout = aiohttp.ClientTimeout(total=self.download_timeout)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    url,
                    headers={
                        'User-Agent': 'RAG-101-Document-Processor/1.0',
                        'Accept': 'application/pdf,*/*'
                    }
                ) as response:
                    
                    # Check response status
                    if response.status != 200:
                        raise DocumentDownloadError(
                            f"HTTP {response.status}: {response.reason}"
                        )
                    
                    # Check content type
                    content_type = response.headers.get('Content-Type', '').lower()
                    if 'pdf' not in content_type and not url.lower().endswith('.pdf'):
                        self.logger.warning(f"Unexpected content type: {content_type}")
                    
                    # Check content length
                    content_length = response.headers.get('Content-Length')
                    if content_length and int(content_length) > self.max_file_size:
                        raise DocumentDownloadError(
                            f"File too large: {content_length} bytes (max: {self.max_file_size})"
                        )
                    
                    # Download file
                    downloaded_size = 0
                    async with aiofiles.open(temp_path, 'wb') as temp_file:
                        async for chunk in response.content.iter_chunked(8192):
                            downloaded_size += len(chunk)
                            
                            # Check size limit during download
                            if downloaded_size > self.max_file_size:
                                raise DocumentDownloadError(
                                    f"File too large: {downloaded_size} bytes (max: {self.max_file_size})"
                                )
                            
                            await temp_file.write(chunk)
                    
                    file_info = {
                        'url': url,
                        'file_size': downloaded_size,
                        'content_type': content_type,
                        'downloaded_at': datetime.now().isoformat(),
                        'temp_path': temp_path
                    }
                    
                    self.logger.debug(f"Downloaded {downloaded_size} bytes from {url}")
                    return temp_path, file_info
                    
        except aiohttp.ClientError as e:
            raise DocumentDownloadError(f"Network error: {str(e)}")
        except asyncio.TimeoutError:
            raise DocumentDownloadError(f"Download timeout after {self.download_timeout}s")
        except Exception as e:
            # Clean up on error
            if 'temp_path' in locals():
                await self.cleanup_file(temp_path)
            raise DocumentDownloadError(f"Download failed: {str(e)}")
    
    async def process_pdf(
        self, 
        file_path: str, 
        url: str, 
        job_id: str, 
        file_info: Dict[str, Any]
    ) -> List[LangChainDocument]:
        """
        Process PDF file using PyPDFLoader
        
        Args:
            file_path: Path to downloaded PDF
            url: Original URL
            job_id: Job identifier
            file_info: File metadata
            
        Returns:
            List[LangChainDocument]: Extracted documents
            
        Raises:
            DocumentProcessingError: If processing fails
        """
        try:
            self.logger.debug(f"Processing PDF: {file_path}")
            
            # Load PDF using PyPDFLoader
            loader = PyPDFLoader(file_path)
            documents = await asyncio.get_event_loop().run_in_executor(
                None, loader.load
            )
            
            if not documents:
                raise DocumentProcessingError("No content extracted from PDF")
            
            # Add metadata to documents
            for i, doc in enumerate(documents):
                doc.metadata.update({
                    'source_url': url,
                    'job_id': job_id,
                    'page_number': i + 1,
                    'total_pages': len(documents),
                    'file_size': file_info.get('file_size', 0),
                    'processed_at': datetime.now().isoformat()
                })
            
            self.logger.info(f"Extracted text from {len(documents)} pages")
            return documents
            
        except Exception as e:
            raise DocumentProcessingError(f"PDF processing failed: {str(e)}")
    
    async def chunk_documents(
        self, 
        documents: List[LangChainDocument], 
        url: str, 
        job_id: str
    ) -> List[LangChainDocument]:
        """
        Chunk documents using RecursiveCharacterTextSplitter
        
        Args:
            documents: LangChain documents to chunk
            url: Source URL
            job_id: Job identifier
            
        Returns:
            List[LangChainDocument]: Chunked documents
        """
        try:
            self.logger.debug(f"Chunking {len(documents)} documents")
            
            # Split documents into chunks
            chunks = await asyncio.get_event_loop().run_in_executor(
                None, self.text_splitter.split_documents, documents
            )
            
            if not chunks:
                raise DocumentProcessingError("No chunks generated from documents")
            
            # Add chunk-specific metadata
            for i, chunk in enumerate(chunks):
                chunk.metadata.update({
                    'chunk_index': i,
                    'total_chunks': len(chunks),
                    'chunk_size': len(chunk.page_content),
                    'chunk_id': f"{job_id}_{chunk.metadata.get('page_number', 0)}_{i}"
                })
            
            self.logger.info(f"Generated {len(chunks)} chunks")
            return chunks
            
        except Exception as e:
            raise DocumentProcessingError(f"Document chunking failed: {str(e)}")
    
    async def process_chunks(
        self, 
        chunks: List[LangChainDocument], 
        url: str, 
        job_id: str,
        metadata: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Process chunks and extract metadata including diseases
        
        Args:
            chunks: Chunked documents
            url: Source URL
            job_id: Job identifier
            metadata: Additional metadata
            
        Returns:
            List[Dict[str, Any]]: Processed chunks with metadata
        """
        try:
            processed_chunks = []
            document_title = await self.extract_document_title(chunks, metadata)
            
            for chunk in chunks:
                # Extract diseases from chunk content
                diseases = self.extract_diseases(chunk.page_content)
                
                # Create chunk data
                chunk_data = {
                    'chunk_id': chunk.metadata['chunk_id'],
                    'text_content': chunk.page_content.strip(),
                    'document_title': document_title,
                    'source_url': url,
                    'page_number': chunk.metadata.get('page_number', 1),
                    'diseases': diseases,
                    'processed_at': datetime.now().isoformat(),
                    'job_id': job_id,
                    'metadata': {
                        'chunk_index': chunk.metadata.get('chunk_index', 0),
                        'total_chunks': chunk.metadata.get('total_chunks', len(chunks)),
                        'chunk_size': len(chunk.page_content),
                        'file_size': chunk.metadata.get('file_size', 0),
                        'total_pages': chunk.metadata.get('total_pages', 1)
                    }
                }
                
                processed_chunks.append(chunk_data)
            
            return processed_chunks
            
        except Exception as e:
            raise DocumentProcessingError(f"Chunk processing failed: {str(e)}")
    
    async def extract_document_title(
        self, 
        chunks: List[LangChainDocument], 
        metadata: Dict[str, Any]
    ) -> str:
        """
        Extract document title from content or metadata
        
        Args:
            chunks: Document chunks
            metadata: Additional metadata
            
        Returns:
            str: Extracted or generated title
        """
        try:
            # Check metadata first
            if metadata.get('title'):
                return metadata['title']
            
            # Try to extract from first chunk
            if chunks:
                first_chunk = chunks[0].page_content.strip()
                lines = first_chunk.split('\n')
                
                # Look for title-like content in first few lines
                for line in lines[:5]:
                    line = line.strip()
                    if len(line) > 10 and len(line) < 200:
                        # Simple heuristic for title-like content
                        if not line.endswith('.') and len(line.split()) < 20:
                            return line
                
                # Fallback: use first 100 characters
                return first_chunk[:100].replace('\n', ' ').strip()
            
            # Final fallback
            return f"Document {datetime.now().strftime('%Y-%m-%d')}"
            
        except Exception:
            return f"Document {datetime.now().strftime('%Y-%m-%d')}"
    
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
    
    async def cleanup_file(self, file_path: str):
        """
        Clean up temporary file
        
        Args:
            file_path: Path to file to clean up
        """
        try:
            if os.path.exists(file_path):
                os.unlink(file_path)
                self.logger.debug(f"Cleaned up temporary file: {file_path}")
        except Exception as e:
            self.logger.warning(f"Failed to cleanup file {file_path}: {e}")