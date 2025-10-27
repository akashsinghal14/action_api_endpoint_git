"""
WSGI entry point for Azure App Service
"""
from application import app

if __name__ == "__main__":
    app.run()
