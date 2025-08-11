import os
import logging
from typing import List, Optional, Union
from pathlib import Path
from pydantic import Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings


logger = logging.getLogger(__name__)


class BaseConfig(BaseSettings):
    """
    Base configuration class with common settings and environment variable loading
    
    This class provides the foundation for all configuration classes in the application.
    It handles environment variable loading, .env file support, and common configuration patterns.
    """
    
    model_config = {
        # Load from .env file if present
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        
        # Allow case insensitive environment variables
        "case_sensitive": False,
        
        # Enable environment variable expansion
        "env_nested_delimiter": "__",
        
        # Validate assignment when values are changed
        "validate_assignment": True,
        
        # Allow extra fields but don't include them in the dict
        "extra": "ignore"
    }
    
    # Environment and deployment settings
    environment: str = Field(
        default="development",
        env="ENVIRONMENT",
        description="Deployment environment (development, staging, production)"
    )
    
    debug: bool = Field(
        default=False,
        env="DEBUG", 
        description="Enable debug mode"
    )
    
    log_level: str = Field(
        default="INFO",
        env="LOG_LEVEL",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )
    
    @field_validator('environment')
    @classmethod
    def validate_environment(cls, v):
        """Validate environment values"""
        valid_environments = ['development', 'staging', 'production', 'testing']
        if v.lower() not in valid_environments:
            logger.warning(f"Unknown environment '{v}', using 'development'")
            return 'development'
        return v.lower()
    
    @field_validator('log_level')
    @classmethod
    def validate_log_level(cls, v):
        """Validate log level values"""
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if v.upper() not in valid_levels:
            logger.warning(f"Invalid log level '{v}', using 'INFO'")
            return 'INFO'
        return v.upper()
    
    def setup_logging(self) -> None:
        """Setup logging configuration based on config"""
        level = getattr(logging, self.log_level)
        
        # Configure root logger
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Set specific loggers to appropriate levels
        if self.environment == 'production':
            # Reduce noise in production
            logging.getLogger('urllib3').setLevel(logging.WARNING)
            logging.getLogger('requests').setLevel(logging.WARNING)
        elif self.debug:
            # Enable debug logging for our modules
            logging.getLogger('shared').setLevel(logging.DEBUG)
            logging.getLogger('services').setLevel(logging.DEBUG)
    
    def is_development(self) -> bool:
        """Check if running in development environment"""
        return self.environment == 'development'
    
    def is_production(self) -> bool:
        """Check if running in production environment"""
        return self.environment == 'production'
    
    def is_testing(self) -> bool:
        """Check if running in testing environment"""
        return self.environment == 'testing'


class HealthCheckConfig:
    """Health check and monitoring configuration"""
    
    # Health check settings
    health_check_interval: int = Field(
        default=30,
        env="HEALTH_CHECK_INTERVAL",
        ge=5,
        le=300,
        description="Health check interval in seconds"
    )
    
    startup_timeout: int = Field(
        default=60,
        env="STARTUP_TIMEOUT", 
        ge=10,
        le=600,
        description="Maximum time to wait for services to start"
    )
    
    # Service metadata
    service_name: str = Field(
        default="rag-service",
        env="SERVICE_NAME",
        description="Service name for identification"
    )
    
    service_version: str = Field(
        default="1.0.0",
        env="SERVICE_VERSION",
        description="Service version"
    )


def load_dotenv_file(dotenv_path: Union[str, Path] = None) -> bool:
    """
    Load environment variables from .env file
    
    Args:
        dotenv_path: Path to .env file (defaults to .env in current directory)
        
    Returns:
        bool: True if .env file was found and loaded
    """
    if dotenv_path is None:
        dotenv_path = Path.cwd() / ".env"
    else:
        dotenv_path = Path(dotenv_path)
    
    if not dotenv_path.exists():
        logger.debug(f"No .env file found at {dotenv_path}")
        return False
    
    try:
        with open(dotenv_path, 'r', encoding='utf-8') as file:
            for line in file:
                line = line.strip()
                
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue
                
                # Parse key=value pairs
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    
                    # Only set if not already in environment
                    if key and key not in os.environ:
                        os.environ[key] = value
        
        logger.info(f"Loaded environment variables from {dotenv_path}")
        return True
        
    except Exception as e:
        logger.error(f"Error loading .env file: {e}")
        return False


