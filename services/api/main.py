"""
RAG-101 API Service Main Application

FastAPI application for the RAG system providing:
- Session management endpoints with NATS KV storage
- Document upload and processing
- Q&A interaction endpoints
- WebSocket connections for real-time answers
- Health checks and monitoring
- Infrastructure initialization (NATS, Milvus)
"""

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional, List
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from simple_config import get_config
from shared.infrastructure import InfrastructureManager

# Import routers
from routers import documents, sessions, questions, health, websocket

# Import WebSocket manager
from shared.websocket_manager import get_websocket_manager

# Initialize configuration
config = get_config()

# Global infrastructure manager
infra_manager = None

# Note: Models and handlers are now in their respective routers

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global infra_manager
    
    # Startup
    try:
        # Create and initialize infrastructure manager
        infra_manager = InfrastructureManager(config, service_name="api")
        await infra_manager.initialize_all(require_all=False)
        
        # Initialize WebSocket manager
        websocket_manager = get_websocket_manager()
        websocket_started = await websocket_manager.start()
        if websocket_started:
            print("✅ WebSocket manager initialized successfully")
        else:
            print("⚠️ WebSocket manager initialization failed - real-time features may not work")
        
    except Exception as e:
        print(f"Warning: Infrastructure initialization failed: {e}")
        print("Running in degraded mode - some features may not work")
    
    yield
    
    # Shutdown
    try:
        # Stop WebSocket manager
        websocket_manager = get_websocket_manager()
        await websocket_manager.stop()
        print("WebSocket manager stopped")
    except Exception as e:
        print(f"Error stopping WebSocket manager: {e}")
    
    if infra_manager:
        await infra_manager.cleanup()

# Create FastAPI app
app = FastAPI(
    title="RAG-101 Medical Q&A API",
    description="Retrieval-Augmented Generation API for medical document Q&A with NATS and Milvus",
    version="0.1.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=config.cors_methods,
    allow_headers=["*"]
)

# Include routers
app.include_router(documents.router, prefix="/api/v1", tags=["documents"])
app.include_router(sessions.router, prefix="/api/v1/sessions", tags=["sessions"])
app.include_router(questions.router, prefix="/api/v1/questions", tags=["questions"])
app.include_router(health.router, prefix="/api/v1/health", tags=["health"])
app.include_router(websocket.router, prefix="/api/v1", tags=["websocket"])


# Health check endpoint
@app.get("/health")
async def health_check():
    """Comprehensive health check endpoint"""
    # Try to reconnect to Milvus if it's not connected
    if infra_manager and not infra_manager.initialization_status.get('milvus', {}).get('initialized', False):
        await infra_manager.retry_milvus_connection()
    
    return {
        "status": "healthy",
        "service": "rag-api",
        "version": "0.1.0",
        "timestamp": datetime.now().isoformat(),
        "environment": config.environment,
        "google_api_key_configured": bool(config.google_api_key),
        "infrastructure": infra_manager.get_status() if infra_manager else {"status": "not initialized"}
    }

# Basic info endpoint
@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "RAG-101 Medical Q&A API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
        "infrastructure_status": "initialized" if infra_manager else "not initialized"
    }

# Note: Session endpoints are now handled by the sessions router

# Note: Document endpoints are now handled by the documents router
# This removes the old file upload endpoint and uses URL-based document processing

# Note: Question endpoints are now handled by the questions router

# Note: WebSocket endpoints are now handled by the websocket router

def main():
    """Main entry point"""
    config = get_config()
    
    print(f"Starting RAG-101 API Server...")
    print(f"Environment: {config.environment}")
    print(f"Debug mode: {config.debug}")
    print(f"Google API Key configured: {bool(config.google_api_key)}")
    print(f"NATS URL: {config.nats_url}")
    print(f"Milvus: {config.milvus_host}:{config.milvus_port}")
    print(f"Server will start on http://{config.host}:{config.port}")
    
    # Run with uvicorn
    uvicorn.run(
        "main:app",
        host=config.host,
        port=config.port,
        reload=config.reload,
        log_level=config.log_level.lower()
    )

if __name__ == "__main__":
    main()