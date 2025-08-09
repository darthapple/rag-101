"""
Sessions Router

Handles session management for Q&A interactions using NATS KV storage including:
- Session creation with nickname and TTL
- Session validation and retrieval
- Session lifecycle management
- Session statistics and monitoring
"""

import logging
import sys
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field, validator

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

from shared.config import get_config
from shared.session_manager import (
    get_session_manager, 
    Session,
    SessionManagerError,
    SessionNotFoundError,
    SessionExpiredError,
    SessionValidationError
)


# Request/Response models
class CreateSessionRequest(BaseModel):
    """Request model for creating a new session"""
    nickname: Optional[str] = Field(None, min_length=1, max_length=100, description="Session nickname")
    ttl: Optional[int] = Field(None, ge=60, le=86400, description="Session TTL in seconds (1 minute to 24 hours)")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Optional session metadata")
    
    @validator('nickname')
    def validate_nickname(cls, v):
        """Validate nickname format"""
        if v is not None:
            v = v.strip()
            if not v:
                return None
            # Remove any potentially harmful characters
            v = ''.join(c for c in v if c.isalnum() or c in ' -_.')
        return v


class SessionResponse(BaseModel):
    """Response model for session information"""
    session_id: str
    nickname: Optional[str]
    created_at: str
    expires_at: str
    is_active: bool
    question_count: int
    metadata: Dict[str, Any]
    last_activity: str


class SessionValidationResponse(BaseModel):
    """Response model for session validation"""
    valid: bool
    session_id: str
    reason: Optional[str] = None
    message: Optional[str] = None
    expires_at: Optional[str] = None


class SessionListResponse(BaseModel):
    """Response model for session list"""
    sessions: List[SessionResponse]
    total: int
    active_sessions: int
    stats: Dict[str, Any]


class SessionStatsResponse(BaseModel):
    """Response model for session statistics"""
    total_active_sessions: int
    recently_active_sessions: int
    total_questions: int
    average_session_age_seconds: float
    default_ttl: int
    nats_connected: bool


router = APIRouter()
logger = logging.getLogger("api.sessions")


def get_current_config():
    """Dependency to get current configuration"""
    return get_config()


async def get_session_manager_dependency():
    """Dependency to get session manager and ensure connection"""
    session_manager = get_session_manager()
    
    # Ensure connection is established
    if not session_manager._connected:
        connected = await session_manager.connect()
        if not connected:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Session service unavailable - could not connect to NATS"
            )
    
    return session_manager


@router.post("/", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    request: CreateSessionRequest,
    config = Depends(get_current_config),
    session_manager = Depends(get_session_manager_dependency)
):
    """
    Create a new Q&A session with NATS KV storage
    
    Args:
        request: Session creation request
        config: Application configuration
        session_manager: NATS session manager
    
    Returns:
        SessionResponse: Created session information
        
    Raises:
        HTTPException: If session creation fails
    """
    try:
        # Create session using NATS session manager
        session = await session_manager.create_session(
            nickname=request.nickname,
            ttl=request.ttl,
            metadata=request.metadata
        )
        
        logger.info(f"Created session {session.session_id} with nickname '{session.nickname}'")
        
        return SessionResponse(
            session_id=session.session_id,
            nickname=session.nickname,
            created_at=session.created_at.isoformat(),
            expires_at=session.expires_at.isoformat() if session.expires_at else "",
            is_active=session.is_active(),
            question_count=session.question_count,
            metadata=session.metadata,
            last_activity=session.last_activity.isoformat()
        )
        
    except SessionManagerError as e:
        logger.error(f"Session creation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Session creation failed: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error creating session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Session creation failed due to internal error"
        )


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    session_manager = Depends(get_session_manager_dependency)
):
    """
    Get session information by ID
    
    Args:
        session_id: Session identifier
        session_manager: NATS session manager
        
    Returns:
        SessionResponse: Session information
        
    Raises:
        HTTPException: If session not found or expired
    """
    try:
        session = await session_manager.get_session(session_id)
        
        return SessionResponse(
            session_id=session.session_id,
            nickname=session.nickname,
            created_at=session.created_at.isoformat(),
            expires_at=session.expires_at.isoformat() if session.expires_at else "",
            is_active=session.is_active(),
            question_count=session.question_count,
            metadata=session.metadata,
            last_activity=session.last_activity.isoformat()
        )
        
    except SessionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found"
        )
    except SessionExpiredError:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"Session {session_id} has expired"
        )
    except SessionManagerError as e:
        logger.error(f"Failed to get session {session_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Session retrieval failed: {str(e)}"
        )


