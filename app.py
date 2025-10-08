from flask import Flask, request, jsonify
from flask_cors import CORS
import openai
import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

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

# Helper function for AI analysis of individual measurements
def analyze_gap_with_ai(gap_type, value, unit, api_key, model):
    """Analyze a single gap measurement using AI"""
    try:
        # Create a minimal survey data structure for AI analysis
        survey_data = {
            f'{gap_type}Gap': value,
            'fireResistance': 'Unknown',  # Default values for AI context
            'doorThickness': 44,
            'intumescentStrips': False,
            'selfClosingDevice': False,
            'keepShutSign': False,
            'holdOpenDevice': False,
            'certificationVisible': False,
            'containsGlazing': False,
            'pyroGlazing': False,
            'comments': f'Individual {gap_type} gap measurement analysis'
        }
        
        # Create AI prompt for single measurement
        prompt = create_openai_prompt(survey_data)
        
        # Call OpenAI API
        response = openai.ChatCompletion.create(
            model=model,
            messages=[
                {
                    'role': 'system',
                    'content': f'You are a UK fire safety expert specializing in fire door compliance. Analyze this {gap_type} gap measurement and provide action items in the EXACT JSON format specified. Focus specifically on the {gap_type} gap measurement provided. Make sure to use latest UK fire safety standards and regulations. Be thorough and professional.'
                },
                {
                    'role': 'user',
                    'content': prompt
                }
            ],
            temperature=0.3,
            max_tokens=1000,
            api_key=api_key
        )
        
        # Parse AI response
        ai_response = response.choices[0].message.content
        action_items = parse_openai_response(ai_response)
        
        # Calculate compliance based on measurement type
        if gap_type == 'door_thickness':
            min_thickness = 44
            compliant = value >= min_thickness
            max_gap = None  # Not applicable for thickness
        else:
            max_gap = 4
            compliant = value <= max_gap
            min_thickness = None  # Not applicable for gaps
        
        # Extract severity from AI action items (use highest severity if multiple items)
        ai_severity = 'none'
        if action_items:
            severities = [item.get('severity', 'low') for item in action_items]
            # Priority: high > medium > low
            if 'high' in severities:
                ai_severity = 'high'
            elif 'medium' in severities:
                ai_severity = 'medium'
            elif 'low' in severities:
                ai_severity = 'low'
        
        # Prepare response based on measurement type
        if gap_type == 'door_thickness':
            return {
                'success': True,
                'measurement_type': 'door_thickness',
                'value': value,
                'unit': unit,
                'compliant': compliant,
                'min_required': min_thickness,
                'severity': ai_severity if not compliant else 'none',
                'actionItems': action_items,
                'recommendations': f'AI-powered analysis of door thickness measurement',
                'timestamp': datetime.now().isoformat(),
                'analysis_type': 'ai',
                'ai_model': model,
                'tokens_used': response.usage.total_tokens if hasattr(response, 'usage') else 0
            }
        else:
            return {
                'success': True,
                'measurement_type': f'{gap_type}_gap',
                'value': value,
                'unit': unit,
                'compliant': compliant,
                'max_allowed': max_gap,
                'severity': ai_severity if not compliant else 'none',
                'actionItems': action_items,
                'recommendations': f'AI-powered analysis of {gap_type} gap measurement',
                'timestamp': datetime.now().isoformat(),
                'analysis_type': 'ai',
                'ai_model': model,
                'tokens_used': response.usage.total_tokens if hasattr(response, 'usage') else 0
            }
        
    except Exception as e:
        print(f"AI analysis error: {e}")
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
        
        # Try AI analysis only if measurement is non-compliant and API key is provided
        if api_key and not is_compliant:
            # Check rate limit for AI analysis
            if not rate_limiter.can_make_call():
                remaining_calls = rate_limiter.get_remaining_calls()
                reset_time = rate_limiter.get_reset_time()
                return jsonify({
                    'error': 'Rate limit exceeded. Maximum 100 calls per minute allowed.',
                    'remaining_calls': remaining_calls,
                    'reset_in_seconds': reset_time,
                    'rate_limit': {
                        'max_calls': 100,
                        'time_window': '1 minute',
                        'remaining': remaining_calls,
                        'resets_in': f"{reset_time} seconds"
                    }
                }), 429
            
            # Resolve the client API key to actual OpenAI key
            real_api_key = resolve_api_key(api_key)
            if real_api_key:
                try:
                    ai_result = analyze_gap_with_ai('head', value, unit, real_api_key, model)
                    if ai_result:
                        return jsonify(ai_result)
                except Exception as e:
                    print(f"AI analysis failed, falling back to static analysis: {e}")
            else:
                print(f"Invalid API key provided: {api_key}")
        
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
            'analysis_type': 'ai' if (api_key and not is_compliant) else 'static'
        })
        
    except Exception as e:
        return jsonify({'error': f'Head gap analysis failed: {str(e)}'}), 500

