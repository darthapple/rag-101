"""
Document Manager

Handles document URL processing, validation, job management, and NATS publishing
for the RAG system's document processing pipeline.
"""

import asyncio
import logging
import json
import uuid
import re
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from urllib.parse import urlparse, quote
from dataclasses import dataclass, field

import aiohttp
import nats
from nats.aio.client import Client as NATS
from nats.js.api import PublishAck

from .config import get_config


@dataclass
class DocumentJob:
    """Document processing job data model"""
    job_id: str
    url: str
    title: Optional[str] = None
    submitted_at: datetime = field(default_factory=datetime.now)
    status: str = "queued"
    metadata: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None
    estimated_size: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary for serialization"""
        return {
            'job_id': self.job_id,
            'url': self.url,
            'title': self.title,
            'submitted_at': self.submitted_at.isoformat(),
            'status': self.status,
            'metadata': self.metadata,
            'session_id': self.session_id,
            'estimated_size': self.estimated_size
        }


class DocumentValidationError(Exception):
    """Exception raised when document validation fails"""
    pass


class DocumentPublishError(Exception):
    """Exception raised when document publishing fails"""
    pass


class DocumentManagerError(Exception):
    """Base exception for document manager errors"""
    pass


class DocumentManager:
    """
    Manager for document URL processing and job management.
    
    Handles URL validation, job creation, and NATS publishing for
    document processing requests.
    """
    
    def __init__(self):
        """Initialize document manager"""
        self.config = get_config()
        self.logger = logging.getLogger("document.manager")
        
        # NATS client
        self.nats_client: Optional[NATS] = None
        self._connected = False
        self._connection_lock = asyncio.Lock()
        
        # Configuration
        self.max_file_size = self.config.max_file_size
        self.allowed_schemes = ['http', 'https']
        self.blocked_domains = [
            'localhost', '127.0.0.1', '0.0.0.0', '::1',
            '10.', '192.168.', '172.16.', '172.17.', '172.18.', '172.19.',
            '172.20.', '172.21.', '172.22.', '172.23.', '172.24.', '172.25.',
            '172.26.', '172.27.', '172.28.', '172.29.', '172.30.', '172.31.'
        ]
        
        # HTTP client for HEAD requests
        self._http_session: Optional[aiohttp.ClientSession] = None
        
        self.logger.info("Document manager initialized")
    
    async def connect(self) -> bool:
        """
        Connect to NATS for job publishing
        
        Returns:
            bool: True if connected successfully
        """
        async with self._connection_lock:
            if self._connected:
                return True
            
            try:
                self.logger.info("Connecting to NATS for document publishing...")
                
                # Connect to NATS
                self.nats_client = await nats.connect(
                    servers=self.config.nats_servers,
                    max_reconnect_attempts=self.config.max_reconnect_attempts,
                    reconnect_time_wait=self.config.reconnect_time_wait,
                    ping_interval=self.config.ping_interval,
                    max_outstanding_pings=self.config.max_outstanding_pings
                )
                
                # Create HTTP session
                timeout = aiohttp.ClientTimeout(total=30)
                self._http_session = aiohttp.ClientSession(
                    timeout=timeout,
                    headers={'User-Agent': 'RAG-101-DocumentManager/1.0'}
                )
                
                self._connected = True
                self.logger.info("Document manager connected to NATS")
                return True
                
            except Exception as e:
                self.logger.error(f"Failed to connect document manager: {e}")
                self._connected = False
                return False
    
    async def disconnect(self):
        """Disconnect from NATS and cleanup"""
        try:
            if self._http_session:
                await self._http_session.close()
                self._http_session = None
            
            if self.nats_client and not self.nats_client.is_closed:
                await self.nats_client.close()
            
            self._connected = False
            self.nats_client = None
            
            self.logger.info("Document manager disconnected")
            
        except Exception as e:
            self.logger.error(f"Error disconnecting document manager: {e}")
    
    async def _ensure_connected(self):
        """Ensure NATS connection is established"""
        if not self._connected:
            success = await self.connect()
            if not success:
                raise DocumentManagerError("Failed to connect to NATS")
    
    def validate_url(self, url: str) -> Tuple[bool, str]:
        """
        Validate document URL with security checks
        
        Args:
            url: URL to validate
            
        Returns:
            Tuple[bool, str]: (is_valid, error_message)
        """
        try:
            # Basic URL structure validation
            if not url or not isinstance(url, str):
                return False, "URL is required and must be a string"
            
            url = url.strip()
            if len(url) > 2048:
                return False, "URL too long (maximum 2048 characters)"
            
            # Parse URL
            try:
                parsed = urlparse(url)
            except Exception:
                return False, "Invalid URL format"
            
            # Scheme validation
            if parsed.scheme not in self.allowed_schemes:
                return False, f"URL scheme must be one of: {', '.join(self.allowed_schemes)}"
            
            # Domain validation
            if not parsed.netloc:
                return False, "URL must have a valid domain"
            
            # Check for blocked domains (security)
            domain = parsed.netloc.lower()
            for blocked in self.blocked_domains:
                if domain.startswith(blocked.lower()):
                    return False, f"Domain blocked for security: {domain}"
            
            # File extension check (PDF)
            path = parsed.path.lower()
            if not path.endswith('.pdf'):
                return False, "URL must point to a PDF file (.pdf extension required)"
            
            # Check for suspicious patterns
            suspicious_patterns = [
                r'[<>"\']',  # HTML/JS injection chars
                r'javascript:',  # JavaScript protocol
                r'data:',  # Data URLs
                r'file:',  # File protocol
                r'ftp:',   # FTP protocol
            ]
            
            for pattern in suspicious_patterns:
                if re.search(pattern, url, re.IGNORECASE):
                    return False, f"URL contains suspicious pattern: {pattern}"
            
            return True, ""
            
        except Exception as e:
            self.logger.error(f"URL validation error: {e}")
            return False, f"URL validation failed: {str(e)}"
    
    async def validate_url_content(self, url: str) -> Tuple[bool, str, Optional[int]]:
        """
        Validate URL content with HEAD request
        
        Args:
            url: URL to validate
            
        Returns:
            Tuple[bool, str, Optional[int]]: (is_valid, error_message, content_length)
        """
        try:
            await self._ensure_connected()
            
            if not self._http_session:
                return False, "HTTP session not available", None
            
            # Perform HEAD request to check content
            try:
                async with self._http_session.head(url, allow_redirects=True) as response:
                    # Check status code
                    if response.status >= 400:
                        return False, f"URL returned error status: {response.status}", None
                    
                    # Check content type
                    content_type = response.headers.get('content-type', '').lower()
                    if 'application/pdf' not in content_type and 'pdf' not in content_type:
                        # Allow if no content-type header (some servers don't set it)
                        if content_type and content_type != 'application/octet-stream':
                            return False, f"URL does not serve PDF content (got: {content_type})", None
                    
                    # Check content length
                    content_length = None
                    if 'content-length' in response.headers:
                        try:
                            content_length = int(response.headers['content-length'])
                            if content_length > self.max_file_size:
                                size_mb = content_length / (1024 * 1024)
                                max_mb = self.max_file_size / (1024 * 1024)
                                return False, f"File too large: {size_mb:.1f}MB (max: {max_mb:.1f}MB)", content_length
                        except ValueError:
                            pass  # Invalid content-length header
                    
                    return True, "", content_length
                    
            except aiohttp.ClientError as e:
                return False, f"Could not access URL: {str(e)}", None
            except asyncio.TimeoutError:
                return False, "URL validation timeout", None
            
        except Exception as e:
            self.logger.error(f"URL content validation error: {e}")
            return False, f"Content validation failed: {str(e)}", None
    
    def create_job(
        self, 
        url: str, 
        session_id: Optional[str] = None,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> DocumentJob:
        """
        Create a document processing job
        
        Args:
            url: Document URL
            session_id: Optional session ID
            title: Optional document title
            metadata: Optional job metadata
            
        Returns:
            DocumentJob: Created job object
        """
        try:
            job_id = str(uuid.uuid4())
            
            job = DocumentJob(
                job_id=job_id,
                url=url,
                title=title or self._extract_title_from_url(url),
                session_id=session_id,
                metadata=metadata or {},
                status="queued",
                submitted_at=datetime.now()
            )
            
            self.logger.info(f"Created document job {job_id} for URL: {url}")
            return job
            
        except Exception as e:
            self.logger.error(f"Job creation failed: {e}")
            raise DocumentManagerError(f"Job creation failed: {e}")
    
    def _extract_title_from_url(self, url: str) -> str:
        """
        Extract document title from URL path
        
        Args:
            url: Document URL
            
        Returns:
            str: Extracted title
        """
        try:
            parsed = urlparse(url)
            path = parsed.path
            
            # Get filename from path
            filename = path.split('/')[-1] if path else 'document'
            
            # Remove .pdf extension
            if filename.lower().endswith('.pdf'):
                filename = filename[:-4]
            
            # Clean up filename for title
            title = filename.replace('_', ' ').replace('-', ' ')
            title = re.sub(r'\s+', ' ', title).strip()
            
            return title or 'Untitled Document'
            
        except Exception:
            return 'Untitled Document'
    
    async def publish_job(self, job: DocumentJob) -> bool:
        """
        Publish job to NATS for processing
        
        Args:
            job: Document job to publish
            
        Returns:
            bool: True if published successfully
            
        Raises:
            DocumentPublishError: If publishing fails
        """
        try:
            await self._ensure_connected()
            
            # Get JetStream context
            js = self.nats_client.jetstream()
            
            # Prepare message
            message_data = {
                'job_id': job.job_id,
                'url': job.url,
                'title': job.title,
                'session_id': job.session_id,
                'metadata': job.metadata,
                'submitted_at': job.submitted_at.isoformat(),
                'estimated_size': job.estimated_size
            }
            
            # Publish to documents.download topic
            ack: PublishAck = await js.publish(
                "documents.download",
                json.dumps(message_data).encode(),
                headers={'job_id': job.job_id}
            )
            
            self.logger.info(f"Published job {job.job_id} to NATS (seq: {ack.seq})")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to publish job {job.job_id}: {e}")
            raise DocumentPublishError(f"Job publishing failed: {e}")
    
    async def submit_document_url(
        self, 
        url: str,
        session_id: Optional[str] = None,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        validate_content: bool = True
    ) -> DocumentJob:
        """
        Complete document URL submission pipeline
        
        Args:
            url: Document URL to process
            session_id: Optional session ID
            title: Optional document title
            metadata: Optional job metadata
            validate_content: Whether to validate URL content
            
        Returns:
            DocumentJob: Created and published job
            
        Raises:
            DocumentValidationError: If URL validation fails
            DocumentManagerError: If submission fails
        """
        try:
            # Step 1: Validate URL format
            is_valid, error_msg = self.validate_url(url)
            if not is_valid:
                raise DocumentValidationError(f"URL validation failed: {error_msg}")
            
            # Step 2: Validate URL content (optional)
            estimated_size = None
            if validate_content:
                content_valid, content_error, size = await self.validate_url_content(url)
                if not content_valid:
                    raise DocumentValidationError(f"URL content validation failed: {content_error}")
                estimated_size = size
            
            # Step 3: Create job
            job = self.create_job(
                url=url,
                session_id=session_id,
                title=title,
                metadata=metadata
            )
            job.estimated_size = estimated_size
            
            # Step 4: Publish job
            await self.publish_job(job)
            
            return job
            
        except (DocumentValidationError, DocumentPublishError):
            raise
        except Exception as e:
            self.logger.error(f"Document submission failed: {e}")
            raise DocumentManagerError(f"Document submission failed: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get document manager statistics
        
        Returns:
            Dict[str, Any]: Statistics
        """
        return {
            'connected': self._connected,
            'max_file_size': self.max_file_size,
            'max_file_size_mb': round(self.max_file_size / (1024 * 1024), 1),
            'allowed_schemes': self.allowed_schemes,
            'blocked_domains_count': len(self.blocked_domains),
            'nats_connected': self._connected and self.nats_client and not self.nats_client.is_closed
        }


# Global document manager instance
_document_manager: Optional[DocumentManager] = None


def get_document_manager() -> DocumentManager:
    """Get global document manager instance"""
    global _document_manager
    if _document_manager is None:
        _document_manager = DocumentManager()
    return _document_manager