def get_project_root() -> Path:
    """
    Get the project root directory
    
    Returns:
        Path: Path to project root
    """
    # Start from this file's directory and go up until we find common project markers
    current_path = Path(__file__).parent
    
    # Look for common project root indicators
    root_indicators = [
        'pyproject.toml',
        'setup.py', 
        'requirements.txt',
        'docker-compose.yml',
        '.git',
        'CLAUDE.md'
    ]
    
    # Go up directories looking for project root
    while current_path != current_path.parent:
        if any((current_path / indicator).exists() for indicator in root_indicators):
            return current_path
        current_path = current_path.parent
    
    # Fallback to current working directory
    return Path.cwd()


def validate_required_env_vars(required_vars: List[str]) -> List[str]:
    """
    Validate that required environment variables are set
    
    Args:
        required_vars: List of required environment variable names
        
    Returns:
        List[str]: List of missing environment variables
    """
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {missing_vars}")
    
    return missing_vars


def get_env_list(env_var: str, default: List[str] = None, separator: str = ",") -> List[str]:
    """
    Get environment variable as list
    
    Args:
        env_var: Environment variable name
        default: Default list if variable not set
        separator: List item separator
        
    Returns:
        List[str]: List of values
    """
    if default is None:
        default = []
    
    value = os.getenv(env_var)
    if not value:
        return default
    
    return [item.strip() for item in value.split(separator) if item.strip()]


def get_env_bool(env_var: str, default: bool = False) -> bool:
    """
    Get environment variable as boolean
    
    Args:
        env_var: Environment variable name
        default: Default boolean value
        
    Returns:
        bool: Boolean value
    """
    value = os.getenv(env_var, '').lower()
    
    if value in ('true', '1', 'yes', 'on'):
        return True
    elif value in ('false', '0', 'no', 'off'):
        return False
    else:
        return default


def get_env_int(env_var: str, default: int = 0, min_val: int = None, max_val: int = None) -> int:
    """
    Get environment variable as integer with validation
    
    Args:
        env_var: Environment variable name
        default: Default integer value
        min_val: Minimum allowed value
        max_val: Maximum allowed value
        
    Returns:
        int: Integer value
    """
    try:
        value = int(os.getenv(env_var, str(default)))
        
        if min_val is not None and value < min_val:
            logger.warning(f"{env_var}={value} below minimum {min_val}, using {min_val}")
            return min_val
            
        if max_val is not None and value > max_val:
            logger.warning(f"{env_var}={value} above maximum {max_val}, using {max_val}")
            return max_val
            
        return value
        
    except ValueError:
        logger.warning(f"Invalid integer for {env_var}, using default {default}")
        return default


# Service-Specific Configuration Classes