@app.route('/api/action_item/hinge', methods=['POST'])
@app.route('/api/action_item/hinge/<value>/<unit>', methods=['GET'])
def analyze_hinge_gap(value=None, unit=None):
    """Analyze hinge gap measurement for compliance"""
    try:
        # Handle both POST (JSON body) and GET (path parameters)
        if request.method == 'POST':
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No data provided'}), 400
            value = data.get('value')
            unit = data.get('unit', 'mm')
            api_key = data.get('api_key')  # Optional AI key
            model = data.get('model', DEFAULT_AI_MODEL)  # Optional AI model
        else:  # GET request with path parameters
            if value is None or unit is None:
                return jsonify({'error': 'Value and unit are required in URL path'}), 400
            api_key = request.args.get('api_key')  # Optional AI key from query params
            model = request.args.get('model', DEFAULT_AI_MODEL)  # Optional AI model from query params
        
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
        
        # Try AI analysis only if measurement is non-compliant and API key is provided
        if api_key and not is_compliant:
            # Check rate limit for AI analysis
            if not rate_limiter.can_make_call():
                remaining_calls = rate_limiter.get_remaining_calls()
                reset_time = rate_limiter.get_reset_time()
                return jsonify({
                    'error': 'Rate limit exceeded. Maximum 100 calls per minute allowed.',
                    'remaining_calls': remaining_calls,
                    'reset_in_seconds': reset_time,
                    'rate_limit': {
                        'max_calls': 100,
                        'time_window': '1 minute',
                        'remaining': remaining_calls,
                        'resets_in': f"{reset_time} seconds"
                    }
                }), 429
            
            # Resolve the client API key to actual OpenAI key
            real_api_key = resolve_api_key(api_key)
            if real_api_key:
                try:
                    ai_result = analyze_gap_with_ai('hinge', value, unit, real_api_key, model)
                    if ai_result:
                        return jsonify(ai_result)
                except Exception as e:
                    print(f"AI analysis failed, falling back to static analysis: {e}")
            else:
                print(f"Invalid API key provided: {api_key}")
        
        # Static analysis (for compliant measurements or when AI is not available)
        action_items = []
        
        if not is_compliant:
            action_item = {
                'severity': 'high',
                'category': 'Hinge Gap Compliance',
                'dueDate': get_due_date('high'),
                'actionDescription': f'Hinge gap ({value}mm) exceeds maximum allowed ({max_gap}mm). This gap allows fire and smoke to pass through.',
                'remediationOptions': [
                    {
                        'option': 'Option 1: Quick Fix - Basic Strips',
                        'plan': 'Install basic intumescent strips at the hinge side of the door. Temporary solution requiring monitoring.'
                    },
                    {
                        'option': 'Option 2: Standard Solution - Quality Strips + Alignment',
                        'plan': 'Install high-quality intumescent strips and check hinge alignment. Adjust hinges if necessary for proper sealing.'
                    },
                    {
                        'option': 'Option 3: Comprehensive Fix - Complete Hinge System',
                        'plan': 'Install premium intumescent strips, complete hinge alignment, frame adjustment, and professional testing. May include hinge replacement if needed.'
                    }
                ],
                'confidenceScore': 92
            }
            action_items.append(action_item)
        
        return jsonify({
            'success': True,
            'measurement_type': 'hinge_gap',
            'value': value,
            'unit': unit,
            'compliant': is_compliant,
            'max_allowed': max_gap,
            'severity': 'high' if not is_compliant else 'none',
            'actionItems': action_items,
            'recommendations': 'Immediate action required to reduce hinge gap to comply with UK fire safety standards' if not is_compliant else 'Hinge gap is within acceptable limits',
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'ai' if (api_key and not is_compliant) else 'static'
        })
        
    except Exception as e:
        return jsonify({'error': f'Hinge gap analysis failed: {str(e)}'}), 500

