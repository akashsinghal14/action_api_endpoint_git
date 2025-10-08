#!/usr/bin/env python3
"""
Fire Door Survey API - Azure App Service Entry Point
"""
import sys
import os
import subprocess

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

# Try to install dependencies if they're missing
def install_dependencies():
    """Install dependencies if they're missing"""
    try:
        import flask
        print("Flask already available")
        return True
    except ImportError:
        print("Installing dependencies...")
        try:
            # Try different pip commands
            pip_commands = [
                [sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'],
                ['pip3', 'install', '-r', 'requirements.txt'],
                ['pip', 'install', '-r', 'requirements.txt']
            ]
            
            for cmd in pip_commands:
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                    if result.returncode == 0:
                        print(f"Dependencies installed successfully with: {' '.join(cmd)}")
                        return True
                    else:
                        print(f"Failed with {' '.join(cmd)}: {result.stderr}")
                except Exception as e:
                    print(f"Error with {' '.join(cmd)}: {e}")
                    continue
            
            print("All pip commands failed, trying to continue anyway...")
            return False
        except Exception as e:
            print(f"Error installing dependencies: {e}")
            return False

# Install dependencies before importing Flask
install_dependencies()

# Now import Flask and other dependencies
try:
    from flask import Flask, request, jsonify
    from flask_cors import CORS
    import openai
    import json
    import re
    from datetime import datetime, timedelta
    from typing import Dict, List, Any, Optional
    from dotenv import load_dotenv
    print("All dependencies imported successfully!")
except ImportError as e:
    print(f"Import error: {e}")
    print("Creating minimal Flask app...")
    
    # Create a minimal Flask app if dependencies fail
    from flask import Flask, request, jsonify
    from flask_cors import CORS
    import json
    import re
    from datetime import datetime, timedelta
    from typing import Dict, List, Any, Optional
    import os

# Load environment variables from .env file
try:
    load_dotenv()
except:
    pass

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# OpenAI Configuration
OPENAI_API_URL = 'https://api.openai.com/v1/chat/completions'

# API Key Mapping - Maps client keys to real OpenAI keys
API_KEY_MAPPING = {
    'YOUR_KEY': os.getenv('YOUR_KEY'),
    'DEV_KEY': os.getenv('DEV_KEY'),
    'PROD_KEY': os.getenv('PROD_KEY'),
    'TEST_KEY': os.getenv('TEST_KEY')
}

# Default AI model
DEFAULT_AI_MODEL = os.getenv('DEFAULT_AI_MODEL', 'gpt-3.5-turbo')

# Cost tracking
total_cost = 0
total_tokens = 0

# Rate limiting - 100 calls per minute
class RateLimiter:
    def __init__(self):
        self.calls = []  # Store timestamps of API calls
        self.max_calls = 100  # Maximum calls allowed
        self.time_window = 60  # Time window in seconds (1 minute)
    
    def can_make_call(self):
        import time
        now = time.time()
        
        # Remove calls older than 1 minute
        self.calls = [call_time for call_time in self.calls if now - call_time < self.time_window]
        
        # Check if we can make another call
        if len(self.calls) < self.max_calls:
            self.calls.append(now)
            return True
        return False
    
    def get_remaining_calls(self):
        """Get number of remaining calls in current window"""
        import time
        now = time.time()
        self.calls = [call_time for call_time in self.calls if now - call_time < self.time_window]
        return max(0, self.max_calls - len(self.calls))
    
    def get_reset_time(self):
        """Get seconds until rate limit resets"""
        import time
        if not self.calls:
            return 0
        now = time.time()
        oldest_call = min(self.calls)
        return max(0, self.time_window - (now - oldest_call))

rate_limiter = RateLimiter()

# Helper functions
def calculate_cost(model: str, tokens: int) -> float:
    """Calculate cost based on model and tokens used"""
    cost_per_1k_tokens = {
        'gpt-5': 0.06,
        'gpt-4': 0.03,
        'gpt-3.5-turbo': 0.002
    }
    return (tokens / 1000) * cost_per_1k_tokens.get(model, 0.002)

def get_due_date(severity: str) -> str:
    """Calculate due date based on severity level"""
    if severity == 'high':
        days = 7
    elif severity == 'medium':
        days = 14
    elif severity == 'low':
        days = 21
    else:
        days = 14  # Default to medium if severity is unknown
    
    date = datetime.now() + timedelta(days=days)
    return date.strftime('%d/%m/%Y')

def extract_cost_range(cost_string: str) -> Optional[Dict[str, int]]:
    """Extract cost range from cost string"""
    patterns = [
        r'£(\d+(?:,\d{3})*)-£(\d+(?:,\d{3})*)',  # £100-£200
        r'£(\d+(?:,\d{3})*)\s*\([^)]*\)',        # £100 (labor)
        r'£(\d+(?:,\d{3})*)'                     # £100
    ]
    
    min_cost = 0
    max_cost = 0
    found = False
    
    for pattern in patterns:
        matches = re.findall(pattern, cost_string)
        if matches:
            for match in matches:
                if isinstance(match, tuple):
                    value = int(match[0].replace(',', ''))
                else:
                    value = int(match.replace(',', ''))
                
                if not found:
                    min_cost = max_cost = value
                    found = True
                else:
                    min_cost = min(min_cost, value)
                    max_cost = max(max_cost, value)
    
    return {'min': min_cost, 'max': max_cost} if found else None

# API Endpoints

@app.route('/')
def health_check():
    """Simple health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'message': 'Fire Door Survey API is running',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0',
        'python_version': sys.version,
        'dependencies_loaded': True
    })

@app.route('/test')
def test_endpoint():
    """Simple test endpoint"""
    return jsonify({
        'message': 'Test endpoint working',
        'python_version': sys.version,
        'flask_available': True,
        'working_directory': os.getcwd(),
        'environment': dict(os.environ)
    })

@app.route('/api/action_item/validate-field', methods=['POST'])
def validate_field():
    """Validate individual form fields"""
    data = request.get_json()
    field_name = data.get('field_name')
    field_value = data.get('field_value')
    field_type = data.get('field_type', 'text')
    min_value = data.get('min_value')
    max_value = data.get('max_value')
    required = data.get('required', False)
    
    errors = []
    
    # Check if required field is empty
    if required and (not field_value or field_value == ''):
        errors.append(f'{field_name} is required')
        return jsonify({'valid': False, 'errors': errors})
    
    # Type-specific validation
    if field_type == 'number' and field_value:
        try:
            num_value = float(field_value)
            if min_value is not None and num_value < min_value:
                errors.append(f'{field_name} must be at least {min_value}')
            if max_value is not None and num_value > max_value:
                errors.append(f'{field_name} must be no more than {max_value}')
        except ValueError:
            errors.append(f'{field_name} must be a valid number')
    
    return jsonify({
        'valid': len(errors) == 0,
        'errors': errors
    })

# Helper function to resolve API keys
def resolve_api_key(client_key):
    """Resolve client-provided API key to actual OpenAI key"""
    if not client_key:
        return None
    
    # Check if it's a mapped key
    if client_key in API_KEY_MAPPING:
        real_key = API_KEY_MAPPING[client_key]
        if real_key and real_key.startswith('sk-'):
            return real_key
    
    # If it looks like a real OpenAI key, use it directly (for backward compatibility)
    if client_key.startswith('sk-'):
        return client_key
    
    # Invalid key
    return None

# Individual gap analysis endpoints for developers

@app.route('/api/action_item/head', methods=['POST'])
@app.route('/api/action_item/head/<value>/<unit>', methods=['GET'])
def analyze_head_gap(value=None, unit=None):
    """Analyze head gap measurement for compliance"""
    try:
        # Handle both POST (JSON body) and GET (path parameters)
        if request.method == 'POST':
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No data provided'}), 400
            value = data.get('value')
            unit = data.get('unit', 'mm')
            api_key = data.get('api_key')  # Optional AI key
            model = data.get('model', 'gpt-3.5-turbo')  # Optional AI model
        else:  # GET request with path parameters
            if value is None or unit is None:
                return jsonify({'error': 'Value and unit are required in URL path'}), 400
            api_key = request.args.get('api_key')  # Optional AI key from query params
            model = request.args.get('model', 'gpt-3.5-turbo')  # Optional AI model from query params
        
        if value is None:
            return jsonify({'error': 'Value is required'}), 400
        
        # Convert value to float for GET requests
        try:
            value = float(value)
        except (ValueError, TypeError):
            return jsonify({'error': 'Value must be a valid number'}), 400
        
        # Check compliance first
        max_gap = 4  # UK standard: maximum 4mm gap
        is_compliant = value <= max_gap
        
        # Static analysis (for compliant measurements or when AI is not available)
        action_items = []
        
        if not is_compliant:
            action_item = {
                'severity': 'high',
                'category': 'Head Gap Compliance',
                'dueDate': get_due_date('high'),
                'actionDescription': f'Head gap ({value}mm) exceeds maximum allowed ({max_gap}mm). This gap allows fire and smoke to pass through.',
                'remediationOptions': [
                    {
                        'option': 'Option 1: Quick Fix - Basic Strips',
                        'plan': 'Install basic intumescent strips at the head of the door. This is a temporary solution that may need replacement within 6-12 months.'
                    },
                    {
                        'option': 'Option 2: Standard Solution - Quality Strips',
                        'plan': 'Install high-quality intumescent strips with proper sealing at the head. Includes door alignment check and frame adjustment if needed.'
                    },
                    {
                        'option': 'Option 3: Comprehensive Fix - Complete Sealing System',
                        'plan': 'Install premium intumescent strips with smoke seals, complete door alignment, frame adjustment, and professional testing at the head.'
                    }
                ],
                'confidenceScore': 92
            }
            action_items.append(action_item)
        
        return jsonify({
            'success': True,
            'measurement_type': 'head_gap',
            'value': value,
            'unit': unit,
            'compliant': is_compliant,
            'max_allowed': max_gap,
            'severity': 'high' if not is_compliant else 'none',
            'actionItems': action_items,
            'recommendations': 'Immediate action required to reduce head gap to comply with UK fire safety standards' if not is_compliant else 'Head gap is within acceptable limits',
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'static'
        })
        
    except Exception as e:
        return jsonify({'error': f'Head gap analysis failed: {str(e)}'}), 500

# Add more endpoints as needed...

if __name__ == '__main__':
    # Azure App Service uses PORT environment variable
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    print(f"Starting Flask app on port {port}, debug={debug_mode}")
    app.run(debug=debug_mode, host='0.0.0.0', port=port)