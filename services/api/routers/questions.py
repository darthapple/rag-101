"""
Questions Router

Handles Q&A interactions including:
- Question submission
- Answer retrieval
- Question history management
"""

import logging
import sys
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field, validator

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

from shared.config import get_config
from shared.session_manager import Session, get_session_manager
from shared.question_manager import (
    get_question_manager,
    QuestionJob,
    QuestionValidationError,
    QuestionPublishError,
    QuestionManagerError
)
from middleware.session_middleware import get_session_dependency
from middleware.rate_limiter import question_submit_rate_limit


# Request/Response models
class QuestionRequest(BaseModel):
    """Request model for submitting a question"""
    question: str = Field(..., min_length=5, max_length=1000, description="Question text")
    context: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional context")
    priority: Optional[str] = Field("normal", description="Question priority (low, normal, high)")
    
    @validator('question')
    def validate_question(cls, v):
        """Question validation"""
        v = v.strip()
        if not v:
            raise ValueError('Question cannot be empty')
        # Remove potentially harmful characters
        v = ''.join(c for c in v if c.isprintable() and c not in '<>&"\'')
        return v
    
    @validator('priority')
    def validate_priority(cls, v):
        """Priority validation"""
        if v not in ['low', 'normal', 'high']:
            return 'normal'
        return v


class QuestionResponse(BaseModel):
    """Response model for question submission"""
    question_id: str
    session_id: str
    question: str
    status: str
    submitted_at: str
    estimated_response_time: Optional[str] = None
    priority: str
    message: str


class AnswerResponse(BaseModel):
    """Response model for answer data"""
    question_id: str
    session_id: str
    question: str
    answer: str
    sources: List[Dict[str, Any]]
    confidence_score: Optional[float]
    generated_at: str
    model_used: str
    processing_time: float


class QuestionHistoryResponse(BaseModel):
    """Response model for question history"""
    session_id: str
    questions: List[Dict[str, Any]]
    total: int
    page: int
    size: int


router = APIRouter()
logger = logging.getLogger("api.questions")

def get_current_config():
    """Dependency to get current configuration"""
    return get_config()


async def get_question_manager_dependency():
    """Dependency to get question manager and ensure connection"""
    question_manager = get_question_manager()
    
    # Ensure connection
    if not question_manager._connected:
        connected = await question_manager.connect()
        if not connected:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Question service unavailable - could not connect to NATS"
            )
    
    return question_manager


@router.post("/", response_model=QuestionResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_question(
    request: QuestionRequest,
    session: Session = Depends(get_session_dependency),
    question_manager = Depends(get_question_manager_dependency),
    _rate_limit = Depends(question_submit_rate_limit)
):
    """
    Submit a question for processing
    
    Args:
        request: Question submission request
        session: User session (from session middleware)
        question_manager: Question manager instance
        _rate_limit: Rate limiting check
        
    Returns:
        QuestionResponse: Question submission confirmation
        
    Raises:
        HTTPException: If submission fails
    """
    try:
        # Submit question through question manager
        job = await question_manager.submit_question(
            question=request.question,
            session_id=session.session_id,
            context=request.context,
            priority=request.priority
        )
        
        # Estimate response time based on priority
        if request.priority == "high":
            estimated_time = "3-8 seconds"
        elif request.priority == "low":
            estimated_time = "10-30 seconds"
        else:
            estimated_time = "5-15 seconds"
        
        logger.info(f"Submitted question {job.question_id} for session {session.session_id}")
        
        return QuestionResponse(
            question_id=job.question_id,
            session_id=job.session_id,
            question=job.question,
            status=job.status,
            submitted_at=job.submitted_at.isoformat(),
            estimated_response_time=estimated_time,
            priority=job.priority,
            message="Question submitted for processing successfully"
        )
        
    except QuestionValidationError as e:
        logger.warning(f"Question validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Question validation failed: {str(e)}"
        )
    except QuestionPublishError as e:
        logger.error(f"Question publishing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Question processing service temporarily unavailable"
        )
    except QuestionManagerError as e:
        logger.error(f"Question submission failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Question submission failed: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error in question submission: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Question submission failed due to internal error"
        )


@router.get("/{question_id}/status")
async def get_question_status(question_id: str):
    """
    Get question processing status
    
    Args:
        question_id: Question identifier
        
    Returns:
        Dict[str, Any]: Question status information
    """
    try:
        # Check if question exists
        question_data = _questions.get(question_id)
        if not question_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Question {question_id} not found"
            )
        
        # Simulate processing progression
        now = datetime.now()
        elapsed = (now - question_data['submitted_at']).total_seconds()
        
        if question_data['status'] == 'submitted' and elapsed > 2:
            question_data['status'] = 'processing'
            question_data['processing_started_at'] = now
            question_data['updated_at'] = now
        
        if question_data['status'] == 'processing' and elapsed > 8:
            # Simulate answer generation
            answer_data = {
                'question_id': question_id,
                'session_id': question_data['session_id'],
                'question': question_data['question'],
                'answer': f"Esta é uma resposta simulada para a pergunta: '{question_data['question'][:50]}...'. Em um sistema real, isso seria gerado pela pipeline RAG usando os documentos médicos indexados.",
                'sources': [
                    {
                        'document_title': 'PCDT - Protocolo Exemplo',
                        'source_url': 'https://example.gov.br/protocolo-exemplo.pdf',
                        'page_number': 15,
                        'relevance_score': 0.85,
                        'excerpt': 'Fragmento relevante do documento...'
                    }
                ],
                'confidence_score': 0.82,
                'generated_at': now,
                'model_used': 'gemini-pro',
                'processing_time': elapsed
            }
            
            _answers[question_id] = answer_data
            question_data['status'] = 'answered'
            question_data['answered_at'] = now
            question_data['updated_at'] = now
        
        status_info = {
            'question_id': question_data['question_id'],
            'session_id': question_data['session_id'],
            'status': question_data['status'],
            'submitted_at': question_data['submitted_at'].isoformat(),
            'updated_at': question_data['updated_at'].isoformat(),
        }
        
        if question_data['processing_started_at']:
            status_info['processing_started_at'] = question_data['processing_started_at'].isoformat()
        
        if question_data['answered_at']:
            status_info['answered_at'] = question_data['answered_at'].isoformat()
            status_info['has_answer'] = True
        else:
            status_info['has_answer'] = False
        
        return status_info
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get question status {question_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Status check failed: {str(e)}"
        )


