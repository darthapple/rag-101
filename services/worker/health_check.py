#!/usr/bin/env python3
"""
Health check script for worker service.
Returns exit code 0 if healthy, 1 if unhealthy.
"""

import sys
import asyncio
import os
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

async def check_health():
    """Check if worker service is healthy"""
    try:
        # Import required modules
        from shared.config import get_config
        from shared.infrastructure import InfrastructureManager
        
        config = get_config()
        
        # Check infrastructure health
        infra_manager = InfrastructureManager()
        health_status = await infra_manager.health_check()
        
        # Check if all services are healthy
        if not health_status.get("healthy", False):
            print(f"Unhealthy: {health_status}")
            return False
        
        print("healthy")
        return True
        
    except Exception as e:
        print(f"Health check failed: {e}")
        return False

if __name__ == "__main__":
    try:
        result = asyncio.run(check_health())
        sys.exit(0 if result else 1)
    except Exception:
        sys.exit(1)