class NATSConfig:
    """NATS messaging configuration"""
    
    # Connection settings
    nats_url: str = Field(
        default="nats://localhost:4222",
        env="NATS_URL",
        description="NATS server URL"
    )
    
    nats_servers: List[str] = Field(
        default_factory=lambda: ["nats://localhost:4222"],
        env="NATS_SERVERS",
        description="List of NATS server URLs for clustering"
    )
    
    # Connection parameters
    max_reconnect_attempts: int = Field(
        default=10,
        env="NATS_MAX_RECONNECT_ATTEMPTS",
        ge=1,
        le=100,
        description="Maximum reconnection attempts"
    )
    
    reconnect_time_wait: float = Field(
        default=2.0,
        env="NATS_RECONNECT_WAIT",
        ge=0.1,
        le=60.0,
        description="Time to wait between reconnection attempts"
    )
    
    ping_interval: float = Field(
        default=120.0,
        env="NATS_PING_INTERVAL",
        ge=10.0,
        le=600.0,
        description="Ping interval in seconds"
    )
    
    max_outstanding_pings: int = Field(
        default=2,
        env="NATS_MAX_OUTSTANDING_PINGS",
        ge=1,
        le=10,
        description="Maximum outstanding pings"
    )
    
    # TTL settings
    message_ttl: int = Field(
        default=3600,
        env="MESSAGE_TTL",
        ge=60,
        le=86400,
        description="Default message TTL in seconds"
    )
    
    session_ttl: int = Field(
        default=3600,
        env="SESSION_TTL", 
        ge=60,
        le=86400,
        description="Session TTL in seconds"
    )
    
    # Topic configuration
    topics_prefix: str = Field(
        default="",
        env="NATS_TOPICS_PREFIX",
        description="Prefix for all NATS topics"
    )
    
    # Core topic names (all lowercase)
    questions_topic: str = Field(
        default="questions",
        env="QUESTIONS_TOPIC",
        description="Questions topic name"
    )
    
    documents_download_topic: str = Field(
        default="documents.download",
        env="DOCUMENTS_DOWNLOAD_TOPIC", 
        description="Document download processing topic"
    )
    
    documents_chunks_topic: str = Field(
        default="documents.chunks",
        env="DOCUMENTS_CHUNKS_TOPIC",
        description="Document chunks processing topic"
    )
    
    documents_embeddings_topic: str = Field(
        default="documents.embeddings",
        env="DOCUMENTS_EMBEDDINGS_TOPIC",
        description="Document embeddings processing topic"
    )
    
    answers_topic_prefix: str = Field(
        default="answers",
        env="ANSWERS_TOPIC_PREFIX",
        description="Prefix for answer topics (answers.{session_id})"
    )
    
    system_metrics_topic: str = Field(
        default="system.metrics",
        env="SYSTEM_METRICS_TOPIC",
        description="System monitoring topic"
    )
    
    errors_topic_prefix: str = Field(
        default="errors",
        env="ERRORS_TOPIC_PREFIX",
        description="Error logging topic prefix"
    )
    
    @field_validator('nats_servers')
    @classmethod
    def validate_nats_servers(cls, v):
        """Validate NATS server URLs"""
        if isinstance(v, str):
            v = [server.strip() for server in v.split(',')]
        
        validated_servers = []
        for server in v:
            if not server.startswith(('nats://', 'tls://')):
                logger.warning(f"NATS server URL should start with nats:// or tls://, got: {server}")
                server = f"nats://{server}"
            validated_servers.append(server)
        
        return validated_servers
    
    @field_validator('questions_topic', 'documents_download_topic', 'documents_chunks_topic', 
                     'documents_embeddings_topic', 'answers_topic_prefix', 'system_metrics_topic', 'errors_topic_prefix')
    @classmethod
    def validate_topic_names(cls, v):
        """Ensure topic names are lowercase"""
        if v != v.lower():
            logger.warning(f"Topic name '{v}' should be lowercase, converting to '{v.lower()}'")
            return v.lower()
        return v


class MilvusConfig:
    """Milvus vector database configuration"""
    
    # Connection settings
    milvus_host: str = Field(
        default="localhost",
        env="MILVUS_HOST",
        description="Milvus server host"
    )
    
    milvus_port: int = Field(
        default=19530,
        env="MILVUS_PORT",
        ge=1,
        le=65535,
        description="Milvus server port"
    )
    
    milvus_alias: str = Field(
        default="default",
        env="MILVUS_ALIAS",
        description="Milvus connection alias"
    )
    
    # Collection settings
    collection_name: str = Field(
        default="medical_documents",
        env="MILVUS_COLLECTION_NAME",
        description="Name of the Milvus collection"
    )
    
    vector_dimension: int = Field(
        default=768,
        env="VECTOR_DIMENSION",
        ge=128,
        le=2048,
        description="Vector embedding dimension"
    )
    
    # Index settings
    index_type: str = Field(
        default="IVF_FLAT",
        env="MILVUS_INDEX_TYPE",
        description="Vector index type"
    )
    
    metric_type: str = Field(
        default="COSINE",
        env="MILVUS_METRIC_TYPE",
        description="Distance metric for similarity search"
    )
    
    nlist: int = Field(
        default=1024,
        env="MILVUS_NLIST",
        ge=1,
        le=65536,
        description="Number of cluster units for IVF index"
    )
    
    # Search settings
    search_nprobe: int = Field(
        default=16,
        env="MILVUS_SEARCH_NPROBE",
        ge=1,
        le=1024,
        description="Number of units to query during search"
    )
    
    # Timeout settings
    connection_timeout: float = Field(
        default=30.0,
        env="MILVUS_CONNECTION_TIMEOUT",
        ge=5.0,
        le=120.0,
        description="Connection timeout in seconds"
    )
    
    @field_validator('index_type')
    @classmethod
    def validate_index_type(cls, v):
        """Validate index type"""
        valid_types = ['FLAT', 'IVF_FLAT', 'IVF_SQ8', 'IVF_PQ', 'HNSW']
        if v not in valid_types:
            logger.warning(f"Unknown index type '{v}', using 'IVF_FLAT'")
            return 'IVF_FLAT'
        return v
    
    @field_validator('metric_type') 
    @classmethod
    def validate_metric_type(cls, v):
        """Validate metric type"""
        valid_metrics = ['L2', 'IP', 'COSINE', 'HAMMING', 'JACCARD']
        if v not in valid_metrics:
            logger.warning(f"Unknown metric type '{v}', using 'COSINE'")
            return 'COSINE'
        return v


