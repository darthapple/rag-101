"""
Enhanced Error Handling Utilities for Worker Services

This module provides decorators and utilities for comprehensive error handling
across all worker handler types, including external service integration error handling.
"""

import asyncio
import functools
import time
from datetime import datetime
from typing import Any, Dict, Optional, Callable, Union, Type
from contextlib import asynccontextmanager

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

from shared.logging import get_structured_logger, StructuredLogger
from shared.config import get_config


class ExternalServiceError(Exception):
    """Exception for external service failures"""
    def __init__(self, service: str, message: str, original_error: Exception = None):
        self.service = service
        self.original_error = original_error
        super().__init__(f"{service}: {message}")


class CircuitBreakerOpen(Exception):
    """Exception when circuit breaker is open"""
    pass


class ExternalServiceCircuitBreaker:
    """Circuit breaker for external service calls"""
    
    def __init__(
        self, 
        service_name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        success_threshold: int = 3
    ):
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        
        self.logger = get_structured_logger(f"circuit_breaker.{service_name}", "rag-worker")
        
    def record_success(self):
        """Record successful operation"""
        self.failure_count = 0
        
        if self.state == "HALF_OPEN":
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self.state = "CLOSED"
                self.success_count = 0
                self.logger.info(
                    "Circuit breaker closed after successful recovery",
                    service_name=self.service_name,
                    success_count=self.success_count
                )
    
    def record_failure(self):
        """Record failed operation"""
        self.failure_count += 1
        self.success_count = 0
        self.last_failure_time = datetime.now()
        
        if self.state == "CLOSED" and self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            self.logger.warning(
                "Circuit breaker opened due to failures",
                service_name=self.service_name,
                failure_count=self.failure_count,
                failure_threshold=self.failure_threshold
            )
        elif self.state == "HALF_OPEN":
            self.state = "OPEN"
            self.logger.warning(
                "Circuit breaker returned to open state",
                service_name=self.service_name,
                failure_count=self.failure_count
            )
    
    def can_execute(self) -> bool:
        """Check if operation should be attempted"""
        if self.state == "CLOSED":
            return True
        
        if self.state == "OPEN":
            if self.last_failure_time:
                time_since_failure = (datetime.now() - self.last_failure_time).total_seconds()
                if time_since_failure >= self.recovery_timeout:
                    self.state = "HALF_OPEN"
                    self.success_count = 0
                    self.logger.info(
                        "Circuit breaker half-open, attempting recovery",
                        service_name=self.service_name,
                        time_since_failure=time_since_failure
                    )
                    return True
            return False
        
        # HALF_OPEN state
        return True
    
    def get_state(self) -> Dict[str, Any]:
        """Get circuit breaker state"""
        return {
            "service_name": self.service_name,
            "state": self.state,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_failure_time": self.last_failure_time.isoformat() if self.last_failure_time else None
        }


# Global circuit breakers for common services
_circuit_breakers: Dict[str, ExternalServiceCircuitBreaker] = {}


def get_circuit_breaker(service_name: str) -> ExternalServiceCircuitBreaker:
    """Get or create circuit breaker for service"""
    if service_name not in _circuit_breakers:
        _circuit_breakers[service_name] = ExternalServiceCircuitBreaker(service_name)
    return _circuit_breakers[service_name]


