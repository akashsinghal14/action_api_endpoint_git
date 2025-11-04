#!/usr/bin/env python3
"""
Run script for FastAPI optimized Fire Door Compliance API
Uses FastAPI with in-memory caching and Claude-only support
"""

import os
import uvicorn
from app_fastapi_optimized import app

if __name__ == '__main__':
    # Get port from environment variable (Azure App Service compatibility)
    port = int(os.environ.get('PORT', 5001))
    
    print("🚀 Starting FastAPI Optimized Fire Door Compliance API")
    print(f"📊 Port: {port}")
    print(f"🧠 AI Provider: Claude Only")
    print(f"💾 Caching: Enabled")
    print(f"⚡ Performance: Optimized")
    print("-" * 50)
    
    # Run the FastAPI app with uvicorn
    uvicorn.run(
        app,
        host='0.0.0.0',
        port=port,
        log_level='info',
        access_log=True
    )
