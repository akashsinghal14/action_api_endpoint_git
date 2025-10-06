#!/usr/bin/env python3
"""
Startup script for the Fire Door Survey API
"""

import subprocess
import sys
import os
import webbrowser
import time
import threading

def check_dependencies():
    """Check if required dependencies are installed"""
    try:
        import flask
        import flask_cors
        import openai
        print("✅ All dependencies are installed")
        return True
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("Please run: pip install -r requirements.txt")
        return False

def start_flask_server():
    """Start the Flask server"""
    print("🚀 Starting Flask server...")
    try:
        subprocess.run([sys.executable, "app.py"], check=True)
    except KeyboardInterrupt:
        print("\n🛑 Flask server stopped")
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to start Flask server: {e}")

def open_frontend():
    """Open the frontend in the default browser"""
    time.sleep(2)  # Wait for server to start
    frontend_path = os.path.abspath("frontend.html")
    webbrowser.open(f"file://{frontend_path}")
    print("🌐 Frontend opened in browser")

def main():
    """Main startup function"""
    print("Fire Door Survey API - Startup Script")
    print("=" * 40)
    
    # Check dependencies
    if not check_dependencies():
        return
    
    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=start_flask_server)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Open frontend in browser
    open_frontend()
    
    print("\n📋 Instructions:")
    print("1. The Flask server is running on http://localhost:5000")
    print("2. The frontend should open automatically in your browser")
    print("3. If the frontend doesn't open, manually open frontend.html")
    print("4. Press Ctrl+C to stop the server")
    
    try:
        # Keep the main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")

if __name__ == "__main__":
    main()