@app.route('/api/action_item/closing', methods=['POST'])
@app.route('/api/action_item/closing/<value>/<unit>', methods=['GET'])
def analyze_closing_gap(value=None, unit=None):
    """Analyze closing gap measurement for compliance"""
    try:
        # Handle both POST (JSON body) and GET (path parameters)
        if request.method == 'POST':
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No data provided'}), 400
            value = data.get('value')
            unit = data.get('unit', 'mm')
            api_key = data.get('api_key')  # Optional AI key
            model = data.get('model', DEFAULT_AI_MODEL)  # Optional AI model
        else:  # GET request with path parameters
            if value is None or unit is None:
                return jsonify({'error': 'Value and unit are required in URL path'}), 400
            api_key = request.args.get('api_key')  # Optional AI key from query params
            model = request.args.get('model', DEFAULT_AI_MODEL)  # Optional AI model from query params
        
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
        
        # Try AI analysis only if measurement is non-compliant and API key is provided
        if api_key and not is_compliant:
            # Check rate limit for AI analysis
            if not rate_limiter.can_make_call():
                remaining_calls = rate_limiter.get_remaining_calls()
                reset_time = rate_limiter.get_reset_time()
                return jsonify({
                    'error': 'Rate limit exceeded. Maximum 100 calls per minute allowed.',
                    'remaining_calls': remaining_calls,
                    'reset_in_seconds': reset_time,
                    'rate_limit': {
                        'max_calls': 100,
                        'time_window': '1 minute',
                        'remaining': remaining_calls,
                        'resets_in': f"{reset_time} seconds"
                    }
                }), 429
            
            # Resolve the client API key to actual OpenAI key
            real_api_key = resolve_api_key(api_key)
            if real_api_key:
                try:
                    ai_result = analyze_gap_with_ai('closing', value, unit, real_api_key, model)
                    if ai_result:
                        return jsonify(ai_result)
                except Exception as e:
                    print(f"AI analysis failed, falling back to static analysis: {e}")
            else:
                print(f"Invalid API key provided: {api_key}")
        
        # Static analysis (for compliant measurements or when AI is not available)
        action_items = []
        
        if not is_compliant:
            action_item = {
                'severity': 'high',
                'category': 'Closing Gap Compliance',
                'dueDate': get_due_date('high'),
                'actionDescription': f'Closing gap ({value}mm) exceeds maximum allowed ({max_gap}mm). This gap allows fire and smoke to pass through.',
                'remediationOptions': [
                    {
                        'option': 'Option 1: Quick Fix - Basic Strips',
                        'plan': 'Install basic intumescent strips at the closing edge of the door. Temporary solution for immediate compliance.'
                    },
                    {
                        'option': 'Option 2: Standard Solution - Quality Strips + Alignment',
                        'plan': 'Install high-quality intumescent strips with proper door alignment and frame adjustment. Includes re-measurement.'
                    },
                    {
                        'option': 'Option 3: Comprehensive Fix - Complete Sealing System',
                        'plan': 'Install premium intumescent strips with smoke seals, complete door alignment, frame adjustment, and professional testing. Includes warranty and follow-up inspection.'
                    }
                ],
                'confidenceScore': 92
            }
            action_items.append(action_item)
        
        return jsonify({
            'success': True,
            'measurement_type': 'closing_gap',
            'value': value,
            'unit': unit,
            'compliant': is_compliant,
            'max_allowed': max_gap,
            'severity': 'high' if not is_compliant else 'none',
            'actionItems': action_items,
            'recommendations': 'Immediate action required to reduce closing gap to comply with UK fire safety standards' if not is_compliant else 'Closing gap is within acceptable limits',
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'ai' if (api_key and not is_compliant) else 'static'
        })
        
    except Exception as e:
        return jsonify({'error': f'Closing gap analysis failed: {str(e)}'}), 500

