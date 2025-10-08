#!/usr/bin/env python3
"""
Azure App Service startup script with dependency installation
"""
import sys
import os
import subprocess

print("=== Azure App Service Startup ===")
print(f"Python version: {sys.version}")
print(f"Current directory: {os.getcwd()}")
print(f"PORT environment variable: {os.environ.get('PORT', 'Not set')}")

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

def install_dependencies():
    """Install dependencies if they're missing"""
    try:
        import flask
        print("✅ Flask already available")
        return True
    except ImportError:
        print("❌ Flask not found, installing dependencies...")
        
        # Try different pip commands
        pip_commands = [
            [sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'],
            ['pip3', 'install', '-r', 'requirements.txt'],
            ['pip', 'install', '-r', 'requirements.txt'],
            ['python3', '-m', 'pip', 'install', 'Flask==2.3.3', 'Flask-CORS==4.0.0']
        ]
        
        for cmd in pip_commands:
            try:
                print(f"Trying: {' '.join(cmd)}")
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                if result.returncode == 0:
                    print(f"✅ Dependencies installed successfully with: {' '.join(cmd)}")
                    return True
                else:
                    print(f"❌ Failed with {' '.join(cmd)}: {result.stderr}")
            except Exception as e:
                print(f"❌ Error with {' '.join(cmd)}: {e}")
                continue
        
        print("⚠️ All pip commands failed, trying to continue anyway...")
        return False

# Install dependencies
install_dependencies()

# Now try to import and run the app
try:
    print("Importing app...")
    from app import app
    
    # Get port from environment
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    
    print(f"✅ App imported successfully!")
    print(f"Starting Flask app on port {port}, debug={debug_mode}")
    
    app.run(debug=debug_mode, host='0.0.0.0', port=port)
    
except Exception as e:
    print(f"❌ Error starting app: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)