@asynccontextmanager
async def external_service_call(
    service_name: str,
    operation_name: str,
    timeout: float = 30.0,
    retries: int = 3,
    backoff_multiplier: float = 2.0,
    logger: StructuredLogger = None
):
    """
    Context manager for external service calls with circuit breaker and retry logic
    
    Args:
        service_name: Name of the external service
        operation_name: Name of the operation being performed
        timeout: Timeout for the operation
        retries: Number of retries
        backoff_multiplier: Multiplier for exponential backoff
        logger: Logger instance
    """
    if logger is None:
        logger = get_structured_logger("external_service", "rag-worker")
    
    circuit_breaker = get_circuit_breaker(service_name)
    
    # Check circuit breaker
    if not circuit_breaker.can_execute():
        logger.error(
            "Circuit breaker is open",
            service_name=service_name,
            operation_name=operation_name,
            circuit_breaker_state=circuit_breaker.get_state()
        )
        raise CircuitBreakerOpen(f"Circuit breaker is open for {service_name}")
    
    start_time = time.time()
    last_exception = None
    
    for attempt in range(retries + 1):
        try:
            logger.debug(
                f"Attempting {service_name} operation",
                service_name=service_name,
                operation_name=operation_name,
                attempt=attempt + 1,
                max_retries=retries + 1,
                timeout=timeout
            )
            
            # Execute with timeout
            yield
            
            # Record success
            execution_time = time.time() - start_time
            circuit_breaker.record_success()
            
            logger.info(
                f"{service_name} operation completed successfully",
                service_name=service_name,
                operation_name=operation_name,
                execution_time=execution_time,
                attempt=attempt + 1
            )
            return
            
        except asyncio.TimeoutError as e:
            last_exception = e
            circuit_breaker.record_failure()
            
            logger.warning(
                f"{service_name} operation timeout",
                service_name=service_name,
                operation_name=operation_name,
                timeout=timeout,
                attempt=attempt + 1,
                max_retries=retries + 1,
                error=str(e)
            )
            
        except (ConnectionError, OSError) as e:
            last_exception = e
            circuit_breaker.record_failure()
            
            logger.warning(
                f"{service_name} connection error",
                service_name=service_name,
                operation_name=operation_name,
                attempt=attempt + 1,
                max_retries=retries + 1,
                error=str(e),
                error_type=type(e).__name__
            )
            
        except Exception as e:
            last_exception = e
            # Don't record as circuit breaker failure for application errors
            
            logger.warning(
                f"{service_name} operation error",
                service_name=service_name,
                operation_name=operation_name,
                attempt=attempt + 1,
                max_retries=retries + 1,
                error=str(e),
                error_type=type(e).__name__
            )
        
        # Wait before retry (except on last attempt)
        if attempt < retries:
            retry_delay = backoff_multiplier ** attempt
            logger.debug(
                "Retrying after delay",
                service_name=service_name,
                operation_name=operation_name,
                retry_delay=retry_delay,
                next_attempt=attempt + 2
            )
            await asyncio.sleep(retry_delay)
    
    # All retries exhausted
    total_time = time.time() - start_time
    logger.error(
        f"{service_name} operation failed after all retries",
        service_name=service_name,
        operation_name=operation_name,
        total_retries=retries + 1,
        total_time=total_time,
        final_error=str(last_exception),
        circuit_breaker_state=circuit_breaker.get_state()
    )
    
    raise ExternalServiceError(service_name, f"Operation failed after {retries + 1} attempts", last_exception)