class GeminiConfig:
    """Google Gemini API configuration"""
    
    # API settings
    google_api_key: Optional[str] = Field(
        default=None,
        env="GEMINI_API_KEY",
        description="Google Gemini API key"
    )
    
    # Model settings
    embedding_model: str = Field(
        default="text-embedding-004",
        env="GEMINI_EMBEDDING_MODEL",
        description="Gemini embedding model name"
    )
    
    chat_model: str = Field(
        default="gemini-pro",
        env="GEMINI_CHAT_MODEL", 
        description="Gemini chat model name"
    )
    
    # Request settings
    max_tokens: int = Field(
        default=4096,
        env="GEMINI_MAX_TOKENS",
        ge=100,
        le=32768,
        description="Maximum tokens per request"
    )
    
    temperature: float = Field(
        default=0.7,
        env="GEMINI_TEMPERATURE",
        ge=0.0,
        le=2.0,
        description="Temperature for text generation"
    )
    
    top_p: float = Field(
        default=0.9,
        env="GEMINI_TOP_P",
        ge=0.0,
        le=1.0,
        description="Top-p sampling parameter"
    )
    
    top_k: int = Field(
        default=40,
        env="GEMINI_TOP_K", 
        ge=1,
        le=100,
        description="Top-k sampling parameter"
    )
    
    # Rate limiting
    requests_per_minute: int = Field(
        default=60,
        env="GEMINI_REQUESTS_PER_MINUTE",
        ge=1,
        le=1000,
        description="Maximum requests per minute"
    )
    
    batch_size: int = Field(
        default=10,
        env="GEMINI_BATCH_SIZE",
        ge=1,
        le=100,
        description="Batch size for embedding requests"
    )
    
    # Timeout settings
    request_timeout: float = Field(
        default=60.0,
        env="GEMINI_REQUEST_TIMEOUT",
        ge=5.0,
        le=300.0,
        description="Request timeout in seconds"
    )
    
    @field_validator('google_api_key')
    @classmethod
    def validate_api_key(cls, v):
        """Validate API key format"""
        if v and not v.startswith('AIza'):
            logger.warning("Google API key should start with 'AIza'")
        return v


class WorkerConfig:
    """Worker service configuration"""
    
    # Concurrency settings
    max_document_workers: int = Field(
        default=2,
        env="MAX_DOCUMENT_WORKERS",
        ge=1,
        le=10,
        description="Maximum number of document processing workers"
    )
    
    max_embedding_workers: int = Field(
        default=2,
        env="MAX_EMBEDDING_WORKERS",
        ge=1,
        le=10,
        description="Maximum number of embedding workers"
    )
    
    max_question_workers: int = Field(
        default=2,
        env="MAX_QUESTION_WORKERS",
        ge=1,
        le=10,
        description="Maximum number of question processing workers"
    )
    
    # Processing settings
    chunk_size: int = Field(
        default=1000,
        env="DOCUMENT_CHUNK_SIZE",
        ge=100,
        le=4000,
        description="Document chunk size in characters"
    )
    
    chunk_overlap: int = Field(
        default=200,
        env="DOCUMENT_CHUNK_OVERLAP",
        ge=0,
        le=500,
        description="Chunk overlap in characters"
    )
    
    max_file_size: int = Field(
        default=50 * 1024 * 1024,  # 50MB
        env="MAX_FILE_SIZE",
        ge=1024,
        le=500 * 1024 * 1024,  # 500MB
        description="Maximum file size in bytes"
    )
    
    # Retry settings
    max_retries: int = Field(
        default=3,
        env="MAX_RETRIES",
        ge=1,
        le=10,
        description="Maximum number of retry attempts"
    )
    
    retry_delay: float = Field(
        default=1.0,
        env="RETRY_DELAY",
        ge=0.1,
        le=60.0,
        description="Delay between retries in seconds"
    )
    
    # Processing timeouts
    document_processing_timeout: float = Field(
        default=300.0,
        env="DOCUMENT_PROCESSING_TIMEOUT",
        ge=30.0,
        le=1800.0,
        description="Document processing timeout in seconds"
    )
    
    embedding_timeout: float = Field(
        default=120.0,
        env="EMBEDDING_TIMEOUT",
        ge=10.0,
        le=600.0,
        description="Embedding generation timeout in seconds"
    )
    
    question_timeout: float = Field(
        default=60.0,
        env="QUESTION_TIMEOUT",
        ge=5.0,
        le=300.0,
        description="Question processing timeout in seconds"
    )


