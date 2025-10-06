#!/usr/bin/env python3
"""
Run script for Claude API implementation
Starts the Flask server on port 5001
"""

import os
import sys
from app_claude import app

def main():
    """Start the Claude API server"""
    print("Starting Claude API Server...")
    print("=" * 50)
    print("Port: 5001")
    print("Base URL: http://localhost:5001")
    print("API Endpoints: http://localhost:5001/api")
    print("=" * 50)
    print("\nAvailable endpoints:")
    print("- GET  /api/action_item/analyze-head-gap/<value>/<unit>")
    print("- GET  /api/action_item/analyze-hinge-gap/<value>/<unit>")
    print("- GET  /api/action_item/analyze-closing-gap/<value>/<unit>")
    print("- GET  /api/action_item/analyze-threshold-gap/<value>/<unit>")
    print("- GET  /api/action_item/analyze-door-thickness/<value>/<unit>")
    print("- POST /api/action_item/ai-analysis")
    print("- POST /api/action_item/contractor-recommendations")
    print("- POST /api/action_item/calculate-costs")
    print("- POST /api/action_item/validate-field")
    print("- POST /api/action_item/fallback-analysis")
    print("\nPress Ctrl+C to stop the server")
    print("=" * 50)
    
    try:
        app.run(debug=True, host='0.0.0.0', port=5001)
    except KeyboardInterrupt:
        print("\n\nServer stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"\nError starting server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