@app.route('/api/action_item/threshold', methods=['POST'])
@app.route('/api/action_item/threshold/<value>/<unit>', methods=['GET'])
def analyze_threshold_gap(value=None, unit=None):
    """Analyze threshold gap measurement for compliance"""
    try:
        # Handle both POST (JSON body) and GET (path parameters)
        if request.method == 'POST':
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No data provided'}), 400
            value = data.get('value')
            unit = data.get('unit', 'mm')
            api_key = data.get('api_key')  # Optional AI key
            model = data.get('model', DEFAULT_AI_MODEL)  # Optional AI model
        else:  # GET request with path parameters
            if value is None or unit is None:
                return jsonify({'error': 'Value and unit are required in URL path'}), 400
            api_key = request.args.get('api_key')  # Optional AI key from query params
            model = request.args.get('model', DEFAULT_AI_MODEL)  # Optional AI model from query params
        
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
        
        # Try AI analysis only if measurement is non-compliant and API key is provided
        if api_key and not is_compliant:
            # Check rate limit for AI analysis
            if not rate_limiter.can_make_call():
                remaining_calls = rate_limiter.get_remaining_calls()
                reset_time = rate_limiter.get_reset_time()
                return jsonify({
                    'error': 'Rate limit exceeded. Maximum 100 calls per minute allowed.',
                    'remaining_calls': remaining_calls,
                    'reset_in_seconds': reset_time,
                    'rate_limit': {
                        'max_calls': 100,
                        'time_window': '1 minute',
                        'remaining': remaining_calls,
                        'resets_in': f"{reset_time} seconds"
                    }
                }), 429
            
            # Resolve the client API key to actual OpenAI key
            real_api_key = resolve_api_key(api_key)
            if real_api_key:
                try:
                    ai_result = analyze_gap_with_ai('threshold', value, unit, real_api_key, model)
                    if ai_result:
                        return jsonify(ai_result)
                except Exception as e:
                    print(f"AI analysis failed, falling back to static analysis: {e}")
            else:
                print(f"Invalid API key provided: {api_key}")
        
        # Static analysis (for compliant measurements or when AI is not available)
        action_items = []
        
        if not is_compliant:
            action_item = {
                'severity': 'high',
                'category': 'Threshold Gap Compliance',
                'dueDate': get_due_date('high'),
                'actionDescription': f'Threshold gap ({value}mm) exceeds maximum allowed ({max_gap}mm). This gap allows fire and smoke to pass through.',
                'remediationOptions': [
                    {
                        'option': 'Option 1: Quick Fix - Basic Threshold Seal',
                        'plan': 'Install basic threshold seal at the bottom of the door. Temporary solution that may need replacement within 6-12 months.'
                    },
                    {
                        'option': 'Option 2: Standard Solution - Quality Threshold System',
                        'plan': 'Install high-quality threshold seals with intumescent strips. Includes door alignment check and frame adjustment.'
                    },
                    {
                        'option': 'Option 3: Comprehensive Fix - Complete Threshold System',
                        'plan': 'Install premium threshold seals with intumescent strips, complete door alignment, frame adjustment, and professional testing. Includes warranty and maintenance plan.'
                    }
                ],
                'confidenceScore': 92
            }
            action_items.append(action_item)
        
        return jsonify({
            'success': True,
            'measurement_type': 'threshold_gap',
            'value': value,
            'unit': unit,
            'compliant': is_compliant,
            'max_allowed': max_gap,
            'severity': 'high' if not is_compliant else 'none',
            'actionItems': action_items,
            'recommendations': 'Immediate action required to reduce threshold gap to comply with UK fire safety standards' if not is_compliant else 'Threshold gap is within acceptable limits',
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'ai' if (api_key and not is_compliant) else 'static'
        })
        
    except Exception as e:
        return jsonify({'error': f'Threshold gap analysis failed: {str(e)}'}), 500

# Compliance check endpoint removed as requested

