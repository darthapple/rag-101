"""
Document Handler

Processes document download requests and extracts text from PDFs.
Publishes extracted text with metadata to document chunking topic.
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
from langchain_community.document_loaders import PyPDFLoader
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
    Handler for document download and text extraction workflow:
    1. Download PDF from URL
    2. Extract text using PyPDFLoader
    3. Extract basic metadata (title, page info)
    4. Publish text with metadata to documents.chunk topic
    """
    
    def __init__(self, handler_name: str = "document-handler", max_workers: int = 2, infra_manager=None):
        """
        Initialize document handler
        
        Args:
            handler_name: Handler identifier
            max_workers: Maximum concurrent workers
        """
        super().__init__(handler_name, max_workers, infra_manager)
        
        # Document processing configuration
        self.max_file_size = self.config.max_file_size
        self.download_timeout = self.config.document_processing_timeout
        
        self.logger.info(
            "Document handler initialized",
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
            'durable_name': 'document-download-worker',
            'manual_ack': True,
            'pending_msgs_limit': self.max_workers * 2,
            'ack_wait': self.download_timeout * 2  # Double timeout for ack wait
        }
    
    def get_result_subject(self, data: Dict[str, Any]) -> Optional[str]:
        """Publish results to document chunking topic"""
        return "documents.chunks"
    
    async def process_message(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process document download and text extraction request
        
        Args:
            data: Message data containing URL and job information
            
        Returns:
            Dict[str, Any]: Processing result with extracted text and metadata
            
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
                
                # Extract document metadata
                document_title = await self.extract_document_title(documents, metadata)
                
                # Prepare document data for chunking
                document_data = {
                    'job_id': job_id,
                    'url': url,
                    'status': 'text_extracted',
                    'document_title': document_title,
                    'pages': [],
                    'file_info': file_info,
                    'metadata': metadata,
                    'extracted_at': datetime.now().isoformat()
                }
                
                # Add page content
                for i, doc in enumerate(documents):
                    page_data = {
                        'page_number': i + 1,
                        'text_content': doc.page_content.strip(),
                        'metadata': doc.metadata
                    }
                    document_data['pages'].append(page_data)
                
                self.logger.log_operation(
                    "document_processing",
                    (datetime.now() - processing_start_time).total_seconds(),
                    success=True,
                    url=url,
                    job_id=job_id,
                    page_count=len(documents),
                    file_size=file_info.get('file_size', 0)
                )
                
                return document_data
                
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
    
    
    
    async def extract_document_title(
        self, 
        documents: List[LangChainDocument], 
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
            
            # Try to extract from first document page
            if documents:
                first_document = documents[0].page_content.strip()
                lines = first_document.split('\n')
                
                # Look for title-like content in first few lines
                for line in lines[:5]:
                    line = line.strip()
                    if len(line) > 10 and len(line) < 200:
                        # Simple heuristic for title-like content
                        if not line.endswith('.') and len(line.split()) < 20:
                            return line
                
                # Fallback: use first 100 characters
                return first_document[:100].replace('\n', ' ').strip()
            
            # Final fallback
            return f"Document {datetime.now().strftime('%Y-%m-%d')}"
            
        except Exception:
            return f"Document {datetime.now().strftime('%Y-%m-%d')}"
    
    
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