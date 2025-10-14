"""
Structured Logging Framework for RAG-101

This module provides comprehensive structured logging with JSON formatting,
multiple handlers, and service identification across all RAG-101 services.
"""

import os
import sys
import json
import logging
import traceback
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, Union, List
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
import contextlib


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging"""
    
    def __init__(self, service_name: str = "rag-service", service_version: str = "1.0.0"):
        super().__init__()
        self.service_name = service_name
        self.service_version = service_version
        
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as structured JSON"""
        # Base log structure
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": {
                "name": self.service_name,
                "version": self.service_version
            },
            "process": {
                "pid": os.getpid(),
                "thread_id": threading.get_ident(),
                "thread_name": threading.current_thread().name
            }
        }
        
        # Add file and function info
        if record.pathname:
            log_data["source"] = {
                "file": os.path.basename(record.pathname),
                "function": record.funcName,
                "line": record.lineno,
                "module": record.module
            }
        
        # Add exception information if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": self.formatException(record.exc_info)
            }
        
        # Add extra fields from record
        extra_fields = {}
        for key, value in record.__dict__.items():
            if key not in {
                'name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 
                'filename', 'module', 'lineno', 'funcName', 'created', 
                'msecs', 'relativeCreated', 'thread', 'threadName', 
                'processName', 'process', 'stack_info', 'exc_info', 'exc_text'
            }:
                extra_fields[key] = value
        
        if extra_fields:
            log_data["extra"] = extra_fields
        
        return json.dumps(log_data, ensure_ascii=False, default=str)


class ContextualFormatter(logging.Formatter):
    """Human-readable formatter with contextual information"""
    
    def __init__(self, service_name: str = "rag-service"):
        super().__init__()
        self.service_name = service_name
        
    def format(self, record: logging.LogRecord) -> str:
        """Format log record with contextual information"""
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        
        # Base format
        base_msg = f"[{timestamp}] {record.levelname:8} {self.service_name}:{record.name} - {record.getMessage()}"
        
        # Add source location for DEBUG and ERROR levels
        if record.levelno <= logging.DEBUG or record.levelno >= logging.ERROR:
            source_info = f" ({os.path.basename(record.pathname)}:{record.lineno})"
            base_msg += source_info
        
        # Add exception information
        if record.exc_info:
            base_msg += f"\n{self.formatException(record.exc_info)}"
        
        return base_msg


class LogContext:
    """Context manager for adding contextual information to logs"""
    
    def __init__(self, **context_data):
        self.context_data = context_data
        self.old_factory = None
        
    def __enter__(self):
        # Store old factory
        self.old_factory = logging.getLogRecordFactory()
        
        # Create new factory that adds context
        def record_factory(*args, **kwargs):
            record = self.old_factory(*args, **kwargs)
            for key, value in self.context_data.items():
                setattr(record, key, value)
            return record
        
        logging.setLogRecordFactory(record_factory)
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Restore old factory
        logging.setLogRecordFactory(self.old_factory)


class StructuredLogger:
    """Enhanced logger with structured logging capabilities"""
    
    def __init__(self, name: str, service_name: str = "rag-service"):
        self.logger = logging.getLogger(name)
        self.service_name = service_name
        
    def debug(self, message: str, **kwargs):
        """Log debug message with optional structured data"""
        self._log(logging.DEBUG, message, **kwargs)
        
    def info(self, message: str, **kwargs):
        """Log info message with optional structured data"""
        self._log(logging.INFO, message, **kwargs)
        
    def warning(self, message: str, **kwargs):
        """Log warning message with optional structured data"""
        self._log(logging.WARNING, message, **kwargs)
        
    def error(self, message: str, error: Exception = None, **kwargs):
        """Log error message with optional exception and structured data"""
        if error:
            kwargs['error_type'] = type(error).__name__
            kwargs['error_message'] = str(error)
        self._log(logging.ERROR, message, exc_info=error is not None, **kwargs)
        
    def critical(self, message: str, error: Exception = None, **kwargs):
        """Log critical message with optional exception and structured data"""
        if error:
            kwargs['error_type'] = type(error).__name__
            kwargs['error_message'] = str(error)
        self._log(logging.CRITICAL, message, exc_info=error is not None, **kwargs)
        
    def log_request(self, method: str, url: str, status_code: int, 
                   response_time: float, **kwargs):
        """Log HTTP request with structured data"""
        self._log(logging.INFO, f"{method} {url} - {status_code}", 
                 request_method=method, request_url=url,
                 response_status=status_code, response_time_ms=response_time * 1000,
                 **kwargs)
        
    def log_operation(self, operation: str, duration: float, success: bool = True, **kwargs):
        """Log operation with timing and success information"""
        level = logging.INFO if success else logging.ERROR
        status = "completed" if success else "failed"
        self._log(level, f"Operation {operation} {status} in {duration:.2f}s",
                 operation_name=operation, duration_seconds=duration,
                 operation_success=success, **kwargs)
        
    def log_exception(self, message: str, exception: Exception, **kwargs):
        """Log exception with full traceback and context"""
        kwargs['exception_type'] = type(exception).__name__
        kwargs['exception_message'] = str(exception)
        self._log(logging.ERROR, message, exc_info=True, **kwargs)
        
    def _log(self, level: int, message: str, **kwargs):
        """Internal logging method that adds structured data"""
        # Create extra dictionary for structured data
        extra = {}
        for key, value in kwargs.items():
            if key not in {'exc_info'}:
                extra[key] = value
        
        # Log with extra data
        self.logger.log(level, message, extra=extra, 
                       exc_info=kwargs.get('exc_info', False))
        
    def context(self, **context_data) -> LogContext:
        """Create logging context manager"""
        return LogContext(**context_data)