@app.route('/api/action_item/doorthick', methods=['POST'])
@app.route('/api/action_item/doorthick/<value>/<unit>', methods=['GET'])
def analyze_door_thickness(value=None, unit=None):
    """Analyze door thickness for compliance"""
    try:
        # Handle both POST (JSON body) and GET (path parameters)
        if request.method == 'POST':
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No data provided'}), 400
            value = data.get('value')
            unit = data.get('unit', 'mm')
            api_key = data.get('api_key')  # Optional AI key
            model = data.get('model', DEFAULT_AI_MODEL)  # Optional AI model
        else:  # GET request with path parameters
            if value is None or unit is None:
                return jsonify({'error': 'Value and unit are required in URL path'}), 400
            api_key = request.args.get('api_key')  # Optional AI key from query params
            model = request.args.get('model', DEFAULT_AI_MODEL)  # Optional AI model from query params
        
        if value is None:
            return jsonify({'error': 'Value is required'}), 400
        
        # Convert value to float for GET requests
        try:
            value = float(value)
        except (ValueError, TypeError):
            return jsonify({'error': 'Value must be a valid number'}), 400
        
        # Check compliance first
        min_thickness = 44  # UK standard: minimum 44mm thickness
        is_compliant = value >= min_thickness
        
        # Try AI analysis only if measurement is non-compliant and API key is provided
        if api_key and not is_compliant:
            # Check rate limit for AI analysis
            if not rate_limiter.can_make_call():
                remaining_calls = rate_limiter.get_remaining_calls()
                reset_time = rate_limiter.get_reset_time()
                return jsonify({
                    'error': 'Rate limit exceeded. Maximum 100 calls per minute allowed.',
                    'remaining_calls': remaining_calls,
                    'reset_in_seconds': reset_time,
                    'rate_limit': {
                        'max_calls': 100,
                        'time_window': '1 minute',
                        'remaining': remaining_calls,
                        'resets_in': f"{reset_time} seconds"
                    }
                }), 429
            
            # Resolve the client API key to actual OpenAI key
            real_api_key = resolve_api_key(api_key)
            if real_api_key:
                try:
                    ai_result = analyze_gap_with_ai('door_thickness', value, unit, real_api_key, model)
                    if ai_result:
                        return jsonify(ai_result)
                except Exception as e:
                    print(f"AI analysis failed, falling back to static analysis: {e}")
            else:
                print(f"Invalid API key provided: {api_key}")
        
        # Static analysis (for compliant measurements or when AI is not available)
        action_items = []
        
        if not is_compliant:
            action_item = {
                'severity': 'medium',
                'category': 'Door Thickness Compliance',
                'dueDate': get_due_date('medium'),
                'actionDescription': f'Door thickness ({value}mm) is below recommended minimum for fire doors ({min_thickness}mm). This may affect fire resistance performance.',
                'remediationOptions': [
                    {
                        'option': 'Option 1: Assessment & Verification',
                        'plan': 'Contact the door manufacturer to verify if the door meets fire resistance requirements despite the reduced thickness. Obtain certification documentation.'
                    },
                    {
                        'option': 'Option 2: Door Replacement',
                        'plan': 'Replace door with properly certified fire door meeting minimum thickness requirements. Includes removal and installation.'
                    },
                    {
                        'option': 'Option 3: Professional Assessment & Upgrade',
                        'plan': 'Conduct comprehensive fire safety assessment, obtain professional certification, and implement necessary upgrades to meet compliance standards.'
                    }
                ],
                'confidenceScore': 85
            }
            action_items.append(action_item)
        
        return jsonify({
            'success': True,
            'measurement_type': 'door_thickness',
            'value': value,
            'unit': unit,
            'compliant': is_compliant,
            'min_required': min_thickness,
            'severity': 'medium' if not is_compliant else 'none',
            'actionItems': action_items,
            'recommendations': 'Door thickness below recommended minimum - verification or replacement may be required' if not is_compliant else 'Door thickness meets minimum requirements',
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'ai' if (api_key and not is_compliant) else 'static'
        })
        
    except Exception as e:
        return jsonify({'error': f'Door thickness analysis failed: {str(e)}'}), 500

@app.route('/api/action_item/ai-analysis', methods=['POST'])
def ai_analysis():
    """Generate AI-powered action items using OpenAI"""
    data = request.get_json()
    survey_data = data.get('survey_data')
    api_key = data.get('api_key')
    model = data.get('model', 'gpt-3.5-turbo')
    
    if not api_key:
        return jsonify({'error': 'API key is required'}), 400
    
    if not rate_limiter.can_make_call():
        remaining_calls = rate_limiter.get_remaining_calls()
        reset_time = rate_limiter.get_reset_time()
        return jsonify({
            'error': 'Rate limit exceeded. Maximum 100 calls per minute allowed.',
            'remaining_calls': remaining_calls,
            'reset_in_seconds': reset_time,
            'rate_limit': {
                'max_calls': 100,
                'time_window': '1 minute',
                'remaining': remaining_calls,
                'resets_in': f"{reset_time} seconds"
            }
        }), 429
    
    try:
        # Create OpenAI prompt
        prompt = create_openai_prompt(survey_data)
        
        # Call OpenAI API
        response = openai.ChatCompletion.create(
            model=model,
            messages=[
                {
                    'role': 'system',
                    'content': f'You are a UK fire safety expert specializing in fire door compliance. Analyze the survey data and provide action items in the EXACT JSON format specified. Make sure to use latest UK fire safety standards and regulations. Be thorough, professional and detailed wherever required. {f"As {model}, provide the most comprehensive and accurate analysis possible with enhanced reasoning capabilities." if model == "gpt-5" else ""}'
                },
                {
                    'role': 'user',
                    'content': prompt
                }
            ],
            temperature=0.3,
            max_tokens=2000,
            api_key=api_key
        )
        
        # Track costs
        tokens_used = response.usage.total_tokens
        cost = calculate_cost(model, tokens_used)
        
        # Parse response
        action_items = parse_openai_response(response.choices[0].message.content)
        
        return jsonify({
            'actionItems': action_items,
            'cost': cost,
            'tokens': tokens_used,
            'model': model
        })
        
    except Exception as e:
        return jsonify({'error': f'AI analysis failed: {str(e)}'}), 500

