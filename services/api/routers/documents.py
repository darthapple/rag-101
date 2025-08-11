"""
Documents Router - Simplified

Handles document URL submission by publishing to NATS topics.
"""

import logging
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.append(str(project_root))

from shared.messaging import get_nats_client

router = APIRouter()
logger = logging.getLogger("api.documents")


@router.post("/document-download")
async def submit_urls(urls: list[str]):
    """
    Submit PDF URLs to download topic for worker processing
    
    Args:
        urls: List of PDF URLs to download
        
    Returns:
        Simple confirmation message
    """
    try:
        nats_client = get_nats_client()
        
        for url in urls:
            await nats_client.publish_message("documents.download", {"url": url})
            logger.info(f"Published URL to download topic: {url}")
        
        return {"submitted": len(urls)}
        
    except Exception as e:
        logger.error(f"Failed to submit URLs: {e}")
        raise HTTPException(status_code=500, detail="Failed to submit URLs")


@router.get("/health")
async def health():
    """Basic health check"""
    return {"status": "ok", "service": "documents"}