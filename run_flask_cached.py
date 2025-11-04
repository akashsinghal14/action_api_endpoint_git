#!/usr/bin/env python3
"""
Run script for Flask Fire Door Compliance API with Caching
Uses Flask with in-memory caching for performance optimization
"""

import os
from app_fastapi_optimized import app

if __name__ == '__main__':
    # Get port from environment variable (Azure App Service compatibility)
    port = int(os.environ.get('PORT', 5001))
    
    print("🚀 Starting Flask Fire Door Compliance API with Caching")
    print(f"📊 Port: {port}")
    print(f"🧠 AI Providers: OpenAI + Claude")
    print(f"💾 Caching: Enabled")
    print(f"⚡ Performance: Optimized with 24-hour cache")
    print("-" * 50)
    
    # Run the Flask app
    app.run(
        debug=True,
        host='0.0.0.0',
        port=port
    )
