"""
RAG-101 API Service Main Application

FastAPI application for the RAG system providing:
- Session management endpoints
- Document upload and processing
- Q&A interaction endpoints
- WebSocket connections for real-time answers
- Health checks and monitoring
"""

import asyncio
import logging
import sys
import os
from pathlib import Path
from typing import Dict, Any
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import uvicorn

# Add project root to Python path for shared imports
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from shared.config import get_config
from shared.websocket_manager import get_websocket_manager
from shared.session_manager import get_session_manager
from middleware.session_middleware import SessionMiddleware


# Global application state
app_state = {
    'start_time': datetime.now(),
    'websocket_manager': None,
    'session_manager': None,
    'nats_connected': False,
    'health_status': 'starting'
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager for startup and shutdown events
    """
    config = get_config()
    logger = logging.getLogger("api.lifespan")
    
    # Startup
    try:
        logger.info("Starting RAG API Service...")
        
        # Initialize Session manager
        app_state['session_manager'] = get_session_manager()
        session_manager_connected = await app_state['session_manager'].connect()
        
        if not session_manager_connected:
            logger.error("Failed to connect session manager")
            app_state['health_status'] = 'unhealthy'
        else:
            logger.info("Session manager connected successfully")
        
        # Initialize WebSocket manager
        app_state['websocket_manager'] = get_websocket_manager()
        websocket_manager_started = await app_state['websocket_manager'].start()
        
        if not websocket_manager_started:
            logger.error("Failed to start WebSocket manager")
            app_state['health_status'] = 'unhealthy'
        else:
            logger.info("WebSocket manager started successfully")
            app_state['nats_connected'] = True
            app_state['health_status'] = 'healthy' if session_manager_connected else 'degraded'
        
        logger.info(f"RAG API Service started on http://{config.host}:{config.port}")
        
        yield  # Application runs here
        
    except Exception as e:
        logger.error(f"Error during startup: {e}")
        app_state['health_status'] = 'unhealthy'
        yield
    
    # Shutdown
    finally:
        try:
            logger.info("Shutting down RAG API Service...")
            
            # Stop WebSocket manager
            if app_state['websocket_manager']:
                await app_state['websocket_manager'].stop()
            
            # Stop Session manager
            if app_state['session_manager']:
                await app_state['session_manager'].disconnect()
            
            app_state['health_status'] = 'stopped'
            logger.info("RAG API Service stopped")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")


def create_app() -> FastAPI:
    """
    Create and configure FastAPI application instance
    
    Returns:
        FastAPI: Configured application instance
    """
    config = get_config()
    
    # Create FastAPI app with metadata
    app = FastAPI(
        title="RAG-101 Medical Q&A API",
        description="""
        Retrieval-Augmented Generation API for medical document Q&A based on Brazilian clinical protocols (PCDT).
        
        Features:
        - Session-based Q&A interactions
        - Real-time WebSocket answer delivery  
        - Document upload and processing
        - Vector similarity search
        - Ephemeral messaging with TTL
        
        Architecture:
        - FastAPI with async endpoints
        - NATS JetStream for messaging
        - Milvus for vector search
        - Google Gemini for AI processing
        """,
        version="0.1.0",
        contact={
            "name": "RAG-101 Team",
            "email": "contact@rag101.example.com",
        },
        license_info={
            "name": "MIT License",
            "url": "https://opensource.org/licenses/MIT",
        },
        openapi_tags=[
            {
                "name": "health",
                "description": "Health checks and service status"
            },
            {
                "name": "sessions", 
                "description": "Session management for Q&A interactions"
            },
            {
                "name": "documents",
                "description": "Document upload and processing"
            },
            {
                "name": "questions",
                "description": "Q&A endpoints for medical queries"
            },
            {
                "name": "websocket",
                "description": "WebSocket connections for real-time answers"
            }
        ],
        lifespan=lifespan,
        docs_url="/docs" if not config.is_production() else None,
        redoc_url="/redoc" if not config.is_production() else None,
        openapi_url="/openapi.json" if not config.is_production() else None
    )
    
    # Configure middleware
    setup_middleware(app, config)
    
    # Setup exception handlers
    setup_exception_handlers(app)
    
    # Include routers
    setup_routers(app)
    
    return app


def setup_middleware(app: FastAPI, config):
    """Configure application middleware"""
    
    # Trusted host middleware (security)
    if config.is_production():
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=["*"]  # Configure properly in production
        )
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=config.cors_methods,
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Processing-Time"]
    )
    
    # Session validation middleware (optional auto-validation)
    app.add_middleware(
        SessionMiddleware,
        auto_validate=False  # Only validate when explicitly requested
    )
    
    # Custom request/response middleware
    @app.middleware("http")
    async def request_middleware(request: Request, call_next):
        """Custom middleware for logging and request processing"""
        start_time = datetime.now()
        request_id = f"req_{int(start_time.timestamp() * 1000)}"
        
        # Add request ID to state
        request.state.request_id = request_id
        request.state.start_time = start_time
        
        # Process request
        try:
            response = await call_next(request)
            
            # Add custom headers
            processing_time = (datetime.now() - start_time).total_seconds()
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Processing-Time"] = f"{processing_time:.3f}s"
            
            # Log request (only in development)
            if config.is_development():
                logger = logging.getLogger("api.requests")
                logger.info(
                    f"{request.method} {request.url.path} "
                    f"- {response.status_code} "
                    f"- {processing_time:.3f}s"
                )
            
            return response
            
        except Exception as e:
            # Log error
            logger = logging.getLogger("api.errors")
            logger.error(f"Request {request_id} failed: {e}", exc_info=True)
            raise


def setup_exception_handlers(app: FastAPI):
    """Setup global exception handlers"""
    
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Handle validation errors"""
        return JSONResponse(
            status_code=422,
            content={
                "error": "validation_error",
                "message": "Request validation failed",
                "details": exc.errors(),
                "request_id": getattr(request.state, 'request_id', 'unknown')
            }
        )
    
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """Handle general exceptions"""
        logger = logging.getLogger("api.errors")
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_server_error",
                "message": "An internal error occurred",
                "request_id": getattr(request.state, 'request_id', 'unknown')
            }
        )