class APIConfig:
    """API service configuration"""
    
    # Server settings
    host: str = Field(
        default="0.0.0.0",
        env="API_HOST",
        description="API server host"
    )
    
    port: int = Field(
        default=8000,
        env="API_PORT",
        ge=1,
        le=65535,
        description="API server port"
    )
    
    reload: bool = Field(
        default=False,
        env="API_RELOAD",
        description="Enable auto-reload for development"
    )
    
    # Request limits
    max_request_size: int = Field(
        default=16 * 1024 * 1024,  # 16MB
        env="MAX_REQUEST_SIZE",
        ge=1024,
        le=100 * 1024 * 1024,  # 100MB
        description="Maximum request size in bytes"
    )
    
    request_timeout: float = Field(
        default=30.0,
        env="REQUEST_TIMEOUT",
        ge=1.0,
        le=300.0,
        description="Request timeout in seconds"
    )
    
    # CORS settings
    cors_origins: List[str] = Field(
        default_factory=lambda: ["*"],
        env="CORS_ORIGINS",
        description="Allowed CORS origins"
    )
    
    cors_methods: List[str] = Field(
        default_factory=lambda: ["GET", "POST", "PUT", "DELETE"],
        env="CORS_METHODS",
        description="Allowed CORS methods"
    )
    
    # WebSocket settings
    websocket_timeout: float = Field(
        default=300.0,
        env="WEBSOCKET_TIMEOUT",
        ge=30.0,
        le=1800.0,
        description="WebSocket connection timeout"
    )
    
    max_websocket_connections: int = Field(
        default=100,
        env="MAX_WEBSOCKET_CONNECTIONS",
        ge=1,
        le=10000,
        description="Maximum concurrent WebSocket connections"
    )
    
    max_connections_per_session: int = Field(
        default=5,
        env="MAX_CONNECTIONS_PER_SESSION",
        ge=1,
        le=20,
        description="Maximum WebSocket connections per session"
    )
    
    websocket_heartbeat_interval: int = Field(
        default=30,
        env="WEBSOCKET_HEARTBEAT_INTERVAL",
        ge=5,
        le=300,
        description="WebSocket heartbeat interval in seconds"
    )
    
    websocket_connection_timeout: int = Field(
        default=300,
        env="WEBSOCKET_CONNECTION_TIMEOUT",
        ge=60,
        le=3600,
        description="WebSocket connection timeout in seconds"
    )
    
    websocket_auth_timeout: int = Field(
        default=10,
        env="WEBSOCKET_AUTH_TIMEOUT",
        ge=5,
        le=60,
        description="WebSocket authentication timeout in seconds"
    )


class UIConfig:
    """UI service configuration"""
    
    # Streamlit settings
    ui_host: str = Field(
        default="0.0.0.0",
        env="UI_HOST",
        description="Streamlit server host"
    )
    
    ui_port: int = Field(
        default=8501,
        env="UI_PORT",
        ge=1,
        le=65535,
        description="Streamlit server port"
    )
    
    # UI behavior
    page_title: str = Field(
        default="RAG-101: Medical Q&A System",
        env="PAGE_TITLE",
        description="Page title for the UI"
    )
    
    max_message_history: int = Field(
        default=50,
        env="MAX_MESSAGE_HISTORY",
        ge=5,
        le=500,
        description="Maximum messages to keep in chat history"
    )
    
    auto_refresh_interval: float = Field(
        default=2.0,
        env="AUTO_REFRESH_INTERVAL",
        ge=0.5,
        le=10.0,
        description="Auto refresh interval for dashboard in seconds"
    )
    
    # Theme settings
    theme: str = Field(
        default="light",
        env="UI_THEME",
        description="UI theme (light, dark)"
    )
    
    @field_validator('theme')
    @classmethod
    def validate_theme(cls, v):
        """Validate theme"""
        valid_themes = ['light', 'dark']
        if v not in valid_themes:
            logger.warning(f"Unknown theme '{v}', using 'light'")
            return 'light'
        return v


