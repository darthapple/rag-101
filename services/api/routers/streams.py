"""
NATS Streams Router

Provides real-time NATS stream statistics for dashboard monitoring.
Returns message counts for document processing and Q&A workflows.
"""

import logging
import sys
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

from shared.database import get_database


# Response models
class WorkflowStats(BaseModel):
    """Workflow statistics model"""
    downloads: int = 0
    chunks: int = 0 
    embeddings: int = 0
    complete: int = 0


class QAStats(BaseModel):
    """Q&A workflow statistics model"""
    questions: int = 0
    answers_total: int = 0


class StreamsResponse(BaseModel):
    """NATS streams statistics response"""
    milvus_documents: int
    document_workflow: WorkflowStats
    qa_workflow: QAStats
    timestamp: str
    status: str = "healthy"


router = APIRouter()
logger = logging.getLogger("api.streams")


@router.get("/", response_model=StreamsResponse)
async def get_streams_stats():
    """
    Get real-time NATS stream statistics for dashboard
    
    Returns:
        StreamsResponse: Stream statistics including workflow counts
    """
    try:
        # Get NATS client from global infra manager  
        import main
        infra_manager = main.infra_manager
        
        nats_client = None
        nats_available = False
        
        if infra_manager and infra_manager.nc and not infra_manager.nc.is_closed:
            nats_client = infra_manager
            nats_available = True
            logger.debug(f"Using infra manager NATS client: connected={nats_available}")
        else:
            logger.debug("Infra manager NATS client not available")

        # Get Milvus document count
        milvus_documents = await get_milvus_document_count()
        
        # Get document workflow statistics  
        if nats_available:
            document_workflow = await get_document_workflow_stats(infra_manager)
            qa_workflow = await get_qa_workflow_stats(infra_manager)
        else:
            document_workflow = WorkflowStats()
            qa_workflow = QAStats()
        
        from datetime import datetime
        
        return StreamsResponse(
            milvus_documents=milvus_documents,
            document_workflow=document_workflow,
            qa_workflow=qa_workflow,
            timestamp=datetime.now().isoformat(),
            status="healthy"
        )
        
    except Exception as e:
        logger.error(f"Failed to get streams statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Streams statistics failed: {str(e)}"
        )


async def get_milvus_document_count() -> int:
    """Get total document count from Milvus"""
    try:
        milvus_db = get_database()
        if not milvus_db:
            return 0
            
        # Get document count from collection
        return milvus_db.count_documents()
        
    except Exception as e:
        logger.error(f"Failed to get Milvus document count: {e}")
        return 0


async def get_document_workflow_stats(infra_manager) -> WorkflowStats:
    """Get document processing workflow statistics from NATS streams"""
    try:
        js = infra_manager.js
        logger.debug(f"JetStream context type: {type(js)}")
        workflow_stats = WorkflowStats()
        
        # Get individual workflow stream info
        try:
            # Downloads stream
            downloads_stream = await js.stream_info("documents_download")
            workflow_stats.downloads = downloads_stream.state.messages
        except Exception as e:
            logger.debug(f"Downloads stream not found or error: {e}")
            
        try:
            # Chunks stream  
            chunks_stream = await js.stream_info("documents_chunks")
            workflow_stats.chunks = chunks_stream.state.messages
        except Exception as e:
            logger.debug(f"Chunks stream not found or error: {e}")
            
        try:
            # Embeddings stream
            embeddings_stream = await js.stream_info("documents_embeddings")
            workflow_stats.embeddings = embeddings_stream.state.messages
        except Exception as e:
            logger.debug(f"Embeddings stream not found or error: {e}")
            
        # Complete count could be based on successful embeddings or a separate stream
        # For now, use embeddings count as proxy for completed documents
        workflow_stats.complete = workflow_stats.embeddings
            
        return workflow_stats
        
    except Exception as e:
        logger.error(f"Failed to get document workflow stats: {e}")
        return WorkflowStats()


async def get_qa_workflow_stats(infra_manager) -> QAStats:
    """Get Q&A workflow statistics from NATS streams"""
    try:
        js = infra_manager.js
        qa_stats = QAStats()
        
        # Get questions stream info
        try:
            questions_stream = await js.stream_info("chat_questions")
            qa_stats.questions = questions_stream.state.messages
        except Exception as e:
            logger.debug(f"Questions stream not found or error: {e}")
            
        # Get answers stream info
        try:
            answers_stream = await js.stream_info("chat_answers")
            qa_stats.answers_total = answers_stream.state.messages
        except Exception as e:
            logger.debug(f"Answers stream not found or error: {e}")
            
        return qa_stats
        
    except Exception as e:
        logger.error(f"Failed to get Q&A workflow stats: {e}")
        return QAStats()


@router.get("/health")
async def streams_health():
    """
    Health check for streams endpoint
    
    Returns:
        Dict[str, str]: Service health status
    """
    try:
        import main
        infra_manager = main.infra_manager
        
        nats_connected = infra_manager and infra_manager.nc and not infra_manager.nc.is_closed
        
        milvus_db = get_database()
        milvus_connected = milvus_db is not None
        
        return {
            "service": "streams",
            "status": "healthy" if (nats_connected and milvus_connected) else "degraded",
            "nats_connected": nats_connected,
            "milvus_connected": milvus_connected
        }
        
    except Exception as e:
        logger.error(f"Streams health check failed: {e}")
        return {
            "service": "streams", 
            "status": "unhealthy",
            "error": str(e)
        }