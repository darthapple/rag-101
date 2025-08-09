"""
Rate Limiting Middleware

Provides rate limiting functionality for API endpoints using in-memory storage
with sliding window algorithm for accurate rate limiting.
"""

import asyncio
import time
import logging
from typing import Dict, Optional, Tuple
from collections import defaultdict, deque
from dataclasses import dataclass, field

from fastapi import HTTPException, status, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


@dataclass
class RateLimitConfig:
    """Rate limit configuration"""
    requests: int = 60  # Number of requests allowed
    period: int = 60    # Time period in seconds
    burst: int = 10     # Burst allowance


@dataclass
class ClientRequests:
    """Track requests for a client"""
    timestamps: deque = field(default_factory=deque)
    burst_count: int = 0
    last_reset: float = field(default_factory=time.time)


class RateLimiter:
    """
    In-memory rate limiter using sliding window algorithm
    """
    
    def __init__(self):
        """Initialize rate limiter"""
        self.logger = logging.getLogger("api.rate_limiter")
        self.clients: Dict[str, ClientRequests] = defaultdict(ClientRequests)
        self.lock = asyncio.Lock()
        
        # Cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
    
    def start_cleanup(self):
        """Start background cleanup task"""
        if not self._running:
            self._running = True
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    def stop_cleanup(self):
        """Stop background cleanup task"""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
    
    async def _cleanup_loop(self):
        """Background task to clean up old client records"""
        while self._running:
            try:
                await self._cleanup_old_records()
                await asyncio.sleep(300)  # Run every 5 minutes
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Rate limiter cleanup error: {e}")
                await asyncio.sleep(60)  # Wait 1 minute on error
    
    async def _cleanup_old_records(self):
        """Remove old client records to prevent memory leaks"""
        async with self.lock:
            current_time = time.time()
            expired_clients = []
            
            for client_id, client_data in self.clients.items():
                # Remove clients with no recent activity (1 hour)
                if current_time - client_data.last_reset > 3600:
                    expired_clients.append(client_id)
            
            for client_id in expired_clients:
                del self.clients[client_id]
            
            if expired_clients:
                self.logger.debug(f"Cleaned up {len(expired_clients)} expired rate limit records")
    
    def _get_client_id(self, request: Request) -> str:
        """
        Get client identifier for rate limiting
        
        Args:
            request: HTTP request
            
        Returns:
            str: Client identifier
        """
        # Try session ID first (if available)
        if hasattr(request.state, 'session_id') and request.state.session_id:
            return f"session:{request.state.session_id}"
        
        # Try Authorization header
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            session_id = auth_header[7:]
            return f"session:{session_id}"
        
        # Fall back to IP address
        client_ip = request.client.host if request.client else "unknown"
        forwarded_for = request.headers.get('X-Forwarded-For')
        if forwarded_for:
            client_ip = forwarded_for.split(',')[0].strip()
        
        return f"ip:{client_ip}"
    
    async def check_rate_limit(
        self, 
        request: Request, 
        config: RateLimitConfig
    ) -> Tuple[bool, Dict[str, any]]:
        """
        Check if request is within rate limit
        
        Args:
            request: HTTP request
            config: Rate limit configuration
            
        Returns:
            Tuple[bool, Dict]: (allowed, limit_info)
        """
        client_id = self._get_client_id(request)
        current_time = time.time()
        
        async with self.lock:
            client_data = self.clients[client_id]
            
            # Clean old timestamps (sliding window)
            cutoff_time = current_time - config.period
            while (client_data.timestamps and 
                   client_data.timestamps[0] < cutoff_time):
                client_data.timestamps.popleft()
            
            # Reset burst count if period has passed
            if current_time - client_data.last_reset >= config.period:
                client_data.burst_count = 0
                client_data.last_reset = current_time
            
            # Check limits
            request_count = len(client_data.timestamps)
            burst_allowed = client_data.burst_count < config.burst
            rate_allowed = request_count < config.requests
            
            # Prepare limit info
            limit_info = {
                'limit': config.requests,
                'remaining': max(0, config.requests - request_count),
                'reset_time': int(client_data.last_reset + config.period),
                'retry_after': None
            }
            
            # Check if request is allowed
            if rate_allowed or (burst_allowed and request_count < config.requests + config.burst):
                # Allow request
                client_data.timestamps.append(current_time)
                
                if not rate_allowed and burst_allowed:
                    # This is a burst request
                    client_data.burst_count += 1
                    limit_info['burst_used'] = client_data.burst_count
                
                return True, limit_info
            else:
                # Rate limit exceeded
                if client_data.timestamps:
                    # Calculate retry after based on oldest request
                    retry_after = int(client_data.timestamps[0] + config.period - current_time)
                    limit_info['retry_after'] = max(1, retry_after)
                else:
                    limit_info['retry_after'] = config.period
                
                return False, limit_info


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware for FastAPI
    """
    
    def __init__(self, app, default_config: Optional[RateLimitConfig] = None):
        """
        Initialize rate limit middleware
        
        Args:
            app: FastAPI application
            default_config: Default rate limit configuration
        """
        super().__init__(app)
        self.default_config = default_config or RateLimitConfig()
        self.rate_limiter = RateLimiter()
        
        # Start cleanup task
        self.rate_limiter.start_cleanup()
        
        # Path-specific configs
        self.path_configs: Dict[str, RateLimitConfig] = {}
    
    def set_path_config(self, path: str, config: RateLimitConfig):
        """
        Set rate limit config for specific path
        
        Args:
            path: API path pattern
            config: Rate limit configuration
        """
        self.path_configs[path] = config
    
    def _get_config_for_path(self, path: str) -> RateLimitConfig:
        """
        Get rate limit config for path
        
        Args:
            path: Request path
            
        Returns:
            RateLimitConfig: Configuration to use
        """
        # Check for exact matches first
        if path in self.path_configs:
            return self.path_configs[path]
        
        # Check for pattern matches
        for pattern, config in self.path_configs.items():
            if path.startswith(pattern):
                return config
        
        return self.default_config
    
    async def dispatch(self, request: Request, call_next):
        """
        Process request and apply rate limiting
        
        Args:
            request: HTTP request
            call_next: Next middleware/handler
            
        Returns:
            Response: HTTP response
        """
        # Skip rate limiting for certain paths
        excluded_paths = {
            '/health', '/health/ready', '/health/metrics',
            '/docs', '/redoc', '/openapi.json'
        }
        
        if request.url.path in excluded_paths:
            return await call_next(request)
        
        # Get rate limit config for this path
        config = self._get_config_for_path(request.url.path)
        
        # Check rate limit
        allowed, limit_info = await self.rate_limiter.check_rate_limit(request, config)
        
        if not allowed:
            # Rate limit exceeded
            headers = {
                'X-RateLimit-Limit': str(limit_info['limit']),
                'X-RateLimit-Remaining': '0',
                'X-RateLimit-Reset': str(limit_info['reset_time']),
            }
            
            if limit_info['retry_after']:
                headers['Retry-After'] = str(limit_info['retry_after'])
            
            return Response(
                content='{"error": "rate_limit_exceeded", "message": "Too many requests"}',
                status_code=429,
                headers=headers,
                media_type="application/json"
            )
        
        # Process request
        response = await call_next(request)
        
        # Add rate limit headers to successful responses
        response.headers['X-RateLimit-Limit'] = str(limit_info['limit'])
        response.headers['X-RateLimit-Remaining'] = str(limit_info['remaining'])
        response.headers['X-RateLimit-Reset'] = str(limit_info['reset_time'])
        
        return response


# Global rate limiter instance
_rate_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    """Get global rate limiter instance"""
    return _rate_limiter


# Dependency functions for FastAPI
async def check_rate_limit_dependency(
    request: Request,
    config: Optional[RateLimitConfig] = None
):
    """
    FastAPI dependency for rate limiting
    
    Args:
        request: HTTP request  
        config: Optional rate limit config
        
    Raises:
        HTTPException: If rate limit exceeded
    """
    limiter = get_rate_limiter()
    rate_config = config or RateLimitConfig()
    
    allowed, limit_info = await limiter.check_rate_limit(request, rate_config)
    
    if not allowed:
        headers = {
            'X-RateLimit-Limit': str(limit_info['limit']),
            'X-RateLimit-Remaining': '0', 
            'X-RateLimit-Reset': str(limit_info['reset_time'])
        }
        
        if limit_info['retry_after']:
            headers['Retry-After'] = str(limit_info['retry_after'])
        
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers=headers
        )


def create_rate_limit_dependency(config: RateLimitConfig):
    """
    Create a rate limit dependency with specific config
    
    Args:
        config: Rate limit configuration
        
    Returns:
        Callable: Rate limit dependency function
    """
    async def _rate_limit_dependency(request: Request):
        """Rate limit dependency with custom config"""
        return await check_rate_limit_dependency(request, config)
    
    return _rate_limit_dependency


# Pre-configured rate limits
document_upload_rate_limit = create_rate_limit_dependency(
    RateLimitConfig(requests=10, period=300, burst=3)  # 10 per 5 minutes, 3 burst
)

question_submit_rate_limit = create_rate_limit_dependency(
    RateLimitConfig(requests=30, period=60, burst=5)   # 30 per minute, 5 burst
)

session_create_rate_limit = create_rate_limit_dependency(
    RateLimitConfig(requests=5, period=300, burst=2)   # 5 per 5 minutes, 2 burst
)