@router.put("/{session_id}/metadata")
async def update_session_metadata(
    session_id: str,
    metadata: Dict[str, Any],
    session_manager = Depends(get_session_manager_dependency)
):
    """
    Update session metadata
    
    Args:
        session_id: Session identifier
        metadata: New metadata to merge with existing
        session_manager: NATS session manager
        
    Returns:
        Dict[str, str]: Success message
        
    Raises:
        HTTPException: If session not found or update fails
    """
    try:
        # Get current session
        session = await session_manager.get_session(session_id)
        
        # Merge metadata
        session.metadata.update(metadata)
        
        # Update session
        await session_manager.update_session(session)
        
        logger.info(f"Updated metadata for session {session_id}")
        
        return {"message": "Session metadata updated successfully"}
        
    except SessionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found"
        )
    except SessionExpiredError:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"Session {session_id} has expired"
        )
    except SessionManagerError as e:
        logger.error(f"Failed to update session {session_id} metadata: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Metadata update failed: {str(e)}"
        )


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    session_manager = Depends(get_session_manager_dependency)
):
    """
    Delete/invalidate a session
    
    Args:
        session_id: Session identifier
        session_manager: NATS session manager
        
    Returns:
        Dict[str, str]: Success message
        
    Raises:
        HTTPException: If deletion fails
    """
    try:
        success = await session_manager.delete_session(session_id)
        
        if success:
            logger.info(f"Deleted session {session_id}")
            return {"message": f"Session {session_id} deleted successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Session deletion failed"
            )
        
    except SessionManagerError as e:
        logger.error(f"Failed to delete session {session_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Session deletion failed: {str(e)}"
        )


@router.post("/{session_id}/validate", response_model=SessionValidationResponse)
async def validate_session(
    session_id: str,
    session_manager = Depends(get_session_manager_dependency)
):
    """
    Validate that a session exists and is active
    
    Args:
        session_id: Session identifier
        session_manager: NATS session manager
        
    Returns:
        SessionValidationResponse: Validation result with detailed information
    """
    try:
        # Try to get the session
        session = await session_manager.get_session(session_id)
        
        return SessionValidationResponse(
            valid=True,
            session_id=session_id,
            expires_at=session.expires_at.isoformat() if session.expires_at else None
        )
        
    except SessionNotFoundError:
        return SessionValidationResponse(
            valid=False,
            session_id=session_id,
            reason="session_not_found",
            message=f"Session {session_id} not found"
        )
    except SessionExpiredError:
        return SessionValidationResponse(
            valid=False,
            session_id=session_id,
            reason="session_expired",
            message=f"Session {session_id} has expired"
        )
    except SessionManagerError as e:
        logger.error(f"Session validation error for {session_id}: {e}")
        return SessionValidationResponse(
            valid=False,
            session_id=session_id,
            reason="validation_error",
            message=f"Validation failed: {str(e)}"
        )


@router.post("/{session_id}/extend")
async def extend_session(
    session_id: str,
    additional_seconds: int = Field(3600, ge=60, le=86400, description="Additional seconds to add to TTL"),
    session_manager = Depends(get_session_manager_dependency)
):
    """
    Extend session TTL
    
    Args:
        session_id: Session identifier
        additional_seconds: Additional seconds to add to session TTL
        session_manager: NATS session manager
        
    Returns:
        SessionResponse: Updated session information
        
    Raises:
        HTTPException: If session not found or extension fails
    """
    try:
        session = await session_manager.extend_session(session_id, additional_seconds)
        
        logger.info(f"Extended session {session_id} by {additional_seconds} seconds")
        
        return SessionResponse(
            session_id=session.session_id,
            nickname=session.nickname,
            created_at=session.created_at.isoformat(),
            expires_at=session.expires_at.isoformat() if session.expires_at else "",
            is_active=session.is_active(),
            question_count=session.question_count,
            metadata=session.metadata,
            last_activity=session.last_activity.isoformat()
        )
        
    except SessionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found"
        )
    except SessionExpiredError:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"Session {session_id} has expired"
        )
    except SessionManagerError as e:
        logger.error(f"Failed to extend session {session_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Session extension failed: {str(e)}"
        )