class LoggingConfig:
    """Centralized logging configuration"""
    
    def __init__(self):
        self.service_name = os.getenv('SERVICE_NAME', 'rag-service')
        self.service_version = os.getenv('SERVICE_VERSION', '1.0.0')
        self.log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
        self.environment = os.getenv('ENVIRONMENT', 'development').lower()
        self.log_dir = Path(os.getenv('LOG_DIR', './logs'))
        self.enable_json = os.getenv('ENABLE_JSON_LOGS', 'true').lower() == 'true'
        self.enable_file_logging = os.getenv('ENABLE_FILE_LOGGING', 'true').lower() == 'true'
        self.max_file_size = int(os.getenv('MAX_LOG_FILE_SIZE', str(10 * 1024 * 1024)))  # 10MB
        self.backup_count = int(os.getenv('LOG_BACKUP_COUNT', '5'))
        
    def setup_logging(self) -> None:
        """Setup comprehensive logging configuration"""
        # Create log directory
        if self.enable_file_logging:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, self.log_level))
        
        # Clear existing handlers
        root_logger.handlers.clear()
        
        # Setup console handler
        self._setup_console_handler(root_logger)
        
        # Setup file handlers
        if self.enable_file_logging:
            self._setup_file_handlers(root_logger)
        
        # Configure specific loggers
        self._configure_external_loggers()
        
        # Log configuration
        logger = StructuredLogger(__name__, self.service_name)
        logger.info("Logging configuration initialized", 
                   log_level=self.log_level,
                   environment=self.environment,
                   json_logging=self.enable_json,
                   file_logging=self.enable_file_logging)
        
    def _setup_console_handler(self, root_logger: logging.Logger) -> None:
        """Setup console handler with appropriate formatter"""
        console_handler = logging.StreamHandler(sys.stdout)
        
        if self.enable_json and self.environment == 'production':
            # Use JSON formatter for production
            formatter = JSONFormatter(self.service_name, self.service_version)
        else:
            # Use human-readable formatter for development
            formatter = ContextualFormatter(self.service_name)
            
        console_handler.setFormatter(formatter)
        console_handler.setLevel(getattr(logging, self.log_level))
        root_logger.addHandler(console_handler)
        
    def _setup_file_handlers(self, root_logger: logging.Logger) -> None:
        """Setup file handlers for different log levels"""
        # All logs file (rotating by size)
        all_logs_file = self.log_dir / f"{self.service_name}.log"
        all_handler = RotatingFileHandler(
            all_logs_file,
            maxBytes=self.max_file_size,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        
        # Error logs file (rotating by time)
        error_logs_file = self.log_dir / f"{self.service_name}-error.log"
        error_handler = TimedRotatingFileHandler(
            error_logs_file,
            when='midnight',
            interval=1,
            backupCount=30,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        
        # Set formatters
        if self.enable_json:
            json_formatter = JSONFormatter(self.service_name, self.service_version)
            all_handler.setFormatter(json_formatter)
            error_handler.setFormatter(json_formatter)
        else:
            contextual_formatter = ContextualFormatter(self.service_name)
            all_handler.setFormatter(contextual_formatter)
            error_handler.setFormatter(contextual_formatter)
        
        # Add handlers
        root_logger.addHandler(all_handler)
        root_logger.addHandler(error_handler)
        
    def _configure_external_loggers(self) -> None:
        """Configure logging levels for external libraries"""
        # Reduce noise from external libraries in production
        if self.environment == 'production':
            external_loggers = {
                'urllib3': logging.WARNING,
                'requests': logging.WARNING,
                'httpx': logging.WARNING,
                'httpcore': logging.WARNING,
                'nats': logging.INFO,
                'milvus': logging.INFO,
                'streamlit': logging.WARNING,
                'asyncio': logging.WARNING,
                'concurrent.futures': logging.WARNING
            }
        else:
            external_loggers = {
                'urllib3': logging.INFO,
                'requests': logging.INFO,
                'httpx': logging.INFO,
                'httpcore': logging.INFO,
                'nats': logging.DEBUG if self.log_level == 'DEBUG' else logging.INFO,
                'milvus': logging.DEBUG if self.log_level == 'DEBUG' else logging.INFO,
                'streamlit': logging.INFO,
            }
            
        for logger_name, level in external_loggers.items():
            logging.getLogger(logger_name).setLevel(level)


# Utility functions for common logging patterns

def get_structured_logger(name: str, service_name: str = None) -> StructuredLogger:
    """
    Get a structured logger instance
    
    Args:
        name: Logger name (usually __name__)
        service_name: Service name for identification
        
    Returns:
        StructuredLogger: Configured structured logger
    """
    if service_name is None:
        service_name = os.getenv('SERVICE_NAME', 'rag-service')
    
    return StructuredLogger(name, service_name)


def log_function_call(logger: StructuredLogger):
    """Decorator to log function calls with arguments and timing"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = datetime.now()
            function_name = f"{func.__module__}.{func.__name__}"
            
            # Log function entry
            logger.debug(f"Entering function {function_name}",
                        function=function_name,
                        args_count=len(args),
                        kwargs_keys=list(kwargs.keys()))
            
            try:
                result = func(*args, **kwargs)
                duration = (datetime.now() - start_time).total_seconds()
                
                # Log successful completion
                logger.debug(f"Function {function_name} completed successfully",
                           function=function_name,
                           duration_seconds=duration,
                           success=True)
                
                return result
                
            except Exception as e:
                duration = (datetime.now() - start_time).total_seconds()
                
                # Log function failure
                logger.error(f"Function {function_name} failed",
                           function=function_name,
                           duration_seconds=duration,
                           success=False,
                           error=e)
                raise
                
        return wrapper
    return decorator


def log_async_function_call(logger: StructuredLogger):
    """Decorator to log async function calls with arguments and timing"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            start_time = datetime.now()
            function_name = f"{func.__module__}.{func.__name__}"
            
            # Log function entry
            logger.debug(f"Entering async function {function_name}",
                        function=function_name,
                        args_count=len(args),
                        kwargs_keys=list(kwargs.keys()))
            
            try:
                result = await func(*args, **kwargs)
                duration = (datetime.now() - start_time).total_seconds()
                
                # Log successful completion
                logger.debug(f"Async function {function_name} completed successfully",
                           function=function_name,
                           duration_seconds=duration,
                           success=True)
                
                return result
                
            except Exception as e:
                duration = (datetime.now() - start_time).total_seconds()
                
                # Log function failure
                logger.error(f"Async function {function_name} failed",
                           function=function_name,
                           duration_seconds=duration,
                           success=False,
                           error=e)
                raise
                
        return wrapper
    return decorator


class PerformanceLogger:
    """Logger for performance metrics and timing"""
    
    def __init__(self, logger: StructuredLogger):
        self.logger = logger
        
    @contextlib.contextmanager
    def time_operation(self, operation_name: str, **context):
        """Context manager to time operations"""
        start_time = datetime.now()
        
        self.logger.debug(f"Starting operation: {operation_name}",
                         operation=operation_name, **context)
        
        try:
            yield
            duration = (datetime.now() - start_time).total_seconds()
            self.logger.log_operation(operation_name, duration, success=True, **context)
            
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            self.logger.log_operation(operation_name, duration, success=False, 
                                    error=e, **context)
            raise


def setup_logging(service_name: str = None) -> StructuredLogger:
    """
    Setup logging configuration and return a structured logger
    
    Args:
        service_name: Name of the service for logging identification
        
    Returns:
        StructuredLogger: Configured logger for the service
    """
    if service_name:
        os.environ['SERVICE_NAME'] = service_name
    
    # Initialize logging configuration
    config = LoggingConfig()
    config.setup_logging()
    
    # Return structured logger for the service
    return get_structured_logger(__name__, service_name)


# Global logger instance for shared module
logger = get_structured_logger(__name__)


# Context managers and utilities

@contextlib.contextmanager
def log_context(**context_data):
    """Context manager for adding context to all logs within the block"""
    with LogContext(**context_data):
        yield


def configure_service_logging(service_name: str) -> StructuredLogger:
    """
    Configure logging for a specific service
    
    Args:
        service_name: Name of the service
        
    Returns:
        StructuredLogger: Configured logger for the service
    """
    return setup_logging(service_name)


# Export main functions and classes
__all__ = [
    'StructuredLogger',
    'LoggingConfig', 
    'JSONFormatter',
    'ContextualFormatter',
    'LogContext',
    'PerformanceLogger',
    'get_structured_logger',
    'log_function_call',
    'log_async_function_call',
    'setup_logging',
    'configure_service_logging',
    'log_context',
    'logger'
]