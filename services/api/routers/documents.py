"""
Documents Router

Handles document URL submission and processing management including:
- PDF document URL submission and validation
- Document processing job management
- Processing status tracking and monitoring
"""

import logging
import sys
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field, HttpUrl, validator

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

from shared.config import get_config
from shared.document_manager import (
    get_document_manager,
    DocumentJob,
    DocumentValidationError,
    DocumentPublishError,
    DocumentManagerError
)
from shared.session_manager import Session
from middleware.session_middleware import get_optional_session
from middleware.rate_limiter import document_upload_rate_limit


# Request/Response models
class DocumentSubmissionRequest(BaseModel):
    """Request model for document URL submission"""
    url: str = Field(..., min_length=10, max_length=2048, description="PDF document URL")
    title: Optional[str] = Field(None, min_length=1, max_length=200, description="Optional document title")
    validate_content: bool = Field(True, description="Whether to validate URL content before processing")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Optional document metadata")
    
    @validator('url')
    def validate_url_format(cls, v):
        """Basic URL format validation"""
        v = v.strip()
        if not v.startswith(('http://', 'https://')):
            raise ValueError('URL must start with http:// or https://')
        if not v.lower().endswith('.pdf'):
            raise ValueError('URL must point to a PDF file')
        return v
    
    @validator('title')
    def validate_title(cls, v):
        """Title validation"""
        if v is not None:
            v = v.strip()
            if not v:
                return None
            # Remove potentially harmful characters
            v = ''.join(c for c in v if c.isprintable() and c not in '<>&"\'')
        return v


class DocumentSubmissionResponse(BaseModel):
    """Response model for document submission"""
    job_id: str
    url: str
    title: str
    status: str
    submitted_at: str
    session_id: Optional[str]
    estimated_size: Optional[int]
    estimated_processing_time: Optional[str]
    message: str


class DocumentJobStatusResponse(BaseModel):
    """Response model for job status"""
    job_id: str
    url: str
    title: str
    status: str
    submitted_at: str
    progress: Dict[str, Any]
    session_id: Optional[str]
    estimated_size: Optional[int]
    error_message: Optional[str] = None


class DocumentValidationResponse(BaseModel):
    """Response model for URL validation"""
    url: str
    valid: bool
    reason: Optional[str] = None
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    size_mb: Optional[float] = None


router = APIRouter()
logger = logging.getLogger("api.documents")


def get_current_config():
    """Dependency to get current configuration"""
    return get_config()


async def get_document_manager_dependency():
    """Dependency to get document manager and ensure connection"""
    document_manager = get_document_manager()
    
    # Ensure connection
    if not document_manager._connected:
        connected = await document_manager.connect()
        if not connected:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Document service unavailable - could not connect to NATS"
            )
    
    return document_manager