@app.route('/api/action_item/fallback-analysis', methods=['POST'])
def fallback_analysis():
    """Generate rule-based action items as fallback"""
    data = request.get_json()
    survey_data = data.get('survey_data')
    
    action_items = []
    
    # Fire resistance check
    if not survey_data.get('fireResistance') or survey_data.get('fireResistance') == 'Unknown':
        action_items.append({
            'severity': 'high',
            'category': 'Certification',
            'dueDate': get_due_date('high'),
            'actionDescription': 'Fire resistance rating is unknown or not specified. This is a critical compliance issue.',
            'remediationOptions': [
                {
                    'option': 'Option 1: Immediate Consultation',
                    'plan': 'Contact the door manufacturer or supplier to obtain proper certification documentation immediately.'
                },
                {
                    'option': 'Option 2: Door Replacement',
                    'plan': 'If certification cannot be obtained, replace the door with a properly certified fire door.'
                },
                {
                    'option': 'Option 3: Professional Assessment',
                    'plan': 'Conduct comprehensive fire safety assessment and obtain professional certification for existing door.'
                }
            ],
            'confidenceScore': 95
        })
    
    # Add other rule-based checks here...
    
    return jsonify({
        'actionItems': action_items,
        'source': 'rule-based'
    })

@app.route('/api/action_item/contractor-recommendations', methods=['POST'])
def contractor_recommendations():
    """Get contractor recommendations based on action items"""
    data = request.get_json()
    action_items = data.get('action_items', [])
    api_key = data.get('api_key')
    model = data.get('model', 'gpt-3.5-turbo')
    
    # Try AI recommendations first
    if api_key:
        try:
            ai_contractors = get_ai_contractor_recommendations(action_items, api_key, model)
            return jsonify({
                'contractors': ai_contractors,
                'source': 'ai'
            })
        except Exception as e:
            print(f"AI contractor recommendations failed: {e}")
    
    # Fallback to hardcoded recommendations
    contractors = get_fallback_contractor_recommendations(action_items)
    return jsonify({
        'contractors': contractors,
        'source': 'fallback'
    })

@app.route('/api/action_item/calculate-costs', methods=['POST'])
def calculate_costs():
    """Calculate total costs from action items"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
            
        action_items = data.get('action_items', [])
        
        total_min = 0
        total_max = 0
        total_confidence = 0
        valid_items = 0
        
        for item in action_items:
            if not isinstance(item, dict):
                continue
                
            if item.get('remediationOptions'):
                # Use standard solution (option 2) for cost calculation
                standard_option = item['remediationOptions'][1] if len(item['remediationOptions']) > 1 else item['remediationOptions'][0]
                if standard_option and standard_option.get('cost'):
                    cost_range = extract_cost_range(standard_option['cost'])
                    if cost_range:
                        total_min += cost_range['min']
                        total_max += cost_range['max']
            
            # Calculate confidence
            if item.get('confidenceScore'):
                confidence = item['confidenceScore']
                # Convert to int if it's a string
                if isinstance(confidence, str):
                    try:
                        confidence = int(confidence)
                    except ValueError:
                        confidence = 0
                elif not isinstance(confidence, (int, float)):
                    confidence = 0
                total_confidence += confidence
                valid_items += 1
        
        avg_confidence = total_confidence / valid_items if valid_items > 0 else 0
        
        return jsonify({
            'min_cost': total_min,
            'max_cost': total_max,
            'average_cost': (total_min + total_max) // 2,
            'avg_confidence': round(avg_confidence, 1)
        })
        
    except Exception as e:
        return jsonify({'error': f'Cost calculation failed: {str(e)}'}), 500

# Helper functions for AI analysis
def create_openai_prompt(survey_data):
    """Create structured prompt for OpenAI"""
    return f"""