def with_error_handling(
    operation_name: str = None,
    retries: int = 3,
    timeout: float = None,
    circuit_breaker: bool = True
):
    """
    Decorator for comprehensive error handling in worker methods
    
    Args:
        operation_name: Name of the operation for logging
        retries: Number of retries for retryable errors
        timeout: Timeout for the operation
        circuit_breaker: Whether to use circuit breaker for external calls
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Get logger from instance or create one
            instance = args[0] if args else None
            if hasattr(instance, 'logger'):
                logger = instance.logger
            else:
                logger = get_structured_logger("worker.error_handler", "rag-worker")
            
            op_name = operation_name or func.__name__
            start_time = time.time()
            
            # Get timeout from config if not specified
            if timeout is None:
                config = get_config()
                method_timeout = getattr(config, f'{op_name}_timeout', 30.0)
            else:
                method_timeout = timeout
            
            last_exception = None
            
            for attempt in range(retries + 1):
                try:
                    logger.debug(
                        f"Starting {op_name} operation",
                        operation_name=op_name,
                        attempt=attempt + 1,
                        max_retries=retries + 1,
                        timeout=method_timeout,
                        function=func.__name__
                    )
                    
                    # Execute with timeout if specified
                    if method_timeout:
                        result = await asyncio.wait_for(
                            func(*args, **kwargs),
                            timeout=method_timeout
                        )
                    else:
                        result = await func(*args, **kwargs)
                    
                    # Log success
                    execution_time = time.time() - start_time
                    logger.debug(
                        f"{op_name} operation completed successfully",
                        operation_name=op_name,
                        execution_time=execution_time,
                        attempt=attempt + 1,
                        function=func.__name__
                    )
                    
                    return result
                    
                except asyncio.TimeoutError as e:
                    last_exception = e
                    logger.warning(
                        f"{op_name} operation timeout",
                        operation_name=op_name,
                        timeout=method_timeout,
                        attempt=attempt + 1,
                        max_retries=retries + 1,
                        function=func.__name__
                    )
                    
                except (ConnectionError, OSError, ExternalServiceError) as e:
                    last_exception = e
                    logger.warning(
                        f"{op_name} retryable error",
                        operation_name=op_name,
                        error=str(e),
                        error_type=type(e).__name__,
                        attempt=attempt + 1,
                        max_retries=retries + 1,
                        function=func.__name__
                    )
                    
                except (ValueError, KeyError, TypeError) as e:
                    # Non-retryable errors - fail immediately
                    execution_time = time.time() - start_time
                    logger.error(
                        f"{op_name} non-retryable error",
                        operation_name=op_name,
                        error=str(e),
                        error_type=type(e).__name__,
                        execution_time=execution_time,
                        function=func.__name__
                    )
                    raise
                    
                except Exception as e:
                    last_exception = e
                    logger.warning(
                        f"{op_name} unexpected error",
                        operation_name=op_name,
                        error=str(e),
                        error_type=type(e).__name__,
                        attempt=attempt + 1,
                        max_retries=retries + 1,
                        function=func.__name__
                    )
                
                # Wait before retry (except on last attempt)
                if attempt < retries:
                    retry_delay = 2.0 ** attempt  # Exponential backoff
                    logger.debug(
                        "Retrying after delay",
                        operation_name=op_name,
                        retry_delay=retry_delay,
                        next_attempt=attempt + 2
                    )
                    await asyncio.sleep(retry_delay)
            
            # All retries exhausted
            total_time = time.time() - start_time
            logger.error(
                f"{op_name} operation failed after all retries",
                operation_name=op_name,
                total_retries=retries + 1,
                total_time=total_time,
                final_error=str(last_exception),
                error_type=type(last_exception).__name__,
                function=func.__name__
            )
            
            raise last_exception
            
        return wrapper
    return decorator


def with_fallback(fallback_value: Any = None, fallback_func: Callable = None):
    """
    Decorator to provide fallback values for operations that can gracefully degrade
    
    Args:
        fallback_value: Static fallback value
        fallback_func: Function to call for dynamic fallback
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            instance = args[0] if args else None
            if hasattr(instance, 'logger'):
                logger = instance.logger
            else:
                logger = get_structured_logger("worker.fallback", "rag-worker")
            
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logger.warning(
                    f"Operation {func.__name__} failed, using fallback",
                    function=func.__name__,
                    error=str(e),
                    error_type=type(e).__name__,
                    has_fallback_value=fallback_value is not None,
                    has_fallback_func=fallback_func is not None
                )
                
                if fallback_func:
                    if asyncio.iscoroutinefunction(fallback_func):
                        return await fallback_func(*args, **kwargs)
                    else:
                        return fallback_func(*args, **kwargs)
                else:
                    return fallback_value
                    
        return wrapper
    return decorator


def get_circuit_breaker_states() -> Dict[str, Dict[str, Any]]:
    """Get states of all circuit breakers"""
    return {
        name: breaker.get_state() 
        for name, breaker in _circuit_breakers.items()
    }


def reset_circuit_breakers():
    """Reset all circuit breakers (useful for testing)"""
    global _circuit_breakers
    _circuit_breakers.clear()


# Utility functions for error classification
def is_retryable_error(error: Exception) -> bool:
    """Check if an error should be retried"""
    retryable_types = (
        ConnectionError,
        OSError,
        asyncio.TimeoutError,
        ExternalServiceError
    )
    
    if isinstance(error, retryable_types):
        return True
    
    # Check error message for retryable patterns
    error_msg = str(error).lower()
    retryable_patterns = [
        'connection', 'timeout', 'network', 'temporary', 'unavailable',
        'busy', 'overloaded', 'rate limit', 'throttled', 'service unavailable'
    ]
    
    return any(pattern in error_msg for pattern in retryable_patterns)


def should_trigger_circuit_breaker(error: Exception) -> bool:
    """Check if an error should trigger circuit breaker"""
    # Only network/connection errors should trigger circuit breaker
    circuit_breaker_types = (
        ConnectionError,
        OSError,
        asyncio.TimeoutError,
    )
    
    return isinstance(error, circuit_breaker_types)