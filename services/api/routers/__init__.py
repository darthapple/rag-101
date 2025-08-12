"""
API Routers

Router modules for different API endpoints:
- Health checks and service status
- Session management
- Document processing
- Q&A interactions
- WebSocket connections
- NATS streams monitoring
"""

from .health import router as health_router
from .sessions import router as sessions_router
from .documents import router as documents_router
from .questions import router as questions_router
from .websocket import router as websocket_router
from .streams import router as streams_router

__all__ = [
    "health_router",
    "sessions_router", 
    "documents_router",
    "questions_router",
    "websocket_router",
    "streams_router"
]