@router.get("/{question_id}/answer", response_model=AnswerResponse)
async def get_answer(question_id: str):
    """
    Get answer for a specific question
    
    Args:
        question_id: Question identifier
        
    Returns:
        AnswerResponse: Generated answer with sources
    """
    try:
        # Check if question exists
        question_data = _questions.get(question_id)
        if not question_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Question {question_id} not found"
            )
        
        # Check if answer exists
        answer_data = _answers.get(question_id)
        if not answer_data:
            if question_data['status'] in ['submitted', 'processing']:
                raise HTTPException(
                    status_code=status.HTTP_202_ACCEPTED,
                    detail=f"Answer for question {question_id} is still being processed"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Answer for question {question_id} not found"
                )
        
        return AnswerResponse(
            question_id=answer_data['question_id'],
            session_id=answer_data['session_id'],
            question=answer_data['question'],
            answer=answer_data['answer'],
            sources=answer_data['sources'],
            confidence_score=answer_data['confidence_score'],
            generated_at=answer_data['generated_at'].isoformat(),
            model_used=answer_data['model_used'],
            processing_time=answer_data['processing_time']
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get answer for question {question_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Answer retrieval failed: {str(e)}"
        )


@router.get("/sessions/{session_id}/history", response_model=QuestionHistoryResponse)
async def get_session_history(
    session_id: str,
    page: int = 1,
    size: int = 20,
    include_answers: bool = True
):
    """
    Get question history for a session
    
    Args:
        session_id: Session identifier
        page: Page number (1-based)
        size: Page size
        include_answers: Include answer data in response
        
    Returns:
        QuestionHistoryResponse: Session question history
    """
    try:
        # Filter questions by session
        session_questions = []
        
        for question_data in _questions.values():
            if question_data['session_id'] != session_id:
                continue
            
            question_info = {
                'question_id': question_data['question_id'],
                'question': question_data['question'],
                'status': question_data['status'],
                'submitted_at': question_data['submitted_at'].isoformat(),
                'updated_at': question_data['updated_at'].isoformat(),
                'context': question_data['context']
            }
            
            # Include answer if requested and available
            if include_answers and question_data['question_id'] in _answers:
                answer_data = _answers[question_data['question_id']]
                question_info['answer'] = {
                    'text': answer_data['answer'],
                    'sources_count': len(answer_data['sources']),
                    'confidence_score': answer_data['confidence_score'],
                    'generated_at': answer_data['generated_at'].isoformat(),
                    'processing_time': answer_data['processing_time']
                }
            
            session_questions.append(question_info)
        
        # Sort by submission time (newest first)
        session_questions.sort(key=lambda q: q['submitted_at'], reverse=True)
        
        # Paginate
        total = len(session_questions)
        start_idx = (page - 1) * size
        end_idx = start_idx + size
        page_questions = session_questions[start_idx:end_idx]
        
        return QuestionHistoryResponse(
            session_id=session_id,
            questions=page_questions,
            total=total,
            page=page,
            size=size
        )
        
    except Exception as e:
        logger.error(f"Failed to get history for session {session_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"History retrieval failed: {str(e)}"
        )


@router.get("/stats")
async def get_question_stats():
    """
    Get question processing statistics
    
    Returns:
        Dict[str, Any]: Question processing statistics
    """
    try:
        stats = {
            'total_questions': len(_questions),
            'total_answers': len(_answers),
            'by_status': {},
            'average_processing_time': 0,
            'active_sessions': set()
        }
        
        processing_times = []
        
        for question_data in _questions.values():
            # Count by status
            status_key = question_data['status']
            stats['by_status'][status_key] = stats['by_status'].get(status_key, 0) + 1
            
            # Track active sessions
            stats['active_sessions'].add(question_data['session_id'])
            
            # Calculate processing times for answered questions
            if (question_data['status'] == 'answered' and 
                question_data['answered_at'] and 
                question_data['submitted_at']):
                processing_time = (question_data['answered_at'] - question_data['submitted_at']).total_seconds()
                processing_times.append(processing_time)
        
        stats['active_sessions_count'] = len(stats['active_sessions'])
        stats.pop('active_sessions')  # Remove set (not JSON serializable)
        
        if processing_times:
            stats['average_processing_time'] = sum(processing_times) / len(processing_times)
        
        # Calculate answer rate
        if stats['total_questions'] > 0:
            stats['answer_rate'] = stats['total_answers'] / stats['total_questions']
        else:
            stats['answer_rate'] = 0
        
        return stats
        
    except Exception as e:
        logger.error(f"Failed to get question stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Stats collection failed: {str(e)}"
        )