@router.post("/submit", response_model=DocumentSubmissionResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_document_url(
    request: DocumentSubmissionRequest,
    config = Depends(get_current_config),
    document_manager = Depends(get_document_manager_dependency),
    session: Optional[Session] = Depends(get_optional_session),
    _rate_limit = Depends(document_upload_rate_limit)
):
    """
    Submit a PDF document URL for processing
    
    Args:
        request: Document submission request
        config: Application configuration
        document_manager: Document manager instance
        session: Optional user session
        _rate_limit: Rate limiting check
        
    Returns:
        DocumentSubmissionResponse: Submission confirmation with job details
        
    Raises:
        HTTPException: If submission fails
    """
    try:
        session_id = session.session_id if session else None
        
        # Submit document URL through document manager
        job = await document_manager.submit_document_url(
            url=request.url,
            session_id=session_id,
            title=request.title,
            metadata=request.metadata,
            validate_content=request.validate_content
        )
        
        # Estimate processing time based on file size
        estimated_time = "2-5 minutes"
        if job.estimated_size:
            # Rough estimate: 1 minute per 10MB
            minutes = max(2, (job.estimated_size // (10 * 1024 * 1024)) + 2)
            estimated_time = f"{minutes}-{minutes+3} minutes"
        
        logger.info(f"Submitted document {job.job_id} from session {session_id}")
        
        return DocumentSubmissionResponse(
            job_id=job.job_id,
            url=job.url,
            title=job.title,
            status=job.status,
            submitted_at=job.submitted_at.isoformat(),
            session_id=job.session_id,
            estimated_size=job.estimated_size,
            estimated_processing_time=estimated_time,
            message="Document submitted for processing successfully"
        )
        
    except DocumentValidationError as e:
        logger.warning(f"Document validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Document validation failed: {str(e)}"
        )
    except DocumentPublishError as e:
        logger.error(f"Document publishing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document processing service temporarily unavailable"
        )
    except DocumentManagerError as e:
        logger.error(f"Document submission failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Document submission failed: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error in document submission: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document submission failed due to internal error"
        )


@router.post("/validate", response_model=DocumentValidationResponse)
async def validate_document_url(
    request: DocumentSubmissionRequest,
    document_manager = Depends(get_document_manager_dependency),
    session: Optional[Session] = Depends(get_optional_session)
):
    """
    Validate a PDF document URL without submitting for processing
    
    Args:
        request: Document validation request (same as submission)
        document_manager: Document manager instance
        session: Optional user session
        
    Returns:
        DocumentValidationResponse: Validation result with details
    """
    try:
        # Step 1: Validate URL format
        is_valid, error_msg = document_manager.validate_url(request.url)
        
        if not is_valid:
            return DocumentValidationResponse(
                url=request.url,
                valid=False,
                reason=error_msg
            )
        
        # Step 2: Validate URL content if requested
        if request.validate_content:
            content_valid, content_error, size = await document_manager.validate_url_content(request.url)
            
            size_mb = None
            if size:
                size_mb = round(size / (1024 * 1024), 2)
            
            return DocumentValidationResponse(
                url=request.url,
                valid=content_valid,
                reason=content_error if not content_valid else None,
                size_bytes=size,
                size_mb=size_mb
            )
        else:
            return DocumentValidationResponse(
                url=request.url,
                valid=True,
                reason="URL format validation passed (content not checked)"
            )
        
    except Exception as e:
        logger.error(f"Document validation failed: {e}")
        return DocumentValidationResponse(
            url=request.url,
            valid=False,
            reason=f"Validation error: {str(e)}"
        )


@router.get("/jobs/{job_id}/status", response_model=DocumentJobStatusResponse)
async def get_job_status(
    job_id: str,
    session: Optional[Session] = Depends(get_optional_session)
):
    """
    Get processing status for a document job
    
    Args:
        job_id: Document job identifier
        session: Optional user session
        
    Returns:
        DocumentJobStatusResponse: Current job status and progress
        
    Note: This is a placeholder implementation. In a full system, job status
        would be retrieved from NATS KV or a job tracking database.
    """
    try:
        # Placeholder implementation - in reality this would query NATS KV or job store
        # For demonstration, we'll simulate some job progression
        
        import time
        import uuid
        
        # Validate job ID format
        try:
            uuid.UUID(job_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid job ID format"
            )
        
        # Simulate job progression based on time
        # In real implementation, this would come from the worker service
        current_time = time.time()
        job_start_time = current_time - 120  # Assume job started 2 minutes ago
        elapsed = current_time - job_start_time
        
        # Determine status based on elapsed time
        if elapsed < 30:
            status_val = "queued"
            progress = {
                "stage": "queued",
                "percentage": 0,
                "message": "Job queued for processing"
            }
        elif elapsed < 60:
            status_val = "downloading"
            progress = {
                "stage": "downloading",
                "percentage": 25,
                "message": "Downloading PDF document"
            }
        elif elapsed < 120:
            status_val = "processing"
            progress = {
                "stage": "chunking",
                "percentage": 60,
                "message": "Processing document and creating chunks"
            }
        elif elapsed < 180:
            status_val = "embedding"
            progress = {
                "stage": "embedding", 
                "percentage": 85,
                "message": "Generating vector embeddings"
            }
        else:
            status_val = "completed"
            progress = {
                "stage": "completed",
                "percentage": 100,
                "message": "Document processing completed successfully"
            }
        
        return DocumentJobStatusResponse(
            job_id=job_id,
            url=f"https://example.com/documents/{job_id}.pdf",
            title=f"Document {job_id[:8]}",
            status=status_val,
            submitted_at=datetime.fromtimestamp(job_start_time).isoformat(),
            progress=progress,
            session_id=session.session_id if session else None,
            estimated_size=1024*1024*5,  # 5MB placeholder
            error_message=None
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job status for {job_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve job status"
        )


@router.delete("/jobs/{job_id}")
async def cancel_job(
    job_id: str,
    session: Optional[Session] = Depends(get_optional_session)
):
    """
    Cancel a document processing job
    
    Args:
        job_id: Document job identifier  
        session: Optional user session
        
    Returns:
        Dict[str, str]: Cancellation confirmation
        
    Note: This is a placeholder implementation. In a full system, this would
        send a cancellation message to the worker service via NATS.
    """
    try:
        # Validate job ID format
        try:
            uuid.UUID(job_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid job ID format"
            )
        
        # In a real implementation, this would:
        # 1. Check if job exists and belongs to session (if provided)
        # 2. Check if job is cancellable (not completed/failed)
        # 3. Send cancellation message to worker via NATS
        # 4. Update job status to "cancelled"
        
        logger.info(f"Job {job_id} cancellation requested from session {session.session_id if session else 'anonymous'}")
        
        return {
            "message": f"Cancellation requested for job {job_id}",
            "job_id": job_id,
            "status": "cancellation_requested"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling job {job_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel job"
        )


@router.get("/stats")
async def get_document_stats(
    document_manager = Depends(get_document_manager_dependency),
    session: Optional[Session] = Depends(get_optional_session)
):
    """
    Get document processing statistics
    
    Args:
        document_manager: Document manager instance
        session: Optional user session
        
    Returns:
        Dict[str, Any]: Document processing statistics
    """
    try:
        stats = document_manager.get_stats()
        
        # Add service-level stats
        stats.update({
            'service_name': 'document-manager',
            'endpoints_available': [
                '/submit', '/validate', '/jobs/{job_id}/status',
                '/jobs/{job_id}', '/stats'
            ],
            'rate_limits': {
                'document_upload': '10 requests per 5 minutes',
                'validation': 'unlimited'
            }
        })
        
        return stats
        
    except Exception as e:
        logger.error(f"Error getting document stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve statistics"
        )


@router.get("/health")
async def document_service_health(
    document_manager = Depends(get_document_manager_dependency)
):
    """
    Document service health check
    
    Args:
        document_manager: Document manager instance
        
    Returns:
        Dict[str, Any]: Service health information
    """
    try:
        stats = document_manager.get_stats()
        
        return {
            'service': 'document-manager',
            'status': 'healthy' if stats['connected'] else 'degraded',
            'nats_connected': stats['nats_connected'],
            'timestamp': datetime.now().isoformat(),
            'details': stats
        }
        
    except Exception as e:
        logger.error(f"Document service health check failed: {e}")
        return {
            'service': 'document-manager',
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }