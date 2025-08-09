import json
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional, Dict, Any, Union
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, HttpUrl, validator, root_validator


class SessionStatus(str, Enum):
    """Session status enumeration"""
    ACTIVE = "active"
    EXPIRED = "expired"
    TERMINATED = "terminated"


class SessionCreate(BaseModel):
    """Model for creating a new session"""
    nickname: str = Field(
        ..., 
        min_length=1, 
        max_length=50,
        description="User's display name for the session"
    )
    ttl_seconds: Optional[int] = Field(
        3600,
        ge=60,
        le=86400,
        description="Session TTL in seconds (1 minute to 24 hours)"
    )
    
    @validator('nickname')
    def validate_nickname(cls, v):
        """Validate nickname format"""
        if not v or not v.strip():
            raise ValueError("Nickname cannot be empty")
        # Remove excessive whitespace
        v = v.strip()
        # Basic sanitization
        if any(char in v for char in ['<', '>', '"', "'"]):
            raise ValueError("Nickname contains invalid characters")
        return v


class Session(BaseModel):
    """Core session model"""
    session_id: UUID = Field(default_factory=uuid4, description="Unique session identifier")
    nickname: str = Field(..., description="User's display name")
    created_at: datetime = Field(default_factory=datetime.now, description="Session creation timestamp")
    expires_at: datetime = Field(..., description="Session expiration timestamp")
    status: SessionStatus = Field(default=SessionStatus.ACTIVE, description="Current session status")
    last_activity: Optional[datetime] = Field(None, description="Last activity timestamp")
    
    @root_validator
    def validate_expiration(cls, values):
        """Ensure expires_at is after created_at"""
        created_at = values.get('created_at')
        expires_at = values.get('expires_at')
        
        if created_at and expires_at and expires_at <= created_at:
            raise ValueError("Session expiration must be after creation time")
        
        return values
    
    @classmethod
    def create_session(cls, nickname: str, ttl_seconds: int = 3600) -> 'Session':
        """Create a new session with automatic expiration calculation"""
        now = datetime.now()
        expires_at = now + timedelta(seconds=ttl_seconds)
        
        return cls(
            nickname=nickname,
            created_at=now,
            expires_at=expires_at,
            status=SessionStatus.ACTIVE
        )
    
    def is_expired(self) -> bool:
        """Check if session has expired"""
        return datetime.now() >= self.expires_at
    
    def extend_session(self, additional_seconds: int = 3600) -> None:
        """Extend session expiration time"""
        self.expires_at = datetime.now() + timedelta(seconds=additional_seconds)
        self.last_activity = datetime.now()
    
    def update_activity(self) -> None:
        """Update last activity timestamp"""
        self.last_activity = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            'session_id': str(self.session_id),
            'nickname': self.nickname,
            'created_at': self.created_at.isoformat(),
            'expires_at': self.expires_at.isoformat(),
            'status': self.status.value,
            'last_activity': self.last_activity.isoformat() if self.last_activity else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Session':
        """Create session from dictionary"""
        return cls(
            session_id=UUID(data['session_id']),
            nickname=data['nickname'],
            created_at=datetime.fromisoformat(data['created_at']),
            expires_at=datetime.fromisoformat(data['expires_at']),
            status=SessionStatus(data['status']),
            last_activity=datetime.fromisoformat(data['last_activity']) if data.get('last_activity') else None
        )


class SessionResponse(BaseModel):
    """Response model for session operations"""
    session_id: UUID = Field(..., description="Session identifier")
    nickname: str = Field(..., description="User's display name")
    status: SessionStatus = Field(..., description="Session status")
    created_at: datetime = Field(..., description="Creation timestamp")
    expires_at: datetime = Field(..., description="Expiration timestamp")
    time_remaining: Optional[int] = Field(None, description="Seconds until expiration")
    
    @root_validator
    def calculate_time_remaining(cls, values):
        """Calculate remaining time for active sessions"""
        expires_at = values.get('expires_at')
        status = values.get('status')
        
        if expires_at and status == SessionStatus.ACTIVE:
            remaining = expires_at - datetime.now()
            values['time_remaining'] = max(0, int(remaining.total_seconds()))
        
        return values


class SessionListResponse(BaseModel):
    """Response model for listing sessions"""
    sessions: List[SessionResponse] = Field(default_factory=list, description="List of sessions")
    total_count: int = Field(..., description="Total number of sessions")
    active_count: int = Field(..., description="Number of active sessions")
    expired_count: int = Field(..., description="Number of expired sessions")


class SessionUpdate(BaseModel):
    """Model for updating session properties"""
    nickname: Optional[str] = Field(None, min_length=1, max_length=50)
    extend_seconds: Optional[int] = Field(None, ge=60, le=86400)
    status: Optional[SessionStatus] = Field(None)
    
    @validator('nickname')
    def validate_nickname(cls, v):
        """Validate nickname format if provided"""
        if v is not None:
            if not v or not v.strip():
                raise ValueError("Nickname cannot be empty")
            # Remove excessive whitespace
            v = v.strip()
            # Basic sanitization
            if any(char in v for char in ['<', '>', '"', "'"]):
                raise ValueError("Nickname contains invalid characters")
        return v


# Document and Processing Models
class DocumentStatus(str, Enum):
    """Document processing status enumeration"""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    EMBEDDING = "embedding"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DocumentDownloadRequest(BaseModel):
    """Request model for document download and processing"""
    url: HttpUrl = Field(..., description="URL of the document to download")
    job_id: Optional[UUID] = Field(default_factory=uuid4, description="Processing job identifier")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional metadata")
    
    @validator('url')
    def validate_url(cls, v):
        """Validate document URL"""
        url_str = str(v)
        # Basic URL validation for supported formats
        if not any(url_str.lower().endswith(ext) for ext in ['.pdf', '.doc', '.docx', '.txt']):
            # Allow URLs without explicit extensions (might be dynamic)
            pass
        return v


class Document(BaseModel):
    """Core document model"""
    job_id: UUID = Field(..., description="Processing job identifier")
    url: HttpUrl = Field(..., description="Source URL of the document")
    title: Optional[str] = Field(None, max_length=500, description="Document title")
    status: DocumentStatus = Field(default=DocumentStatus.PENDING, description="Processing status")
    file_size: Optional[int] = Field(None, ge=0, description="File size in bytes")
    content_type: Optional[str] = Field(None, description="MIME type of the document")
    page_count: Optional[int] = Field(None, ge=0, description="Number of pages")
    created_at: datetime = Field(default_factory=datetime.now, description="Creation timestamp")
    processed_at: Optional[datetime] = Field(None, description="Processing completion timestamp")
    error_message: Optional[str] = Field(None, description="Error message if processing failed")
    chunk_count: Optional[int] = Field(None, ge=0, description="Number of chunks generated")
    
    def mark_processing(self) -> None:
        """Mark document as being processed"""
        self.status = DocumentStatus.PROCESSING
    
    def mark_completed(self, chunk_count: int = 0) -> None:
        """Mark document as completed"""
        self.status = DocumentStatus.COMPLETED
        self.processed_at = datetime.now()
        self.chunk_count = chunk_count
    
    def mark_failed(self, error: str) -> None:
        """Mark document as failed"""
        self.status = DocumentStatus.FAILED
        self.error_message = error
        self.processed_at = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            'job_id': str(self.job_id),
            'url': str(self.url),
            'title': self.title,
            'status': self.status.value,
            'file_size': self.file_size,
            'content_type': self.content_type,
            'page_count': self.page_count,
            'created_at': self.created_at.isoformat(),
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
            'error_message': self.error_message,
            'chunk_count': self.chunk_count
        }


class DocumentChunk(BaseModel):
    """Model for document chunks stored in vector database"""
    chunk_id: str = Field(..., max_length=128, description="Unique chunk identifier")
    text_content: str = Field(..., max_length=4000, description="Text content of the chunk")
    document_title: str = Field(..., max_length=500, description="Title of source document")
    source_url: HttpUrl = Field(..., description="URL of source document")
    page_number: int = Field(..., ge=1, description="Page number in source document")
    diseases: List[str] = Field(default_factory=list, description="Related diseases/conditions")
    processed_at: datetime = Field(default_factory=datetime.now, description="Processing timestamp")
    job_id: str = Field(..., max_length=100, description="Processing job identifier")
    embedding: Optional[List[float]] = Field(None, description="Vector embedding (768 dimensions)")
    
    @validator('diseases')
    def validate_diseases(cls, v):
        """Validate diseases list"""
        if v:
            # Remove empty strings and duplicates
            v = list(set(disease.strip() for disease in v if disease.strip()))
            # Limit number of diseases
            if len(v) > 20:
                v = v[:20]
        return v
    
    @validator('embedding')
    def validate_embedding(cls, v):
        """Validate embedding dimensions"""
        if v is not None:
            if len(v) != 768:
                raise ValueError("Embedding must have exactly 768 dimensions")
        return v
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for vector storage"""
        return {
            'chunk_id': self.chunk_id,
            'embedding': self.embedding,
            'text_content': self.text_content,
            'document_title': self.document_title,
            'source_url': str(self.source_url),
            'page_number': self.page_number,
            'diseases': json.dumps(self.diseases) if self.diseases else "[]",
            'processed_at': self.processed_at.isoformat(),
            'job_id': self.job_id
        }


class DocumentProcessingStatus(BaseModel):
    """Status response for document processing"""
    job_id: UUID = Field(..., description="Processing job identifier")
    status: DocumentStatus = Field(..., description="Current processing status")
    progress: float = Field(0.0, ge=0.0, le=1.0, description="Processing progress (0.0 to 1.0)")
    message: Optional[str] = Field(None, description="Status message")
    created_at: datetime = Field(..., description="Job creation timestamp")
    updated_at: datetime = Field(default_factory=datetime.now, description="Last update timestamp")
    estimated_completion: Optional[datetime] = Field(None, description="Estimated completion time")
    
    def update_progress(self, progress: float, message: str = None) -> None:
        """Update processing progress"""
        self.progress = max(0.0, min(1.0, progress))
        self.updated_at = datetime.now()
        if message:
            self.message = message


class DocumentListResponse(BaseModel):
    """Response model for listing documents"""
    documents: List[Document] = Field(default_factory=list, description="List of documents")
    total_count: int = Field(..., description="Total number of documents")
    status_counts: Dict[str, int] = Field(default_factory=dict, description="Count by status")


class EmbeddingRequest(BaseModel):
    """Request model for generating embeddings"""
    chunks: List[DocumentChunk] = Field(..., description="Chunks to embed")
    job_id: UUID = Field(..., description="Processing job identifier")
    model: str = Field("text-embedding-004", description="Embedding model to use")
    
    @validator('chunks')
    def validate_chunks(cls, v):
        """Validate chunks list"""
        if not v:
            raise ValueError("At least one chunk is required")
        if len(v) > 100:
            raise ValueError("Maximum 100 chunks per request")
        return v


class EmbeddingResponse(BaseModel):
    """Response model for embedding generation"""
    job_id: UUID = Field(..., description="Processing job identifier")
    chunk_count: int = Field(..., description="Number of chunks processed")
    success_count: int = Field(..., description="Number of successful embeddings")
    error_count: int = Field(..., description="Number of failed embeddings")
    processing_time: float = Field(..., description="Total processing time in seconds")
    errors: List[str] = Field(default_factory=list, description="List of error messages")


# Question and Answer Models
class QuestionRequest(BaseModel):
    """Request model for asking questions"""
    session_id: UUID = Field(..., description="Session identifier")
    question: str = Field(..., min_length=1, max_length=2000, description="Question text")
    context: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional context")
    
    @validator('question')
    def validate_question(cls, v):
        """Validate question format"""
        if not v or not v.strip():
            raise ValueError("Question cannot be empty")
        return v.strip()


class Question(BaseModel):
    """Core question model"""
    message_id: UUID = Field(default_factory=uuid4, description="Unique message identifier")
    session_id: UUID = Field(..., description="Session identifier")
    question: str = Field(..., description="Question text")
    submitted_at: datetime = Field(default_factory=datetime.now, description="Submission timestamp")
    context: Dict[str, Any] = Field(default_factory=dict, description="Additional context")
    processing_status: Optional[str] = Field(None, description="Processing status")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for messaging"""
        return {
            'message_id': str(self.message_id),
            'session_id': str(self.session_id),
            'question': self.question,
            'submitted_at': self.submitted_at.isoformat(),
            'context': self.context,
            'processing_status': self.processing_status
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Question':
        """Create question from dictionary"""
        return cls(
            message_id=UUID(data['message_id']),
            session_id=UUID(data['session_id']),
            question=data['question'],
            submitted_at=datetime.fromisoformat(data['submitted_at']),
            context=data.get('context', {}),
            processing_status=data.get('processing_status')
        )


class AnswerSource(BaseModel):
    """Model for answer source attribution"""
    chunk_id: str = Field(..., description="Source chunk identifier")
    document_title: str = Field(..., description="Source document title")
    source_url: HttpUrl = Field(..., description="Source document URL")
    page_number: int = Field(..., ge=1, description="Page number")
    relevance_score: float = Field(..., ge=0.0, le=1.0, description="Relevance score (0.0 to 1.0)")
    excerpt: str = Field(..., max_length=500, description="Relevant text excerpt")
    diseases: List[str] = Field(default_factory=list, description="Related diseases")
    
    @validator('excerpt')
    def validate_excerpt(cls, v):
        """Validate and clean excerpt"""
        if v:
            v = v.strip()
            # Remove excessive whitespace
            v = ' '.join(v.split())
        return v


class Answer(BaseModel):
    """Core answer model"""
    message_id: UUID = Field(default_factory=uuid4, description="Unique message identifier")
    session_id: UUID = Field(..., description="Session identifier")
    question_id: Optional[UUID] = Field(None, description="Related question identifier")
    answer: str = Field(..., description="Answer text")
    sources: List[AnswerSource] = Field(default_factory=list, description="Source documents")
    generated_at: datetime = Field(default_factory=datetime.now, description="Generation timestamp")
    confidence_score: Optional[float] = Field(None, ge=0.0, le=1.0, description="Confidence score")
    model_used: Optional[str] = Field(None, description="AI model used for generation")
    processing_time: Optional[float] = Field(None, ge=0.0, description="Processing time in seconds")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    @validator('answer')
    def validate_answer(cls, v):
        """Validate answer format"""
        if not v or not v.strip():
            raise ValueError("Answer cannot be empty")
        return v.strip()
    
    @validator('sources')
    def validate_sources(cls, v):
        """Validate sources list"""
        if len(v) > 20:
            # Limit to top 20 sources
            v = v[:20]
        return v
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for messaging"""
        return {
            'message_id': str(self.message_id),
            'session_id': str(self.session_id),
            'question_id': str(self.question_id) if self.question_id else None,
            'answer': self.answer,
            'sources': [source.dict() for source in self.sources],
            'generated_at': self.generated_at.isoformat(),
            'confidence_score': self.confidence_score,
            'model_used': self.model_used,
            'processing_time': self.processing_time,
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Answer':
        """Create answer from dictionary"""
        return cls(
            message_id=UUID(data['message_id']),
            session_id=UUID(data['session_id']),
            question_id=UUID(data['question_id']) if data.get('question_id') else None,
            answer=data['answer'],
            sources=[AnswerSource(**source) for source in data.get('sources', [])],
            generated_at=datetime.fromisoformat(data['generated_at']),
            confidence_score=data.get('confidence_score'),
            model_used=data.get('model_used'),
            processing_time=data.get('processing_time'),
            metadata=data.get('metadata', {})
        )


class AnswerResponse(BaseModel):
    """Response model for answers"""
    message_id: UUID = Field(..., description="Message identifier")
    session_id: UUID = Field(..., description="Session identifier")
    answer: str = Field(..., description="Answer text")
    sources: List[AnswerSource] = Field(default_factory=list, description="Source documents")
    confidence_score: Optional[float] = Field(None, description="Confidence score")
    generated_at: datetime = Field(..., description="Generation timestamp")
    source_count: int = Field(..., description="Number of source documents")
    processing_time: Optional[float] = Field(None, description="Processing time in seconds")


class QuestionAnswerPair(BaseModel):
    """Model for question-answer pairs"""
    question: Question = Field(..., description="Question data")
    answer: Optional[Answer] = Field(None, description="Answer data (if available)")
    status: str = Field("pending", description="Processing status")
    
    @validator('status')
    def validate_status(cls, v):
        """Validate status values"""
        valid_statuses = ["pending", "processing", "completed", "failed"]
        if v not in valid_statuses:
            raise ValueError(f"Status must be one of: {', '.join(valid_statuses)}")
        return v


class ConversationHistory(BaseModel):
    """Model for session conversation history"""
    session_id: UUID = Field(..., description="Session identifier")
    pairs: List[QuestionAnswerPair] = Field(default_factory=list, description="Q&A pairs")
    total_questions: int = Field(0, description="Total number of questions")
    total_answers: int = Field(0, description="Total number of answers")
    last_activity: Optional[datetime] = Field(None, description="Last activity timestamp")
    
    def add_question(self, question: Question) -> None:
        """Add a new question to conversation"""
        pair = QuestionAnswerPair(question=question)
        self.pairs.append(pair)
        self.total_questions += 1
        self.last_activity = datetime.now()
    
    def add_answer(self, answer: Answer) -> bool:
        """Add answer to the most recent question"""
        # Find the most recent question without an answer
        for pair in reversed(self.pairs):
            if pair.answer is None and pair.question.session_id == answer.session_id:
                pair.answer = answer
                pair.status = "completed"
                self.total_answers += 1
                self.last_activity = datetime.now()
                return True
        return False
    
    def get_recent_context(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get recent conversation context"""
        context = []
        recent_pairs = self.pairs[-limit:] if len(self.pairs) > limit else self.pairs
        
        for pair in recent_pairs:
            context.append({
                'question': pair.question.question,
                'answer': pair.answer.answer if pair.answer else None,
                'timestamp': pair.question.submitted_at.isoformat()
            })
        
        return context


# Validation Utilities and Base Configurations
class APIError(BaseModel):
    """API error response model"""
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")
    timestamp: datetime = Field(default_factory=datetime.now, description="Error timestamp")
    
    class Config:
        """Pydantic configuration"""
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class HealthCheck(BaseModel):
    """Health check response model"""
    status: str = Field(..., description="Health status")
    timestamp: datetime = Field(default_factory=datetime.now, description="Check timestamp")
    version: Optional[str] = Field(None, description="Service version")
    uptime: Optional[float] = Field(None, description="Uptime in seconds")
    dependencies: Dict[str, str] = Field(default_factory=dict, description="Dependency status")
    
    class Config:
        """Pydantic configuration"""
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


# Custom Validators
def validate_session_id(session_id: str) -> UUID:
    """Validate and convert session ID to UUID"""
    try:
        return UUID(session_id)
    except ValueError:
        raise ValueError("Invalid session ID format")


def validate_message_id(message_id: str) -> UUID:
    """Validate and convert message ID to UUID"""
    try:
        return UUID(message_id)
    except ValueError:
        raise ValueError("Invalid message ID format")


def validate_job_id(job_id: str) -> UUID:
    """Validate and convert job ID to UUID"""
    try:
        return UUID(job_id)
    except ValueError:
        raise ValueError("Invalid job ID format")


# Serialization Utilities
def serialize_for_nats(obj: Union[BaseModel, Dict[str, Any]]) -> bytes:
    """Serialize object for NATS messaging"""
    if isinstance(obj, BaseModel):
        data = obj.dict()
    else:
        data = obj
    
    # Convert UUIDs and datetimes to strings
    def convert_values(item):
        if isinstance(item, dict):
            return {k: convert_values(v) for k, v in item.items()}
        elif isinstance(item, list):
            return [convert_values(v) for v in item]
        elif isinstance(item, UUID):
            return str(item)
        elif isinstance(item, datetime):
            return item.isoformat()
        else:
            return item
    
    converted_data = convert_values(data)
    return json.dumps(converted_data, default=str).encode('utf-8')


def deserialize_from_nats(data: bytes, model_class: type) -> BaseModel:
    """Deserialize NATS message to Pydantic model"""
    try:
        json_data = json.loads(data.decode('utf-8'))
        return model_class(**json_data)
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"Failed to deserialize message: {str(e)}")


# Base Model Configuration
class BaseConfig:
    """Base configuration for all Pydantic models"""
    # JSON encoding for datetime and UUID
    json_encoders = {
        datetime: lambda v: v.isoformat(),
        UUID: lambda v: str(v)
    }
    
    # Allow population by field name or alias
    allow_population_by_field_name = True
    
    # Validate assignment
    validate_assignment = True
    
    # Use enum values
    use_enum_values = True
    
    # Extra fields behavior
    extra = 'forbid'


# Model Factory Functions
def create_session_from_request(request: SessionCreate) -> Session:
    """Create session from session create request"""
    return Session.create_session(
        nickname=request.nickname,
        ttl_seconds=request.ttl_seconds or 3600
    )


def create_question_from_request(request: QuestionRequest) -> Question:
    """Create question from question request"""
    return Question(
        session_id=request.session_id,
        question=request.question,
        context=request.context
    )


def create_document_from_request(request: DocumentDownloadRequest) -> Document:
    """Create document from download request"""
    return Document(
        job_id=request.job_id,
        url=request.url,
        status=DocumentStatus.PENDING
    )


# Response Builders
def build_session_response(session: Session) -> SessionResponse:
    """Build session response from session model"""
    return SessionResponse(
        session_id=session.session_id,
        nickname=session.nickname,
        status=session.status,
        created_at=session.created_at,
        expires_at=session.expires_at
    )


def build_answer_response(answer: Answer) -> AnswerResponse:
    """Build answer response from answer model"""
    return AnswerResponse(
        message_id=answer.message_id,
        session_id=answer.session_id,
        answer=answer.answer,
        sources=answer.sources,
        confidence_score=answer.confidence_score,
        generated_at=answer.generated_at,
        source_count=len(answer.sources),
        processing_time=answer.processing_time
    )


# Validation Helpers
def is_valid_uuid(uuid_string: str) -> bool:
    """Check if string is a valid UUID"""
    try:
        UUID(uuid_string)
        return True
    except ValueError:
        return False


def sanitize_text(text: str, max_length: int = None) -> str:
    """Sanitize and clean text input"""
    if not text:
        return ""
    
    # Strip whitespace
    text = text.strip()
    
    # Replace excessive whitespace
    text = ' '.join(text.split())
    
    # Remove or replace potentially harmful characters
    text = text.replace('\x00', '')  # Remove null bytes
    
    # Truncate if needed
    if max_length and len(text) > max_length:
        text = text[:max_length].rstrip()
    
    return text


# Model Collections
ALL_SESSION_MODELS = [
    SessionStatus, SessionCreate, Session, SessionResponse, 
    SessionListResponse, SessionUpdate
]

ALL_DOCUMENT_MODELS = [
    DocumentStatus, DocumentDownloadRequest, Document, DocumentChunk,
    DocumentProcessingStatus, DocumentListResponse, EmbeddingRequest, EmbeddingResponse
]

ALL_QA_MODELS = [
    QuestionRequest, Question, AnswerSource, Answer, AnswerResponse,
    QuestionAnswerPair, ConversationHistory
]

ALL_UTILITY_MODELS = [
    APIError, HealthCheck
]

ALL_MODELS = (
    ALL_SESSION_MODELS + 
    ALL_DOCUMENT_MODELS + 
    ALL_QA_MODELS + 
    ALL_UTILITY_MODELS
)