Analyze this UK fire door survey data and provide action items in EXACTLY this JSON format:

{{
    "actionItems": [
        {{
            "severity": "high|medium|low",
            "category": "specific category name",
            "dueDate": "DD/MM/YYYY",
            "actionDescription": "detailed description of the issue",
            "remediationOptions": [
                {{
                    "option": "Option 1: Quick Fix",
                    "plan": "step-by-step remediation plan for quick fix"
                }},
                {{
                    "option": "Option 2: Standard Solution",
                    "plan": "step-by-step remediation plan for standard solution"
                }},
                {{
                    "option": "Option 3: Comprehensive Fix",
                    "plan": "step-by-step remediation plan for comprehensive solution"
                }}
            ],
            "confidenceScore": 85
        }}
    ]
}}

Survey Data:
- Fire Resistance: {survey_data.get('fireResistance', 'Not specified')}
- Head Gap: {survey_data.get('headGap', 'Not measured')}mm
- Hinge Gap: {survey_data.get('hingeGap', 'Not measured')}mm
- Closing Gap: {survey_data.get('closingGap', 'Not measured')}mm
- Threshold Gap: {survey_data.get('thresholdGap', 'Not measured')}mm
- Door Thickness: {survey_data.get('doorThickness', 'Not measured')}mm
- Frame Depth: {survey_data.get('frameDepth', 'Not measured')}mm
- Door Size: {survey_data.get('doorSize', 'Not measured')}mm
- Intumescent Strips: {'Yes' if survey_data.get('intumescentStrips') else 'No'}
- Self-closing Device: {'Yes' if survey_data.get('selfClosingDevice') else 'No'}
- Keep Shut Sign: {'Yes' if survey_data.get('keepShutSign') else 'No'}
- Hold Open Device: {'Yes' if survey_data.get('holdOpenDevice') else 'No'}
- Certification Visible: {'Yes' if survey_data.get('certificationVisible') else 'No'}
- Contains Glazing: {'Yes' if survey_data.get('containsGlazing') else 'No'}
- Pyro Glazing: {'Yes' if survey_data.get('pyroGlazing') else 'No'}
- Comments: {survey_data.get('comments', 'None')}

UK Fire Door Standards & Regulations:
- Maximum gaps around door: 4mm (BS 476, Building Regulations Approved Document B)
- Minimum door thickness: 44mm for most fire doors
- Required components: intumescent strips, self-closing devices, certification labels
- Signs must meet BS 5499 standards
- Glazing must be fire-rated pyro glazing if present
- Hold-open devices must be connected to fire alarm system

Assessment Guidelines:
- HIGH severity: Missing critical safety components (intumescent strips, self-closing devices), gaps > 4mm, missing certification
- MEDIUM severity: Missing signs, hold-open device issues, door thickness concerns
- LOW severity: Minor compliance issues, maintenance recommendations

Due Date Guidelines:
- HIGH: 1-3 days (immediate safety risk)
- MEDIUM: 7-14 days (important compliance issue)
- LOW: 14-30 days (maintenance/review)

Remediation Options Guidelines:
- Option 1 (Quick Fix): Temporary or immediate solution, may need follow-up
- Option 2 (Standard Solution): Industry standard approach, balanced effectiveness
- Option 3 (Comprehensive Fix): Complete, long-term solution, most effective

