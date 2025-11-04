#!/usr/bin/env python3
"""
Run script for Flask Fire Door Compliance API with Auto Cache Warming
Automatically warms cache on startup for Azure App Services deployment
"""

import os
from app_with_auto_warming import app, start_cache_warming

if __name__ == '__main__':
    # Get port from environment variable (Azure App Service compatibility)
    port = int(os.environ.get('PORT', 5001))
    
    print("🚀 Starting Flask Fire Door Compliance API with Auto Cache Warming")
    print(f"📊 Port: {port}")
    print(f"🧠 AI Providers: OpenAI + Claude")
    print(f"💾 Caching: Enabled (24-hour TTL)")
    print(f"🔥 Auto Warm: Enabled (will warm during startup)")
    print("-" * 50)
    
    # Start cache warming during app initialization
    start_cache_warming()
    
    # Run the Flask app
    app.run(
        debug=False,  # Set to False for production
        host='0.0.0.0',
        port=port,
        use_reloader=False  # Disable reloader to prevent issues with cache warming
    )
