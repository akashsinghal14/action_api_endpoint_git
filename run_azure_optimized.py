#!/usr/bin/env python3
"""
Run script for Azure-Optimized Flask Fire Door Compliance API
Specifically designed for Azure App Services deployment
"""

import os
from app_azure_optimized import app, start_cache_warming

if __name__ == '__main__':
    # Get port from environment variable (Azure App Service compatibility)
    port = int(os.environ.get('PORT', 5001))
    
    print("🚀 Starting Azure-Optimized Flask Fire Door Compliance API")
    print(f"📊 Port: {port}")
    print(f"🌍 Environment: {'Azure App Service' if os.getenv('WEBSITE_SITE_NAME') else 'Local'}")
    print(f"🧠 AI Providers: OpenAI + Claude")
    print(f"💾 Caching: Enabled (24-hour TTL)")
    print(f"🔥 Auto Warm: Enabled (Azure-optimized)")
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
