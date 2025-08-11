"""
Question Manager

Handles question processing, validation, job management, and NATS publishing
for the RAG system's Q&A pipeline.
"""

import asyncio
import logging
import json
import uuid
import re
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from dataclasses import dataclass, field

import nats
from nats.aio.client import Client as NATS
from nats.js.api import PubAck

from .config import get_config


@dataclass
class QuestionJob:
    """Question processing job data model"""
    question_id: str
    question: str
    session_id: str
    submitted_at: datetime = field(default_factory=datetime.now)
    status: str = "queued"
    context: Dict[str, Any] = field(default_factory=dict)
    priority: str = "normal"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary for serialization"""
        return {
            'question_id': self.question_id,
            'question': self.question,
            'session_id': self.session_id,
            'submitted_at': self.submitted_at.isoformat(),
            'status': self.status,
            'context': self.context,
            'priority': self.priority
        }


class QuestionValidationError(Exception):
    """Exception raised when question validation fails"""
    pass


class QuestionPublishError(Exception):
    """Exception raised when question publishing fails"""
    pass


class QuestionManagerError(Exception):
    """Base exception for question manager errors"""
    pass


class QuestionManager:
    """
    Manager for question processing and job management.
    
    Handles question validation, job creation, and NATS publishing for
    question processing requests.
    """
    
    def __init__(self):
        """Initialize question manager"""
        self.config = get_config()
        self.logger = logging.getLogger("question.manager")
        
        # NATS client
        self.nats_client: Optional[NATS] = None
        self._connected = False
        self._connection_lock = asyncio.Lock()
        
        # Configuration
        self.min_question_length = 5
        self.max_question_length = 1000
        self.valid_priorities = ['low', 'normal', 'high']
        
        self.logger.info("Question manager initialized")
    
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
                self.logger.info("Connecting to NATS for question publishing...")
                
                # Connect to NATS
                self.nats_client = await nats.connect(
                    servers=self.config.nats_servers,
                    max_reconnect_attempts=self.config.max_reconnect_attempts,
                    reconnect_time_wait=self.config.reconnect_time_wait,
                    ping_interval=self.config.ping_interval,
                    max_outstanding_pings=self.config.max_outstanding_pings
                )
                
                self._connected = True
                self.logger.info("Question manager connected to NATS")
                return True
                
            except Exception as e:
                self.logger.error(f"Failed to connect question manager: {e}")
                self._connected = False
                return False
    
    async def disconnect(self):
        """Disconnect from NATS and cleanup"""
        try:
            if self.nats_client and not self.nats_client.is_closed:
                await self.nats_client.close()
            
            self._connected = False
            self.nats_client = None
            
            self.logger.info("Question manager disconnected")
            
        except Exception as e:
            self.logger.error(f"Error disconnecting question manager: {e}")
    
    async def _ensure_connected(self):
        """Ensure NATS connection is established"""
        if not self._connected:
            success = await self.connect()
            if not success:
                raise QuestionManagerError("Failed to connect to NATS")
    
    def validate_question(self, question: str) -> Tuple[bool, str]:
        """
        Validate question text with content checks
        
        Args:
            question: Question text to validate
            
        Returns:
            Tuple[bool, str]: (is_valid, error_message)
        """
        try:
            # Basic validation
            if not question or not isinstance(question, str):
                return False, "Question is required and must be a string"
            
            question = question.strip()
            if not question:
                return False, "Question cannot be empty"
            
            # Length validation
            if len(question) < self.min_question_length:
                return False, f"Question too short (minimum {self.min_question_length} characters)"
            
            if len(question) > self.max_question_length:
                return False, f"Question too long (maximum {self.max_question_length} characters)"
            
            # Content validation - must end with question mark or be a clear question
            question_words = ['como', 'quando', 'onde', 'por que', 'porque', 'qual', 'quais', 'quem', 'o que', 'que']
            has_question_mark = question.endswith('?')
            starts_with_question_word = any(question.lower().startswith(word) for word in question_words)
            
            if not has_question_mark and not starts_with_question_word:
                return False, "Text should be formatted as a question (end with '?' or start with question word)"
            
            # Check for suspicious patterns
            suspicious_patterns = [
                r'[<>\"\'&]',  # HTML/JS injection chars
                r'javascript:',  # JavaScript protocol
                r'<script',  # Script tags
                r'eval\(',  # Eval calls
            ]
            
            for pattern in suspicious_patterns:
                if re.search(pattern, question, re.IGNORECASE):
                    return False, f"Question contains invalid characters or patterns"
            
            return True, ""
            
        except Exception as e:
            self.logger.error(f"Question validation error: {e}")
            return False, f"Question validation failed: {str(e)}"
    
    def create_job(
        self, 
        question: str, 
        session_id: str,
        context: Optional[Dict[str, Any]] = None,
        priority: str = "normal"
    ) -> QuestionJob:
        """
        Create a question processing job
        
        Args:
            question: Question text
            session_id: Session ID
            context: Optional question context
            priority: Question priority
            
        Returns:
            QuestionJob: Created job object
        """
        try:
            question_id = str(uuid.uuid4())
            
            # Validate priority
            if priority not in self.valid_priorities:
                priority = "normal"
            
            job = QuestionJob(
                question_id=question_id,
                question=question,
                session_id=session_id,
                context=context or {},
                priority=priority,
                status="queued",
                submitted_at=datetime.now()
            )
            
            self.logger.info(f"Created question job {question_id} for session: {session_id}")
            return job
            
        except Exception as e:
            self.logger.error(f"Job creation failed: {e}")
            raise QuestionManagerError(f"Job creation failed: {e}")
    
    async def publish_job(self, job: QuestionJob) -> bool:
        """
        Publish job to NATS for processing
        
        Args:
            job: Question job to publish
            
        Returns:
            bool: True if published successfully
            
        Raises:
            QuestionPublishError: If publishing fails
        """
        try:
            await self._ensure_connected()
            
            # Get JetStream context
            js = self.nats_client.jetstream()
            
            # Prepare message
            message_data = {
                'question_id': job.question_id,
                'question': job.question,
                'session_id': job.session_id,
                'context': job.context,
                'priority': job.priority,
                'submitted_at': job.submitted_at.isoformat()
            }
            
            # Publish to questions topic
            topic_name = self.config.questions_topic
            ack: PubAck = await js.publish(
                topic_name,
                json.dumps(message_data).encode(),
                headers={'question_id': job.question_id, 'session_id': job.session_id}
            )
            
            self.logger.info(f"Published question {job.question_id} to NATS (seq: {ack.seq})")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to publish question {job.question_id}: {e}")
            raise QuestionPublishError(f"Question publishing failed: {e}")
    
    async def submit_question(
        self, 
        question: str,
        session_id: str,
        context: Optional[Dict[str, Any]] = None,
        priority: str = "normal"
    ) -> QuestionJob:
        """
        Complete question submission pipeline
        
        Args:
            question: Question text to process
            session_id: Session ID
            context: Optional question context
            priority: Question priority
            
        Returns:
            QuestionJob: Created and published job
            
        Raises:
            QuestionValidationError: If question validation fails
            QuestionManagerError: If submission fails
        """
        try:
            # Step 1: Validate question
            is_valid, error_msg = self.validate_question(question)
            if not is_valid:
                raise QuestionValidationError(f"Question validation failed: {error_msg}")
            
            # Step 2: Create job
            job = self.create_job(
                question=question,
                session_id=session_id,
                context=context,
                priority=priority
            )
            
            # Step 3: Publish job
            await self.publish_job(job)
            
            return job
            
        except (QuestionValidationError, QuestionPublishError):
            raise
        except Exception as e:
            self.logger.error(f"Question submission failed: {e}")
            raise QuestionManagerError(f"Question submission failed: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get question manager statistics
        
        Returns:
            Dict[str, Any]: Statistics
        """
        return {
            'connected': self._connected,
            'min_question_length': self.min_question_length,
            'max_question_length': self.max_question_length,
            'valid_priorities': self.valid_priorities,
            'nats_connected': self._connected and self.nats_client and not self.nats_client.is_closed
        }


# Global question manager instance
_question_manager: Optional[QuestionManager] = None


def get_question_manager() -> QuestionManager:
    """Get global question manager instance"""
    global _question_manager
    if _question_manager is None:
        _question_manager = QuestionManager()
    return _question_manager