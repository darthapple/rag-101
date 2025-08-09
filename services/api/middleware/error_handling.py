"""
Enhanced Error Handling Middleware for FastAPI

This module provides comprehensive error handling capabilities including:
- Request correlation tracking
- Rate limiting error handling
- Circuit breaker integration
- Error aggregation and metrics
- Graceful degradation support
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Callable
from collections import defaultdict, deque
import logging

from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# Import project modules
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

from shared.logging import get_structured_logger, StructuredLogger
from shared.config import get_config


class ErrorMetrics:
    """Track error metrics and patterns"""
    
    def __init__(self, window_size: int = 100, time_window: int = 300):
        self.window_size = window_size
        self.time_window = time_window  # 5 minutes
        self.errors = deque(maxlen=window_size)
        self.error_counts = defaultdict(int)
        self.error_rates = defaultdict(list)
        self.logger = get_structured_logger("api.error_metrics", "rag-api")
        
    def record_error(self, error_type: str, endpoint: str, status_code: int):
        """Record an error occurrence"""
        now = datetime.now()
        error_record = {
            'timestamp': now,
            'error_type': error_type,
            'endpoint': endpoint,
            'status_code': status_code
        }
        
        self.errors.append(error_record)
        self.error_counts[error_type] += 1
        
        # Track error rates per endpoint
        self.error_rates[endpoint].append(now)
        
        # Clean old entries
        self._cleanup_old_entries(endpoint)
        
    def _cleanup_old_entries(self, endpoint: str):
        """Remove entries older than time window"""
        cutoff = datetime.now() - timedelta(seconds=self.time_window)
        self.error_rates[endpoint] = [
            ts for ts in self.error_rates[endpoint] 
            if ts > cutoff
        ]
    
    def get_error_rate(self, endpoint: str) -> float:
        """Get error rate per minute for endpoint"""
        if endpoint not in self.error_rates:
            return 0.0
        
        self._cleanup_old_entries(endpoint)
        count = len(self.error_rates[endpoint])
        return (count / self.time_window) * 60  # Per minute
    
    def get_top_errors(self, limit: int = 5) -> Dict[str, int]:
        """Get most common error types"""
        return dict(sorted(
            self.error_counts.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:limit])
    
    def is_error_spike(self, error_type: str, threshold: float = 10.0) -> bool:
        """Detect if there's an error spike"""
        recent_errors = [
            e for e in self.errors 
            if e['error_type'] == error_type and
            (datetime.now() - e['timestamp']).seconds < 60
        ]
        return len(recent_errors) > threshold


class CircuitBreakerState:
    """Simple circuit breaker for external service calls"""
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.logger = get_structured_logger("api.circuit_breaker", "rag-api")
        
    def record_success(self):
        """Record successful operation"""
        self.failure_count = 0
        if self.state == "HALF_OPEN":
            self.state = "CLOSED"
            self.logger.info("Circuit breaker closed after successful recovery")
    
    def record_failure(self):
        """Record failed operation"""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            self.logger.warning(
                f"Circuit breaker opened after {self.failure_count} failures",
                failure_count=self.failure_count,
                failure_threshold=self.failure_threshold
            )
    
    def can_attempt(self) -> bool:
        """Check if operation should be attempted"""
        if self.state == "CLOSED":
            return True
        
        if self.state == "OPEN":
            if self.last_failure_time:
                time_since_failure = (datetime.now() - self.last_failure_time).seconds
                if time_since_failure >= self.recovery_timeout:
                    self.state = "HALF_OPEN"
                    self.logger.info("Circuit breaker half-open, attempting recovery")
                    return True
            return False
        
        # HALF_OPEN state - allow one attempt
        return True


