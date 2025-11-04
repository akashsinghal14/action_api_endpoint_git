#!/usr/bin/env python3
"""
Run script for optimized Fire Door Compliance API
Uses Quart (async Flask) with in-memory caching and Claude-only support
"""

import os
import sys
from app_optimized import app

if __name__ == '__main__':
    # Get port from environment variable (Azure App Service compatibility)
    port = int(os.environ.get('PORT', 5001))
    
    print("🚀 Starting Optimized Fire Door Compliance API")
    print(f"📊 Port: {port}")
    print(f"🧠 AI Provider: Claude Only")
    print(f"💾 Caching: Enabled")
    print(f"⚡ Performance: Optimized")
    print("-" * 50)
    
    # Run the Quart app
    app.run(
        debug=True,
        host='0.0.0.0',
        port=port,
        use_reloader=False  # Disable reloader for better performance
    )