Provide ONLY the JSON response for each survey data category separately ie. separate for Head, Hinge, threshold etc and only show if there is an action item. Each issue should have 3 different remediation options with different effectiveness levels.
"""

def parse_openai_response(ai_response):
    """Parse OpenAI response and extract action items"""
    try:
        # Extract JSON from response
        json_match = re.search(r'\{[\s\S]*\}', ai_response)
        if json_match:
            parsed = json.loads(json_match.group(0))
            if parsed.get('actionItems') and isinstance(parsed['actionItems'], list):
                # Process action items to replace due date placeholders or any date
                for item in parsed['actionItems']:
                    due_date = item.get('dueDate', '')
                    # Replace placeholder or any date format with calculated date
                    if due_date == 'DD/MM/YYYY' or re.match(r'\d{2}/\d{2}/\d{4}', due_date):
                        # Replace with actual calculated date based on severity
                        severity = item.get('severity', 'medium')
                        item['dueDate'] = get_due_date(severity)
                return parsed['actionItems']
        raise ValueError('Invalid response format')
    except Exception as e:
        print(f'Failed to parse OpenAI response: {e}')
        print(f'Raw response: {ai_response}')
        raise ValueError('AI response parsing failed')

def get_ai_contractor_recommendations(action_items, api_key, model):
    """Get AI-generated contractor recommendations"""
    issues = '\n'.join([f"{item['category']}: {item['actionDescription']}" for item in action_items])
    
    prompt = f"""
Based on these fire door compliance issues found in the UK, recommend 3-4 professional contractors who can address these specific problems:

Issues Found:
{issues}

Provide recommendations in this EXACT JSON format:
{{
    "contractors": [
        {{
            "name": "Company Name",
            "specialty": "Specific expertise relevant to the issues",
            "contact": "Phone number | email@domain.com",
            "website": "www.companywebsite.co.uk",
            "rating": 4
        }}
    ]
}}

Requirements:
- Focus on UK-based fire door specialists
- Match contractor specialties to the specific issues found
- Include real, reputable companies when possible
- Provide accurate contact information
- Rating should be 3-5 stars
- Website should be realistic and professional

Provide ONLY the JSON response, no additional text.
"""
    
    response = openai.ChatCompletion.create(
        model=model,
        messages=[
            {
                'role': 'system',
                'content': 'You are a UK fire safety consultant specializing in contractor recommendations. Provide accurate, professional contractor recommendations based on specific fire door compliance issues.'
            },
            {
                'role': 'user',
                'content': prompt
            }
        ],
        temperature=0.3,
        max_tokens=1000,
        api_key=api_key
    )
    
    ai_response = response.choices[0].message.content
    
    # Parse AI response
    try:
        json_match = re.search(r'\{[\s\S]*\}', ai_response)
        if json_match:
            parsed = json.loads(json_match.group(0))
            if parsed.get('contractors') and isinstance(parsed['contractors'], list):
                return parsed['contractors']
        raise ValueError('Invalid AI response format')
    except Exception as e:
        print(f'Failed to parse AI contractor response: {e}')
        raise ValueError('AI contractor response parsing failed')

def get_fallback_contractor_recommendations(action_items):
    """Get fallback contractor recommendations"""
    contractors = [
        {
            "name": "Fire Door Solutions Ltd",
            "specialty": "Complete fire door installation & maintenance",
            "contact": "0800 123 4567 | info@firedoorsolutions.co.uk",
            "website": "www.firedoorsolutions.co.uk",
            "rating": 5
        },
        {
            "name": "UK Fire Safety Services",
            "specialty": "Fire door compliance & certification",
            "contact": "020 7123 4567 | enquiries@ukfiresafety.co.uk",
            "website": "www.ukfiresafety.co.uk",
            "rating": 4
        },
        {
            "name": "Premier Fire Doors",
            "specialty": "Specialized fire door repairs & upgrades",
            "contact": "0161 234 5678 | sales@premierfiredoors.com",
            "website": "www.premierfiredoors.com",
            "rating": 5
        },
        {
            "name": "SafeGuard Fire Protection",
            "specialty": "Fire door hardware & self-closing devices",
            "contact": "0117 345 6789 | info@safeguardfire.co.uk",
            "website": "www.safeguardfire.co.uk",
            "rating": 4
        }
    ]
    
    # Filter contractors based on issues found
    has_high_priority = any(item['severity'] == 'high' for item in action_items)
    has_glazing = any('glazing' in item['category'].lower() for item in action_items)
    has_hardware = any('hardware' in item['category'].lower() or 'device' in item['category'].lower() for item in action_items)
    
    if has_high_priority:
        return contractors[:3]  # Top 3 for high priority issues
    elif has_glazing or has_hardware:
        return [c for c in contractors if 'hardware' in c['specialty'].lower() or 'repairs' in c['specialty'].lower()]
    else:
        return contractors[:2]  # Top 2 for general issues

if __name__ == '__main__':
    # Azure App Service uses PORT environment variable
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    app.run(debug=debug_mode, host='0.0.0.0', port=port)