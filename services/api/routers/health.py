"""
Health Router

Provides health check endpoints for service monitoring and diagnostics.
"""

import logging
import sys
from pathlib import Path
from typing import Dict, Any
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

from shared.config import get_config
from shared.websocket_manager import get_websocket_manager
from shared.session_manager import get_session_manager


# Response models
class HealthResponse(BaseModel):
    """Health check response model"""
    status: str
    service: str
    version: str
    timestamp: str
    uptime: float
    details: Dict[str, Any]


class ReadinessResponse(BaseModel):
    """Readiness check response model"""
    ready: bool
    services: Dict[str, bool]
    message: str


router = APIRouter()
logger = logging.getLogger("api.health")


@router.get("/", response_model=HealthResponse)
async def health_check():
    """
    Basic health check endpoint
    
    Returns:
        HealthResponse: Service health status
    """
    try:
        config = get_config()
        websocket_manager = get_websocket_manager()
        session_manager = get_session_manager()
        
        # Calculate uptime (assuming app start time tracking)
        start_time = datetime.now() - timedelta(seconds=300)  # Placeholder
        uptime = (datetime.now() - start_time).total_seconds()
        
        # Get WebSocket manager stats
        websocket_stats = websocket_manager.get_stats() if websocket_manager else {}
        
        # Get Session manager stats
        session_stats = await session_manager.get_stats() if session_manager else {}
        
        health_details = {
            "environment": config.environment,
            "websocket_manager": {
                "running": websocket_stats.get('manager_running', False),
                "connections": websocket_stats.get('active_connections', 0),
                "sessions": websocket_stats.get('active_sessions', 0),
                "nats_connected": websocket_stats.get('nats_connected', False)
            },
            "session_manager": {
                "connected": session_stats.get('connected', False),
                "active_sessions": session_stats.get('active_sessions', 0),
                "recently_active": session_stats.get('recently_active_sessions', 0),
                "total_questions": session_stats.get('total_questions', 0),
                "bucket_name": session_stats.get('bucket_name', 'sessions')
            },
            "configuration": {
                "nats_url": config.nats_url,
                "max_connections": config.max_websocket_connections,
                "session_ttl": config.session_ttl,
                "debug": config.debug
            }
        }
        
        return HealthResponse(
            status="healthy",
            service="rag-api",
            version="0.1.0",
            timestamp=datetime.now().isoformat(),
            uptime=uptime,
            details=health_details
        )
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Health check failed: {str(e)}"
        )


@router.get("/ready", response_model=ReadinessResponse)
async def readiness_check():
    """
    Readiness check endpoint for load balancers
    
    Returns:
        ReadinessResponse: Service readiness status
    """
    try:
        websocket_manager = get_websocket_manager()
        websocket_stats = websocket_manager.get_stats() if websocket_manager else {}
        
        session_manager = get_session_manager()
        session_stats = await session_manager.get_stats() if session_manager else {}
        
        # Check service dependencies
        services_status = {
            "websocket_manager": websocket_stats.get('manager_running', False),
            "session_manager": session_stats.get('connected', False),
            "nats": websocket_stats.get('nats_connected', False),
        }
        
        all_ready = all(services_status.values())
        
        message = "All services ready" if all_ready else "Some services not ready"
        
        response_status = status.HTTP_200_OK if all_ready else status.HTTP_503_SERVICE_UNAVAILABLE
        
        return ReadinessResponse(
            ready=all_ready,
            services=services_status,
            message=message
        )
        
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Readiness check failed: {str(e)}"
        )


@router.get("/metrics")
async def metrics():
    """
    Prometheus-compatible metrics endpoint
    
    Returns:
        Dict[str, Any]: Service metrics
    """
    try:
        websocket_manager = get_websocket_manager()
        websocket_stats = websocket_manager.get_stats() if websocket_manager else {}
        
        metrics = {
            "rag_api_websocket_connections_total": websocket_stats.get('active_connections', 0),
            "rag_api_websocket_sessions_total": websocket_stats.get('active_sessions', 0),
            "rag_api_websocket_messages_sent_total": websocket_stats.get('messages_sent', 0),
            "rag_api_websocket_messages_failed_total": websocket_stats.get('messages_failed', 0),
            "rag_api_websocket_connections_created_total": websocket_stats.get('connections_created', 0),
            "rag_api_websocket_connections_closed_total": websocket_stats.get('connections_closed', 0),
            "rag_api_nats_connected": 1 if websocket_stats.get('nats_connected', False) else 0,
        }
        
        return metrics
        
    except Exception as e:
        logger.error(f"Metrics collection failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Metrics collection failed: {str(e)}"
        )


@router.get("/version")
async def version_info():
    """
    Version information endpoint
    
    Returns:
        Dict[str, str]: Version details
    """
    return {
        "service": "rag-api",
        "version": "0.1.0",
        "build_time": "2024-01-01T00:00:00Z",  # Would be set during build
        "git_commit": "unknown",  # Would be set during build
        "python_version": sys.version,
        "description": "RAG-101 Medical Q&A API Service"
    }