"""
Session Validation Middleware

Provides session validation middleware and dependency injection for FastAPI endpoints.
Integrates with NATS KV session storage for session lifecycle management.
"""

import logging
import sys
from pathlib import Path
from typing import Optional, Callable, Any

from fastapi import HTTPException, status, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

from shared.session_manager import (
    get_session_manager,
    Session,
    SessionManagerError,
    SessionNotFoundError,
    SessionExpiredError
)


logger = logging.getLogger("api.middleware.session")


class SessionRequired(Exception):
    """Exception raised when session is required but not provided or invalid"""
    pass


class SessionMiddleware(BaseHTTPMiddleware):
    """
    Middleware for automatic session validation and injection
    
    This middleware can optionally validate sessions for all requests
    or specific routes. It injects session information into the request state.
    """
    
    def __init__(self, app, auto_validate: bool = False):
        """
        Initialize session middleware
        
        Args:
            app: FastAPI application instance
            auto_validate: Whether to automatically validate sessions for all requests
        """
        super().__init__(app)
        self.auto_validate = auto_validate
        self.session_manager = get_session_manager()
        
        # Paths that don't require session validation
        self.excluded_paths = {
            "/health",
            "/health/ready",
            "/health/metrics", 
            "/health/version",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/api/v1/sessions"  # Session creation endpoint
        }
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request and optionally validate session
        
        Args:
            request: HTTP request
            call_next: Next middleware/endpoint handler
            
        Returns:
            Response: HTTP response
        """
        # Initialize session state
        request.state.session = None
        request.state.session_id = None
        request.state.session_valid = False
        
        # Skip validation for excluded paths
        if request.url.path in self.excluded_paths or request.url.path.startswith("/ws/"):
            return await call_next(request)
        
        # Extract session ID from various sources
        session_id = await self._extract_session_id(request)
        
        if session_id:
            request.state.session_id = session_id
            
            # Validate session if auto_validate is enabled or explicitly requested
            if self.auto_validate or self._should_validate_session(request):
                try:
                    session = await self._validate_session(session_id)
                    request.state.session = session
                    request.state.session_valid = True
                    
                    logger.debug(f"Session {session_id} validated for {request.url.path}")
                    
                except (SessionNotFoundError, SessionExpiredError) as e:
                    logger.debug(f"Session validation failed for {session_id}: {e}")
                    
                    # For auto-validation, return error immediately
                    if self.auto_validate:
                        return Response(
                            content=f'{{"error": "invalid_session", "message": "{str(e)}"}}',
                            status_code=401,
                            media_type="application/json"
                        )
                
                except SessionManagerError as e:
                    logger.error(f"Session validation error for {session_id}: {e}")
                    
                    if self.auto_validate:
                        return Response(
                            content='{"error": "session_service_error", "message": "Session validation failed"}',
                            status_code=503,
                            media_type="application/json"
                        )
        
        # Continue with request processing
        return await call_next(request)
    
    async def _extract_session_id(self, request: Request) -> Optional[str]:
        """
        Extract session ID from request headers, query parameters, or path
        
        Args:
            request: HTTP request
            
        Returns:
            Optional[str]: Session ID if found
        """
        # Check Authorization header (Bearer token format)
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header[7:]  # Remove "Bearer " prefix
        
        # Check X-Session-ID header
        session_header = request.headers.get("X-Session-ID")
        if session_header:
            return session_header
        
        # Check session_id query parameter
        session_param = request.query_params.get("session_id")
        if session_param:
            return session_param
        
        # Check if session_id is in path parameters (for dynamic routes)
        path_params = getattr(request, "path_params", {})
        if "session_id" in path_params:
            return path_params["session_id"]
        
        return None
    
    def _should_validate_session(self, request: Request) -> bool:
        """
        Determine if session should be validated for this request
        
        Args:
            request: HTTP request
            
        Returns:
            bool: True if session should be validated
        """
        # Validate for endpoints that typically require sessions
        session_required_patterns = [
            "/api/v1/questions",
            "/api/v1/documents/upload"
        ]
        
        return any(request.url.path.startswith(pattern) for pattern in session_required_patterns)
    
    async def _validate_session(self, session_id: str) -> Session:
        """
        Validate session using session manager
        
        Args:
            session_id: Session identifier
            
        Returns:
            Session: Validated session object
            
        Raises:
            SessionManagerError: If validation fails
        """
        # Ensure session manager is connected
        if not self.session_manager._connected:
            connected = await self.session_manager.connect()
            if not connected:
                raise SessionManagerError("Session service unavailable")
        
        # Validate session
        return await self.session_manager.get_session(session_id)


# FastAPI dependency functions
async def get_session_manager_dependency():
    """Dependency to get session manager instance"""
    session_manager = get_session_manager()
    
    # Ensure connection
    if not session_manager._connected:
        connected = await session_manager.connect()
        if not connected:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Session service unavailable"
            )
    
    return session_manager


def get_session_dependency(
    required: bool = True
) -> Callable:
    """
    Create a dependency function for session validation
    
    Args:
        required: Whether session is required (raises exception if not found)
        
    Returns:
        Callable: Dependency function
    """
    async def _get_session(request: Request) -> Optional[Session]:
        """
        Get validated session from request state or validate on-demand
        
        Args:
            request: HTTP request with session state
            
        Returns:
            Optional[Session]: Session object if valid
            
        Raises:
            HTTPException: If session is required but not valid
        """
        # Check if session was already validated by middleware
        if hasattr(request.state, 'session') and request.state.session:
            return request.state.session
        
        # Try to get session ID from request state or extract directly
        session_id = getattr(request.state, 'session_id', None)
        
        if not session_id:
            # Try to extract session ID directly
            session_id = await SessionMiddleware(None)._extract_session_id(request)
        
        if not session_id:
            if required:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session ID required but not provided"
                )
            return None
        
        # Validate session on-demand
        try:
            session_manager = await get_session_manager_dependency()
            session = await session_manager.get_session(session_id)
            
            # Cache in request state
            request.state.session = session
            request.state.session_valid = True
            
            return session
            
        except SessionNotFoundError:
            if required:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Session {session_id} not found"
                )
            return None
            
        except SessionExpiredError:
            if required:
                raise HTTPException(
                    status_code=status.HTTP_410_GONE,
                    detail=f"Session {session_id} has expired"
                )
            return None
            
        except SessionManagerError as e:
            logger.error(f"Session validation error: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Session validation failed"
            )
    
    return _get_session


# Pre-configured dependency instances
get_required_session = get_session_dependency(required=True)
get_optional_session = get_session_dependency(required=False)


# Alias for backward compatibility
def get_session_dependency_required() -> Callable:
    """Get session dependency that requires valid session"""
    return get_required_session


def get_optional_session_dependency() -> Callable:
    """Get session dependency that allows missing session"""
    return get_optional_session


# Bearer token extractor for session ID
bearer_scheme = HTTPBearer(auto_error=False)


async def get_session_from_bearer(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)
) -> Optional[Session]:
    """
    Extract session from Bearer token in Authorization header
    
    Args:
        request: HTTP request
        credentials: Bearer token credentials
        
    Returns:
        Optional[Session]: Session if valid bearer token provided
    """
    if not credentials:
        return None
    
    session_id = credentials.credentials
    
    try:
        session_manager = await get_session_manager_dependency()
        session = await session_manager.get_session(session_id)
        
        # Update session activity
        await session_manager.update_session(session)
        
        return session
        
    except (SessionNotFoundError, SessionExpiredError, SessionManagerError):
        return None


def create_session_validator(
    auto_extract: bool = True,
    required: bool = True,
    update_activity: bool = True
) -> Callable:
    """
    Create a custom session validator dependency
    
    Args:
        auto_extract: Whether to automatically extract session ID from request
        required: Whether to raise exception if session not found
        update_activity: Whether to update session activity on access
        
    Returns:
        Callable: Session validator dependency function
    """
    async def _validate_session(
        request: Request,
        session_manager = Depends(get_session_manager_dependency)
    ) -> Optional[Session]:
        """Custom session validation logic"""
        
        session_id = None
        
        if auto_extract:
            # Try multiple extraction methods
            middleware = SessionMiddleware(None)
            session_id = await middleware._extract_session_id(request)
        
        if not session_id and required:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session ID required"
            )
        
        if not session_id:
            return None
        
        try:
            session = await session_manager.get_session(session_id)
            
            # Update activity if requested
            if update_activity:
                await session_manager.update_session(session)
            
            return session
            
        except SessionNotFoundError:
            if required:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Session {session_id} not found"
                )
            return None
            
        except SessionExpiredError:
            if required:
                raise HTTPException(
                    status_code=status.HTTP_410_GONE,
                    detail=f"Session {session_id} has expired"
                )
            return None
            
        except SessionManagerError as e:
            logger.error(f"Session validation failed: {e}")
            if required:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Session service error"
                )
            return None
    
    return _validate_session