class RateLimitTracker:
    """Track request rates per client"""
    
    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = defaultdict(deque)
        
    def is_rate_limited(self, client_id: str) -> bool:
        """Check if client is rate limited"""
        now = time.time()
        cutoff = now - self.window_seconds
        
        # Clean old requests
        client_requests = self.requests[client_id]
        while client_requests and client_requests[0] < cutoff:
            client_requests.popleft()
        
        # Check rate limit
        if len(client_requests) >= self.max_requests:
            return True
        
        # Record this request
        client_requests.append(now)
        return False


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Comprehensive error handling middleware"""
    
    def __init__(
        self, 
        app: ASGIApp,
        enable_circuit_breaker: bool = True,
        enable_rate_limiting: bool = True,
        enable_error_aggregation: bool = True
    ):
        super().__init__(app)
        self.config = get_config()
        self.logger = get_structured_logger("api.error_middleware", "rag-api")
        
        # Initialize components
        self.error_metrics = ErrorMetrics() if enable_error_aggregation else None
        self.circuit_breaker = CircuitBreakerState() if enable_circuit_breaker else None
        self.rate_limiter = RateLimitTracker() if enable_rate_limiting else None
        
        # Error response templates
        self.error_templates = {
            "rate_limited": {
                "error": "rate_limit_exceeded",
                "message": "Too many requests. Please try again later.",
                "retry_after": 60
            },
            "circuit_breaker_open": {
                "error": "service_unavailable",
                "message": "Service temporarily unavailable. Please try again later.",
                "retry_after": 30
            },
            "degraded_service": {
                "error": "degraded_service",
                "message": "Service is running in degraded mode. Some features may be limited.",
            }
        }
        
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Main middleware dispatch logic"""
        start_time = datetime.now()
        request_id = getattr(request.state, 'request_id', f"req_{int(time.time() * 1000)}")
        client_id = self._get_client_id(request)
        
        try:
            # Rate limiting check
            if self.rate_limiter and self.rate_limiter.is_rate_limited(client_id):
                self.logger.warning(
                    "Rate limit exceeded",
                    request_id=request_id,
                    client_id=client_id,
                    endpoint=request.url.path
                )
                
                return self._create_error_response(
                    request, "rate_limited", 429, request_id
                )
            
            # Circuit breaker check for external service endpoints
            if self.circuit_breaker and self._is_external_service_endpoint(request.url.path):
                if not self.circuit_breaker.can_attempt():
                    self.logger.warning(
                        "Circuit breaker open - rejecting request",
                        request_id=request_id,
                        endpoint=request.url.path
                    )
                    
                    return self._create_error_response(
                        request, "circuit_breaker_open", 503, request_id
                    )
            
            # Process request
            response = await call_next(request)
            
            # Record success for circuit breaker
            if self.circuit_breaker and self._is_external_service_endpoint(request.url.path):
                if response.status_code < 500:
                    self.circuit_breaker.record_success()
                else:
                    self.circuit_breaker.record_failure()
            
            # Record metrics for errors
            if self.error_metrics and response.status_code >= 400:
                error_type = self._classify_error(response.status_code)
                self.error_metrics.record_error(
                    error_type, request.url.path, response.status_code
                )
            
            return response
            
        except Exception as exc:
            # Record failure for circuit breaker
            if self.circuit_breaker and self._is_external_service_endpoint(request.url.path):
                self.circuit_breaker.record_failure()
            
            # Record error metrics
            if self.error_metrics:
                error_type = type(exc).__name__
                self.error_metrics.record_error(error_type, request.url.path, 500)
            
            # Log comprehensive error information
            processing_time = (datetime.now() - start_time).total_seconds()
            
            self.logger.log_exception(
                f"Middleware caught exception: {str(exc)}",
                exception=exc,
                request_id=request_id,
                client_id=client_id,
                endpoint=request.url.path,
                processing_time=processing_time,
                error_context="middleware"
            )
            
            # Re-raise to let FastAPI exception handlers deal with it
            raise
    
    def _get_client_id(self, request: Request) -> str:
        """Get client identifier for rate limiting"""
        # Try different methods to identify the client
        if "x-forwarded-for" in request.headers:
            return request.headers["x-forwarded-for"].split(",")[0].strip()
        elif "x-real-ip" in request.headers:
            return request.headers["x-real-ip"]
        elif request.client:
            return request.client.host
        else:
            return "unknown"
    
    def _is_external_service_endpoint(self, path: str) -> bool:
        """Check if endpoint involves external service calls"""
        external_endpoints = [
            "/api/v1/documents",  # Document processing
            "/api/v1/questions",  # Q&A processing
            "/ws/",              # WebSocket connections
        ]
        return any(path.startswith(endpoint) for endpoint in external_endpoints)
    
    def _classify_error(self, status_code: int) -> str:
        """Classify error by status code"""
        if status_code >= 500:
            return "server_error"
        elif status_code >= 400:
            return "client_error"
        else:
            return "unknown_error"
    
    def _create_error_response(
        self, 
        request: Request, 
        error_type: str, 
        status_code: int, 
        request_id: str
    ) -> JSONResponse:
        """Create structured error response"""
        template = self.error_templates.get(error_type, {})
        
        content = {
            **template,
            "request_id": request_id,
            "timestamp": datetime.now().isoformat(),
            "path": request.url.path
        }
        
        headers = {}
        if "retry_after" in template:
            headers["Retry-After"] = str(template["retry_after"])
        
        return JSONResponse(
            status_code=status_code,
            content=content,
            headers=headers
        )
    
    def get_error_stats(self) -> Dict[str, Any]:
        """Get current error statistics"""
        stats = {
            "circuit_breaker_state": self.circuit_breaker.state if self.circuit_breaker else None,
            "top_errors": self.error_metrics.get_top_errors() if self.error_metrics else {},
        }
        
        if self.error_metrics:
            # Get error rates for common endpoints
            common_endpoints = ["/api/v1/questions", "/api/v1/documents", "/api/v1/sessions"]
            stats["endpoint_error_rates"] = {
                endpoint: self.error_metrics.get_error_rate(endpoint)
                for endpoint in common_endpoints
            }
        
        return stats