# Centralized Configuration Loader

class AppConfig(
    BaseConfig,
    HealthCheckConfig,
    NATSConfig,
    MilvusConfig,
    GeminiConfig,
    WorkerConfig,
    APIConfig,
    UIConfig
):
    """
    Main application configuration that combines all service-specific configs
    
    This class inherits from all service-specific configuration classes,
    providing a single source of truth for all configuration values.
    """
    
    def __init__(self, **kwargs):
        """Initialize configuration with validation"""
        # Load .env file before initialization
        load_dotenv_file()
        
        super().__init__(**kwargs)
        
        # Setup logging based on configuration
        self.setup_logging()
        
        # Validate configuration after loading
        self.validate_configuration()
    
    def validate_configuration(self) -> None:
        """Validate the complete configuration"""
        validation_errors = []
        
        # Check required API key for Gemini
        if not self.google_api_key:
            validation_errors.append("GEMINI_API_KEY is required for AI functionality")
        
        # Validate TTL consistency
        if self.message_ttl > self.session_ttl:
            logger.warning("Message TTL is greater than session TTL - sessions may expire before messages")
        
        # Validate worker concurrency
        total_workers = (
            self.max_document_workers + 
            self.max_embedding_workers + 
            self.max_question_workers
        )
        if total_workers > 20:
            logger.warning(f"High worker count ({total_workers}) may cause resource issues")
        
        # Validate chunk settings
        if self.chunk_overlap >= self.chunk_size:
            validation_errors.append("Chunk overlap must be less than chunk size")
        
        # Validate port conflicts
        ports = [self.port, self.ui_port]
        if len(ports) != len(set(ports)):
            validation_errors.append("Port conflicts detected between services")
        
        # Validate vector dimension consistency
        if self.vector_dimension != 768 and self.embedding_model == "text-embedding-004":
            logger.warning("Vector dimension may not match embedding model dimension")
        
        if validation_errors:
            error_msg = "Configuration validation errors:\n" + "\n".join(f"- {error}" for error in validation_errors)
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        logger.info("Configuration validation passed")
    
    def get_nats_config(self) -> dict:
        """Get NATS-specific configuration as dictionary"""
        return {
            'servers': self.nats_servers,
            'max_reconnect_attempts': self.max_reconnect_attempts,
            'reconnect_time_wait': self.reconnect_time_wait,
            'ping_interval': self.ping_interval,
            'max_outstanding_pings': self.max_outstanding_pings,
            'message_ttl': self.message_ttl,
            'session_ttl': self.session_ttl
        }
    
    def get_milvus_config(self) -> dict:
        """Get Milvus-specific configuration as dictionary"""
        return {
            'host': self.milvus_host,
            'port': self.milvus_port,
            'alias': self.milvus_alias,
            'collection_name': self.collection_name,
            'vector_dimension': self.vector_dimension,
            'index_type': self.index_type,
            'metric_type': self.metric_type,
            'nlist': self.nlist,
            'search_nprobe': self.search_nprobe,
            'connection_timeout': self.connection_timeout
        }
    
    def get_gemini_config(self) -> dict:
        """Get Gemini-specific configuration as dictionary"""
        return {
            'api_key': self.google_api_key,
            'embedding_model': self.embedding_model,
            'chat_model': self.chat_model,
            'max_tokens': self.max_tokens,
            'temperature': self.temperature,
            'top_p': self.top_p,
            'top_k': self.top_k,
            'requests_per_minute': self.requests_per_minute,
            'batch_size': self.batch_size,
            'request_timeout': self.request_timeout
        }
    
    def get_worker_config(self) -> dict:
        """Get worker-specific configuration as dictionary"""
        return {
            'max_document_workers': self.max_document_workers,
            'max_embedding_workers': self.max_embedding_workers,
            'max_question_workers': self.max_question_workers,
            'chunk_size': self.chunk_size,
            'chunk_overlap': self.chunk_overlap,
            'max_file_size': self.max_file_size,
            'max_retries': self.max_retries,
            'retry_delay': self.retry_delay,
            'document_processing_timeout': self.document_processing_timeout,
            'embedding_timeout': self.embedding_timeout,
            'question_timeout': self.question_timeout
        }
    
    def get_api_config(self) -> dict:
        """Get API-specific configuration as dictionary"""
        return {
            'host': self.host,
            'port': self.port,
            'reload': self.reload,
            'max_request_size': self.max_request_size,
            'request_timeout': self.request_timeout,
            'cors_origins': self.cors_origins,
            'cors_methods': self.cors_methods,
            'websocket_timeout': self.websocket_timeout,
            'max_websocket_connections': self.max_websocket_connections,
            'max_connections_per_session': self.max_connections_per_session,
            'websocket_heartbeat_interval': self.websocket_heartbeat_interval,
            'websocket_connection_timeout': self.websocket_connection_timeout,
            'websocket_auth_timeout': self.websocket_auth_timeout
        }
    
    def get_ui_config(self) -> dict:
        """Get UI-specific configuration as dictionary"""
        return {
            'host': self.ui_host,
            'port': self.ui_port,
            'page_title': self.page_title,
            'max_message_history': self.max_message_history,
            'auto_refresh_interval': self.auto_refresh_interval,
            'theme': self.theme
        }
    
    def to_dict(self) -> dict:
        """Convert configuration to dictionary"""
        return self.dict()
    
    def print_config(self, mask_secrets: bool = True) -> None:
        """Print configuration for debugging"""
        config_dict = self.dict()
        
        if mask_secrets:
            # Mask sensitive information
            for key in config_dict:
                if any(secret in key.lower() for secret in ['key', 'password', 'secret', 'token']):
                    if config_dict[key]:
                        config_dict[key] = '***MASKED***'
        
        logger.info("Current configuration:")
        for section, values in config_dict.items():
            if isinstance(values, dict):
                logger.info(f"  {section}:")
                for key, value in values.items():
                    logger.info(f"    {key}: {value}")
            else:
                logger.info(f"  {section}: {values}")