@router.get("/", response_model=SessionListResponse)
async def list_sessions(
    limit: int = Field(50, ge=1, le=500, description="Maximum number of sessions to return"),
    session_manager = Depends(get_session_manager_dependency)
):
    """
    List active sessions with statistics
    
    Args:
        limit: Maximum number of sessions to return
        session_manager: NATS session manager
        
    Returns:
        SessionListResponse: List of active sessions with statistics
    """
    try:
        # Get active sessions
        sessions = await session_manager.list_active_sessions(limit=limit)
        
        # Get session manager statistics
        stats = await session_manager.get_stats()
        
        # Convert sessions to response format
        session_responses = []
        for session in sessions:
            session_response = SessionResponse(
                session_id=session.session_id,
                nickname=session.nickname,
                created_at=session.created_at.isoformat(),
                expires_at=session.expires_at.isoformat() if session.expires_at else "",
                is_active=session.is_active(),
                question_count=session.question_count,
                metadata=session.metadata,
                last_activity=session.last_activity.isoformat()
            )
            session_responses.append(session_response)
        
        return SessionListResponse(
            sessions=session_responses,
            total=len(session_responses),
            active_sessions=stats.get('active_sessions', len(session_responses)),
            stats=stats
        )
        
    except SessionManagerError as e:
        logger.error(f"Failed to list sessions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Session listing failed: {str(e)}"
        )


@router.get("/stats", response_model=SessionStatsResponse)
async def get_session_stats(
    session_manager = Depends(get_session_manager_dependency)
):
    """
    Get session management statistics
    
    Args:
        session_manager: NATS session manager
        
    Returns:
        SessionStatsResponse: Detailed session statistics
    """
    try:
        stats = await session_manager.get_stats()
        
        return SessionStatsResponse(
            total_active_sessions=stats.get('active_sessions', 0),
            recently_active_sessions=stats.get('recently_active_sessions', 0),
            total_questions=stats.get('total_questions', 0),
            average_session_age_seconds=stats.get('average_session_age_seconds', 0),
            default_ttl=stats.get('default_ttl', 3600),
            nats_connected=stats.get('connected', False)
        )
        
    except SessionManagerError as e:
        logger.error(f"Failed to get session stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Statistics collection failed: {str(e)}"
        )


@router.post("/{session_id}/activity")
async def update_session_activity(
    session_id: str,
    increment_questions: bool = Field(False, description="Whether to increment question count"),
    session_manager = Depends(get_session_manager_dependency)
):
    """
    Update session activity (last activity timestamp and optionally question count)
    
    Args:
        session_id: Session identifier
        increment_questions: Whether to increment the question count
        session_manager: NATS session manager
        
    Returns:
        Dict[str, Any]: Updated activity information
        
    Raises:
        HTTPException: If session not found or update fails
    """
    try:
        session = await session_manager.get_session(session_id)
        
        # Update activity
        if increment_questions:
            session.increment_question_count()
        else:
            session.update_activity()
        
        # Save updated session
        await session_manager.update_session(session)
        
        return {
            "message": "Session activity updated",
            "session_id": session_id,
            "last_activity": session.last_activity.isoformat(),
            "question_count": session.question_count
        }
        
    except SessionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found"
        )
    except SessionExpiredError:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"Session {session_id} has expired"
        )
    except SessionManagerError as e:
        logger.error(f"Failed to update activity for session {session_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Activity update failed: {str(e)}"
        )