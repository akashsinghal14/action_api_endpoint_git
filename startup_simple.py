#!/usr/bin/env python3
"""
Simple startup script for Azure App Service
"""
import os
import sys

print("Starting Azure App Service...")
print("Python version:", sys.version)
print("Current directory:", os.getcwd())
print("PORT environment variable:", os.environ.get('PORT', 'Not set'))

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

try:
    print("Importing app module...")
    from app import app
    print("App imported successfully!")
    
    # Get port from environment
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    
    print(f"Starting Flask app on port {port}, debug={debug_mode}")
    app.run(debug=debug_mode, host='0.0.0.0', port=port)
    
except Exception as e:
    print(f"Error starting app: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
