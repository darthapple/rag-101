"""
API Routers

Router modules for different API endpoints:
- Health checks and service status
- Session management
- Document processing
- Q&A interactions
- WebSocket connections
"""

from .health import router as health_router
from .sessions import router as sessions_router
from .documents import router as documents_router
from .questions import router as questions_router
from .websocket import router as websocket_router

__all__ = [
    "health_router",
    "sessions_router", 
    "documents_router",
    "questions_router",
    "websocket_router"
]