def setup_routers(app: FastAPI):
    """Setup and include API routers"""
    
    # Import routers dynamically to avoid circular imports
    try:
        from routers.health import router as health_router
        from routers.sessions import router as sessions_router
        from routers.documents import router as documents_router
        from routers.questions import router as questions_router
        from routers.websocket import router as websocket_router
        
        # Include routers with prefixes
        app.include_router(
            health_router, 
            prefix="/health", 
            tags=["health"]
        )
        
        app.include_router(
            sessions_router, 
            prefix="/api/v1/sessions", 
            tags=["sessions"]
        )
        
        app.include_router(
            documents_router, 
            prefix="/api/v1/documents", 
            tags=["documents"]
        )
        
        app.include_router(
            questions_router, 
            prefix="/api/v1/questions", 
            tags=["questions"]
        )
        
        app.include_router(
            websocket_router, 
            prefix="/ws", 
            tags=["websocket"]
        )
        
    except ImportError as e:
        # Routers not implemented yet - create basic health endpoint
        logger = logging.getLogger("api.setup")
        logger.warning(f"Some routers not available yet: {e}")
        
        @app.get("/health", tags=["health"])
        async def basic_health():
            """Basic health check endpoint"""
            return {
                "status": app_state['health_status'],
                "service": "rag-api",
                "version": "0.1.0",
                "timestamp": datetime.now().isoformat(),
                "uptime": (datetime.now() - app_state['start_time']).total_seconds(),
                "websocket_manager": app_state['websocket_manager'] is not None,
                "nats_connected": app_state['nats_connected']
            }


def setup_logging():
    """Setup logging configuration"""
    config = get_config()
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, config.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('api.log') if config.environment == 'production' else logging.NullHandler()
        ]
    )
    
    # Set specific logger levels
    if config.environment == 'development':
        logging.getLogger('api').setLevel(logging.DEBUG)
        logging.getLogger('uvicorn.access').setLevel(logging.WARNING)
    elif config.environment == 'production':
        # Reduce noise in production
        logging.getLogger('uvicorn.access').setLevel(logging.WARNING)
        logging.getLogger('fastapi').setLevel(logging.WARNING)


def get_app_stats() -> Dict[str, Any]:
    """Get application statistics"""
    websocket_stats = {}
    if app_state['websocket_manager']:
        websocket_stats = app_state['websocket_manager'].get_stats()
    
    return {
        'service': 'rag-api',
        'version': '0.1.0',
        'status': app_state['health_status'],
        'start_time': app_state['start_time'].isoformat(),
        'uptime': (datetime.now() - app_state['start_time']).total_seconds(),
        'nats_connected': app_state['nats_connected'],
        'websocket_stats': websocket_stats
    }


# Create the FastAPI app instance
app = create_app()


def main():
    """Main entry point for running the API service"""
    setup_logging()
    config = get_config()
    
    logger = logging.getLogger("api.main")
    logger.info("Starting RAG API Service...")
    
    # Run with uvicorn
    uvicorn.run(
        "main:app",
        host=config.host,
        port=config.port,
        reload=config.reload and config.is_development(),
        log_level=config.log_level.lower(),
        access_log=config.is_development(),
        server_header=False,
        date_header=False
    )


if __name__ == "__main__":
    main()