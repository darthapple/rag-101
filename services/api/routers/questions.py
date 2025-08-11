"""
Questions Router - Simplified

Handles question submission to NATS for processing with session validation
"""

import json
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import nats
from nats.js import JetStreamContext

from simple_config import get_config

# Request/Response models
class QuestionRequest(BaseModel):
    """Simple question submission request"""
    question: str
    session_id: str
    
    def validate_question(self) -> bool:
        """Basic question validation"""
        return bool(self.question and self.question.strip())

class QuestionResponse(BaseModel):
    """Response after submitting question"""
    question_id: str
    session_id: str
    status: str = "submitted"
    message: str = "Question sent for processing"

router = APIRouter()
config = get_config()

# Global NATS client and JetStream context
_nats_client = None
_js_context = None

async def get_nats():
    """Get or create NATS connection with JetStream"""
    global _nats_client, _js_context
    if not _nats_client:
        _nats_client = await nats.connect(config.nats_url)
        _js_context = _nats_client.jetstream()
    return _nats_client, _js_context

async def validate_session(session_id: str, js: JetStreamContext) -> bool:
    """Check if session exists in NATS KV store"""
    try:
        # Get the sessions KV bucket
        kv = await js.key_value(bucket="sessions")
        
        # Try to get the session data
        entry = await kv.get(session_id)
        
        # If we got here, session exists
        return entry is not None
    except Exception as e:
        print(f"Session validation error: {e}")
        return False

@router.post("/", response_model=QuestionResponse)
async def submit_question(request: QuestionRequest):
    """
    Submit a question for processing via NATS
    
    Validates session exists, then sends the question and session_id 
    to the chat.questions topic. Workers will process it and send answers 
    to chat.answers.{session_id}
    """
    try:
        # Validate question is not empty
        if not request.validate_question():
            raise HTTPException(
                status_code=400,
                detail="Question cannot be empty"
            )
        
        # Get NATS connection and JetStream context
        nc, js = await get_nats()
        
        # Validate session exists
        if not await validate_session(request.session_id, js):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid session ID: {request.session_id}"
            )
        
        # Generate question ID
        question_id = str(uuid.uuid4())
        
        # Create message payload
        message = {
            "question_id": question_id,
            "question": request.question,
            "session_id": request.session_id,
            "timestamp": datetime.now().isoformat()
        }
        
        # Publish to chat.questions topic
        await nc.publish("chat.questions", json.dumps(message).encode())
        
        print(f"Published question {question_id} for session {request.session_id}")
        
        return QuestionResponse(
            question_id=question_id,
            session_id=request.session_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error submitting question: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to submit question: {str(e)}"
        )