class GracefulDegradationManager:
    """Manage service degradation based on error patterns"""
    
    def __init__(self):
        self.degraded_features = set()
        self.logger = get_structured_logger("api.degradation", "rag-api")
        
    def enable_degradation(self, feature: str, reason: str):
        """Enable degraded mode for a feature"""
        if feature not in self.degraded_features:
            self.degraded_features.add(feature)
            self.logger.warning(
                f"Enabling degraded mode for {feature}",
                feature=feature,
                reason=reason,
                degraded_features=list(self.degraded_features)
            )
    
    def disable_degradation(self, feature: str):
        """Disable degraded mode for a feature"""
        if feature in self.degraded_features:
            self.degraded_features.remove(feature)
            self.logger.info(
                f"Disabling degraded mode for {feature}",
                feature=feature,
                remaining_degraded=list(self.degraded_features)
            )
    
    def is_degraded(self, feature: str) -> bool:
        """Check if feature is in degraded mode"""
        return feature in self.degraded_features
    
    def get_degraded_features(self) -> list:
        """Get list of currently degraded features"""
        return list(self.degraded_features)


# Global instances for the API service
_error_middleware_instance = None
_degradation_manager = GracefulDegradationManager()


def get_error_middleware() -> ErrorHandlingMiddleware:
    """Get the global error middleware instance"""
    global _error_middleware_instance
    if _error_middleware_instance is None:
        # This will be set when the middleware is added to FastAPI
        raise RuntimeError("Error middleware not initialized")
    return _error_middleware_instance


def set_error_middleware(middleware: ErrorHandlingMiddleware):
    """Set the global error middleware instance"""
    global _error_middleware_instance
    _error_middleware_instance = middleware


def get_degradation_manager() -> GracefulDegradationManager:
    """Get the global degradation manager"""
    return _degradation_manager


# Utility functions for error handling

def create_error_response(
    error_type: str,
    message: str,
    status_code: int = 500,
    details: Any = None,
    request_id: str = "unknown"
) -> JSONResponse:
    """Create a standardized error response"""
    content = {
        "error": error_type,
        "message": message,
        "request_id": request_id,
        "timestamp": datetime.now().isoformat()
    }
    
    if details is not None:
        content["details"] = details
    
    return JSONResponse(status_code=status_code, content=content)


def handle_service_error(
    service_name: str,
    error: Exception,
    request_id: str,
    fallback_response: Any = None
) -> JSONResponse:
    """Handle errors from external services with optional fallback"""
    logger = get_structured_logger("api.service_errors", "rag-api")
    
    logger.log_exception(
        f"Error in {service_name} service",
        exception=error,
        service_name=service_name,
        request_id=request_id,
        has_fallback=fallback_response is not None
    )
    
    if fallback_response is not None:
        # Enable degraded mode and return fallback
        _degradation_manager.enable_degradation(
            service_name, f"Service error: {str(error)}"
        )
        
        return JSONResponse(
            status_code=200,
            content={
                "data": fallback_response,
                "degraded": True,
                "message": f"{service_name} service is temporarily degraded",
                "request_id": request_id,
                "timestamp": datetime.now().isoformat()
            }
        )
    else:
        # Return service unavailable
        return create_error_response(
            error_type="service_unavailable",
            message=f"{service_name} service is temporarily unavailable",
            status_code=503,
            request_id=request_id
        )