# Configuration Factory Functions

def create_config(**overrides) -> AppConfig:
    """
    Create configuration instance with optional overrides
    
    Args:
        **overrides: Configuration value overrides
        
    Returns:
        AppConfig: Configured application instance
    """
    try:
        return AppConfig(**overrides)
    except Exception as e:
        logger.error(f"Failed to create configuration: {e}")
        raise


def create_development_config() -> AppConfig:
    """Create configuration optimized for development"""
    return create_config(
        environment="development",
        debug=True,
        log_level="DEBUG",
        reload=True,
        message_ttl=300,  # 5 minutes for development
        session_ttl=1800,  # 30 minutes for development
        max_document_workers=1,
        max_embedding_workers=1,
        max_question_workers=1
    )


def create_production_config() -> AppConfig:
    """Create configuration optimized for production"""
    return create_config(
        environment="production",
        debug=False,
        log_level="INFO",
        reload=False,
        message_ttl=3600,  # 1 hour
        session_ttl=7200,  # 2 hours
    )


def create_testing_config() -> AppConfig:
    """Create configuration optimized for testing"""
    return create_config(
        environment="testing",
        debug=True,
        log_level="WARNING",
        message_ttl=60,  # 1 minute for fast tests
        session_ttl=300,  # 5 minutes for tests
        max_document_workers=1,
        max_embedding_workers=1,
        max_question_workers=1,
        health_check_interval=5,
        startup_timeout=30
    )


# Global Configuration Instance

_config_instance: Optional[AppConfig] = None

def get_config() -> AppConfig:
    """
    Get the global configuration instance (singleton pattern)
    
    Returns:
        AppConfig: Global configuration instance
    """
    global _config_instance
    
    if _config_instance is None:
        environment = os.getenv('ENVIRONMENT', 'development').lower()
        
        if environment == 'production':
            _config_instance = create_production_config()
        elif environment == 'testing':
            _config_instance = create_testing_config()
        else:
            _config_instance = create_development_config()
        
        logger.info(f"Initialized {environment} configuration")
    
    return _config_instance


def reset_config() -> None:
    """Reset the global configuration instance (useful for testing)"""
    global _config_instance
    _config_instance = None


def set_config(config: AppConfig) -> None:
    """
    Set the global configuration instance
    
    Args:
        config: Configuration instance to set as global
    """
    global _config_instance
    _config_instance = config


# Export the main configuration instance (lazy-loaded)
config = None