from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import openai
import anthropic
import json
import re
from datetime import datetime, timedelta
from typing import Optional
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
CORS(app)

# Unified API Key Mapping - Maps client keys to real AI keys
API_KEY_MAPPING = {
    # OpenAI keys
    'your_key': os.getenv('OPENAI_API_KEY'),
    'openai_dev': os.getenv('OPENAI_DEV_KEY'),
    'openai_prod': os.getenv('OPENAI_PROD_KEY'),
    'openai_test': os.getenv('OPENAI_TEST_KEY'),
    
    # Claude keys  
    'claude_key': os.getenv('CLAUDE_API_KEY'),
    'claude_dev': os.getenv('CLAUDE_DEV_KEY'),
    'claude_prod': os.getenv('CLAUDE_PROD_KEY'),
    'claude_test': os.getenv('CLAUDE_TEST_KEY'),
    
    # Shared keys (will work with both providers)
    'DEV_KEY': os.getenv('DEV_KEY'),
    'PROD_KEY': os.getenv('PROD_KEY'),
    'TEST_KEY': os.getenv('TEST_KEY')
}

# Default models for each provider
DEFAULT_OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o')
DEFAULT_CLAUDE_MODEL = os.getenv('DEFAULT_AI_MODEL', 'claude-sonnet-4-20250514')

print(f"Default OpenAI model: {DEFAULT_OPENAI_MODEL}")
print(f"Default Claude model: {DEFAULT_CLAUDE_MODEL}")

# Rate limiting - 100 calls per minute
class RateLimiter:
    def __init__(self):
        self.calls = []
        self.max_calls = 100
        self.time_window = 60
    
    def can_make_call(self):
        import time
        now = time.time()
        self.calls = [t for t in self.calls if now - t < self.time_window]
        if len(self.calls) < self.max_calls:
            self.calls.append(now)
            return True
        return False
    
    def get_remaining_calls(self):
        import time
        now = time.time()
        self.calls = [t for t in self.calls if now - t < self.time_window]
        return max(0, self.max_calls - len(self.calls))
    
    def get_reset_time(self):
        import time
        if not self.calls:
            return 0
        now = time.time()
        oldest = min(self.calls)
        return max(0, self.time_window - (now - oldest))

rate_limiter = RateLimiter()

def get_due_date(severity: str) -> str:
    if severity == 'high':
        days = 7
    elif severity == 'medium':
        days = 14
    elif severity == 'low':
        days = 21
    else:
        days = 14
    date = datetime.now() + timedelta(days=days)
    return date.strftime('%d/%m/%Y')

def calculate_openai_cost(model, input_tokens, output_tokens):
    """Calculate cost based on OpenAI pricing (as of 2024)"""
    pricing = {
        'gpt-4o': {'input': 0.005, 'output': 0.015},  # per 1K tokens
        'gpt-4o-mini': {'input': 0.00015, 'output': 0.0006},
        'gpt-4-turbo': {'input': 0.01, 'output': 0.03},
        'gpt-3.5-turbo': {'input': 0.0015, 'output': 0.002},
    }
    
    model_pricing = pricing.get(model, pricing['gpt-4o'])
    
    input_cost = (input_tokens / 1000) * model_pricing['input']
    output_cost = (output_tokens / 1000) * model_pricing['output']
    
    return round(input_cost + output_cost, 6)

def calculate_claude_cost(model, input_tokens, output_tokens):
    """Calculate cost based on Claude pricing (as of 2024)"""
    pricing = {
        'claude-sonnet-4-20250514': {'input': 0.003, 'output': 0.015},  # per 1K tokens
        'claude-3-5-sonnet-20241022': {'input': 0.003, 'output': 0.015},
        'claude-3-5-sonnet-20240620': {'input': 0.003, 'output': 0.015},
        'claude-3-opus-20240229': {'input': 0.015, 'output': 0.075},
        'claude-3-haiku-20240307': {'input': 0.00025, 'output': 0.00125},
    }
    
    model_pricing = pricing.get(model, pricing['claude-sonnet-4-20250514'])
    
    input_cost = (input_tokens / 1000) * model_pricing['input']
    output_cost = (output_tokens / 1000) * model_pricing['output']
    
    return round(input_cost + output_cost, 6)

def resolve_api_key(client_key: Optional[str], provider: str) -> Optional[str]:
    """Resolve API key based on provider"""
    print(f"DEBUG: resolve_api_key called with: {client_key}, provider: {provider}")
    
    if not client_key:
        print("DEBUG: No client key provided")
        return None
    
    # Check if key is in mapping
    if client_key in API_KEY_MAPPING:
        real = API_KEY_MAPPING[client_key]
        print(f"DEBUG: Found in mapping: {client_key} -> {real}")
        
        if provider == 'openai' and real and real.startswith('sk-'):
            print("DEBUG: Returning OpenAI mapped key")
            return real
        elif provider == 'claude' and real and real.startswith('sk-ant-'):
            print("DEBUG: Returning Claude mapped key")
            return real
    
    # Check if it's a direct API key
    if provider == 'openai' and client_key.startswith('sk-'):
        print("DEBUG: Direct OpenAI API key provided")
        return client_key
    elif provider == 'claude' and client_key.startswith('sk-ant-'):
        print("DEBUG: Direct Claude API key provided")
        return client_key
    
    print("DEBUG: No valid key found")
    return None

def parse_ai_response(ai_response, provider):
    """Parse AI response from either OpenAI or Claude"""
    try:
        print(f"Parsing {provider} response: {ai_response}")
        json_match = re.search(r'\{[\s\S]*\}', ai_response)
        if json_match:
            parsed = json.loads(json_match.group(0))
            print(f"Parsed JSON: {parsed}")
            if 'actionItems' in parsed and isinstance(parsed['actionItems'], list):
                print(f"Found action items: {parsed['actionItems']}")
                for item in parsed['actionItems']:
                    due_date = item.get('dueDate', '')
                    if due_date == 'DD/MM/YYYY' or re.match(r'\d{2}/\d{2}/\d{4}', due_date):
                        severity = item.get('severity', 'medium')
                        item['dueDate'] = get_due_date(severity)
                return parsed['actionItems']
            else:
                print("No action items found in parsed JSON")
        else:
            print("No JSON match found")
        raise ValueError('Invalid response format')
    except Exception as e:
        print(f"Parsing error: {e}")
        raise ValueError('AI response parsing failed')

def create_ai_prompt(survey_data):
    """Create prompt for AI analysis"""
    # Build focused prompt based on what data is provided
    data_lines = []
    
    if 'headGap' in survey_data:
        data_lines.append(f"- Head Gap: {survey_data['headGap']}mm")
    if 'hingeGap' in survey_data:
        data_lines.append(f"- Hinge Gap: {survey_data['hingeGap']}mm")
    if 'closingGap' in survey_data:
        data_lines.append(f"- Closing Gap: {survey_data['closingGap']}mm")
    if 'thresholdGap' in survey_data:
        data_lines.append(f"- Threshold Gap: {survey_data['thresholdGap']}mm")
    if 'doorThickness' in survey_data:
        data_lines.append(f"- Door Thickness: {survey_data['doorThickness']}mm")
    if 'frameDepth' in survey_data:
        data_lines.append(f"- Frame Depth: {survey_data['frameDepth']}mm")
    if 'doorSize' in survey_data:
        data_lines.append(f"- Door Size: {survey_data['doorSize']}mm")
    if 'intumescent_strips' in survey_data:
        data_lines.append(f"- Intumescent Strips: {survey_data['intumescent_strips']}")
    if 'self_closing_device' in survey_data:
        data_lines.append(f"- Self-closing Device: {survey_data['self_closing_device']}")
    if 'keep_shut_sign' in survey_data:
        data_lines.append(f"- Keep Shut Sign: {survey_data['keep_shut_sign']}")
    if 'hold_open_device' in survey_data:
        data_lines.append(f"- Hold Open Device: {survey_data['hold_open_device']}")
    if 'certification_visible' in survey_data:
        data_lines.append(f"- Certification Visible: {survey_data['certification_visible']}")
    if 'contains_glazing' in survey_data:
        data_lines.append(f"- Contains Glazing: {survey_data['contains_glazing']}")
    if 'pyro_glazing' in survey_data:
        data_lines.append(f"- Pyro Glazing: {survey_data['pyro_glazing']}")
    
    survey_text = "\n".join(data_lines) if data_lines else "No specific measurements provided"
    
    return f"""
You are a UK fire safety expert. Analyze this fire door measurement and provide action items.

CRITICAL COMPLIANCE RULES:
- Door Thickness: ONLY exactly 20mm is compliant. Any other value (above OR below) needs action items.
- Frame Depth: ONLY exactly 55mm is compliant. Any other value (above OR below) needs action items.  
- Door Size: ONLY exactly 500mm is compliant. Any other value (above OR below) needs action items.
- Gap measurements: Maximum 4mm allowed. Any value above 4mm needs action items.
- Boolean measurements (Intumescent Strips, Self-closing Device, Keep Shut Sign, Hold Open Device, Certification Visible, Contains Glazing, Pyro Glazing): ONLY "yes" is compliant. "no" needs action items.

Measurement Data:
{survey_text}

IMPORTANT: 
- For numeric measurements: If the measurement is NOT exactly at the minimum value, you MUST provide action items for assessment and optimization.
- For boolean measurements: If the value is "no", you MUST provide action items for compliance.

Return ONLY this JSON format:
{{
    "actionItems": [
        {{
            "severity": "high|medium|low",
            "category": "specific category name",
            "dueDate": "DD/MM/YYYY",
            "actionDescription": "detailed description of the issue",
            "remediationOptions": [
                {{"option": "Option 1: Quick Fix", "plan": "steps"}},
                {{"option": "Option 2: Standard Solution", "plan": "steps"}},
                {{"option": "Option 3: Comprehensive Fix", "plan": "steps"}}
            ],
            "confidenceScore": 85
        }}
    ]
}}

If the measurement is exactly at minimum value, return empty actionItems array.
If the measurement is NOT exactly at minimum value, provide specific action items for that measurement.
"""

def analyze_gap_with_ai(gap_type, value, unit, api_key, model, provider):
    """Unified AI analysis function for both OpenAI and Claude"""
    try:
        # Create focused survey data for the specific measurement
        survey_data = {}
        if gap_type == 'door_thickness':
            survey_data = {'doorThickness': value}
        elif gap_type == 'frame_depth':
            survey_data = {'frameDepth': value}
        elif gap_type == 'door_size':
            survey_data = {'doorSize': value}
        elif gap_type in ['intumescent_strips', 'self_closing_device', 'keep_shut_sign', 'hold_open_device', 'certification_visible', 'contains_glazing', 'pyro_glazing']:
            survey_data = {gap_type: value}
        else:
            survey_data = {f'{gap_type}Gap': value}
        
        prompt = create_ai_prompt(survey_data)
        print(f"Survey data for {gap_type}: {survey_data}")
        print(f"Using {provider} with model: {model}")
        
        if provider == 'openai':
            # OpenAI API call
            client = openai.OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {'role': 'system', 'content': f'You are a UK fire safety expert. Focus on the provided {gap_type} measurement and return ONLY JSON.'},
                    {'role': 'user', 'content': prompt},
                ],
                temperature=0.3,
                max_tokens=1000,
            )
            
            ai_response = response.choices[0].message.content
            input_tokens = response.usage.prompt_tokens if response.usage else 0
            output_tokens = response.usage.completion_tokens if response.usage else 0
            total_tokens = response.usage.total_tokens if response.usage else 0
            cost = calculate_openai_cost(model, input_tokens, output_tokens)
            
        elif provider == 'claude':
            # Claude API call
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=model,
                max_tokens=1000,
                temperature=0.3,
                messages=[
                    {'role': 'user', 'content': f'You are a UK fire safety expert. Focus on the provided {gap_type} measurement and return ONLY JSON.\n\n{prompt}'},
                ]
            )
            
            ai_response = response.content[0].text
            input_tokens = response.usage.input_tokens if hasattr(response.usage, 'input_tokens') else 0
            output_tokens = response.usage.output_tokens if hasattr(response.usage, 'output_tokens') else 0
            total_tokens = input_tokens + output_tokens
            cost = calculate_claude_cost(model, input_tokens, output_tokens)
        
        else:
            raise ValueError(f"Unsupported AI provider: {provider}")
        
        print(f"AI Response for {gap_type}: {ai_response}")
        action_items = parse_ai_response(ai_response, provider)
        print(f"Parsed action items for {gap_type}: {action_items}")
        print(f"Cost for {gap_type}: ${cost} (Input: {input_tokens}, Output: {output_tokens})")

        # Determine compliance based on gap type
        if gap_type == 'door_thickness':
            min_thickness = 20
            compliant = value == min_thickness  # Only exactly 20mm is compliant
            max_gap = None
        elif gap_type == 'frame_depth':
            min_depth = 55
            compliant = value == min_depth  # Only exactly 55mm is compliant
            min_thickness = None
            max_gap = None
        elif gap_type == 'door_size':
            min_size = 500
            compliant = value == min_size  # Only exactly 500mm is compliant
            min_thickness = None
            max_gap = None
        elif gap_type in ['intumescent_strips', 'self_closing_device', 'keep_shut_sign', 'hold_open_device', 'certification_visible', 'contains_glazing', 'pyro_glazing']:
            # Boolean measurements: 'yes' is compliant, 'no' is not compliant
            compliant = value.lower() == 'yes'
            min_thickness = None
            max_gap = None
        else:
            max_gap = 4
            compliant = value <= max_gap
            min_thickness = None

        ai_severity = 'none'
        if action_items:
            severities = [item.get('severity', 'low') for item in action_items]
            if 'high' in severities:
                ai_severity = 'high'
            elif 'medium' in severities:
                ai_severity = 'medium'
            elif 'low' in severities:
                ai_severity = 'low'

        # Build response based on gap type
        response_data = {
            'success': True,
            'measurement_type': gap_type if gap_type in ['intumescent_strips', 'self_closing_device', 'keep_shut_sign', 'hold_open_device', 'certification_visible', 'contains_glazing', 'pyro_glazing'] else f'{gap_type}_gap',
            'value': value,
            'unit': unit if gap_type not in ['intumescent_strips', 'self_closing_device', 'keep_shut_sign', 'hold_open_device', 'certification_visible', 'contains_glazing', 'pyro_glazing'] else None,
            'compliant': compliant,
            'severity': ai_severity if not compliant else 'none',
            'actionItems': action_items,
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'ai',
            'ai_provider': provider,
            'ai_model': model,
            'tokens_used': total_tokens,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'cost_usd': cost,
        }
        
        # Add provider-specific fields
        if gap_type == 'door_thickness':
            response_data['min_required'] = min_thickness
        elif gap_type == 'frame_depth':
            response_data['min_required'] = min_depth
        elif gap_type == 'door_size':
            response_data['min_required'] = min_size
        elif gap_type not in ['intumescent_strips', 'self_closing_device', 'keep_shut_sign', 'hold_open_device', 'certification_visible', 'contains_glazing', 'pyro_glazing']:
            response_data['max_allowed'] = max_gap
        
        return response_data
        
    except Exception as e:
        print(f"Error in analyze_gap_with_ai: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return None

# API Endpoints

@app.route('/api/action_item/head', methods=['POST'])
@app.route('/api/action_item/head/<value>/<unit>', methods=['GET'])
def slim_head(value=None, unit=None):
    try:
        if request.method == 'POST':
            data = request.get_json() or {}
            value = data.get('value')
            unit = data.get('unit', 'mm')
            api_key = data.get('api_key')
            model = data.get('model')
            ai_provider = data.get('ai_provider', 'openai')
        else:
            api_key = request.args.get('api_key')
            model = request.args.get('model')
            ai_provider = request.args.get('ai_provider', 'openai')
        
        if value is None:
            return jsonify({'error': 'Value is required'}), 400
        try:
            value = float(value)
        except (ValueError, TypeError):
            return jsonify({'error': 'Value must be a valid number'}), 400

        max_gap = 4
        is_compliant = value <= max_gap

        if api_key and not is_compliant:
            if not rate_limiter.can_make_call():
                return jsonify({'error': 'Rate limit exceeded', 'remaining_calls': rate_limiter.get_remaining_calls(), 'reset_in_seconds': rate_limiter.get_reset_time()}), 429
            
            # Set default model based on provider
            if not model:
                model = DEFAULT_OPENAI_MODEL if ai_provider == 'openai' else DEFAULT_CLAUDE_MODEL
            
            real_key = resolve_api_key(api_key, ai_provider)
            print(f"API key provided: {api_key}")
            print(f"Resolved key: {real_key}")
            print(f"Is compliant: {is_compliant}")
            print(f"AI Provider: {ai_provider}")
            
            if real_key:
                print("Calling AI analysis...")
                ai = analyze_gap_with_ai('head', value, unit, real_key, model, ai_provider)
                if ai:
                    print("AI analysis successful, returning AI response")
                    return jsonify(ai)
                else:
                    print("AI analysis failed, falling back to static")
            else:
                print("No valid API key resolved")

        action_items = []
        if not is_compliant:
            action_items.append({
                'severity': 'high',
                'category': 'Head Gap Compliance',
                'dueDate': get_due_date('high'),
                'actionDescription': f'Head gap ({value}mm) exceeds maximum allowed ({max_gap}mm).',
                'remediationOptions': [
                    {'option': 'Option 1: Quick Fix - Basic Strips', 'plan': 'Install basic intumescent strips at the head.'},
                    {'option': 'Option 2: Standard Solution - Quality Strips', 'plan': 'Install high-quality strips; adjust alignment if needed.'},
                    {'option': 'Option 3: Comprehensive Fix', 'plan': 'Premium strips with smoke seals and full alignment.'},
                ],
                'confidenceScore': 92,
            })

        return jsonify({
            'success': True,
            'measurement_type': 'head_gap',
            'value': value,
            'unit': unit,
            'compliant': is_compliant,
            'max_allowed': max_gap,
            'severity': 'high' if not is_compliant else 'none',
            'actionItems': action_items,
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'ai' if (api_key and not is_compliant) else 'static',
            'ai_provider': ai_provider if (api_key and not is_compliant) else None,
        })
    except Exception as e:
        return jsonify({'error': f'Head gap analysis failed: {str(e)}'}), 500

@app.route('/api/action_item/hinge', methods=['POST'])
@app.route('/api/action_item/hinge/<value>/<unit>', methods=['GET'])
def slim_hinge(value=None, unit=None):
    try:
        if request.method == 'POST':
            data = request.get_json() or {}
            value = data.get('value')
            unit = data.get('unit', 'mm')
            api_key = data.get('api_key')
            model = data.get('model')
            ai_provider = data.get('ai_provider', 'openai')
        else:
            api_key = request.args.get('api_key')
            model = request.args.get('model')
            ai_provider = request.args.get('ai_provider', 'openai')
        
        if value is None:
            return jsonify({'error': 'Value is required'}), 400
        try:
            value = float(value)
        except (ValueError, TypeError):
            return jsonify({'error': 'Value must be a valid number'}), 400

        max_gap = 4
        is_compliant = value <= max_gap

        if api_key and not is_compliant:
            if not rate_limiter.can_make_call():
                return jsonify({'error': 'Rate limit exceeded', 'remaining_calls': rate_limiter.get_remaining_calls(), 'reset_in_seconds': rate_limiter.get_reset_time()}), 429
            
            if not model:
                model = DEFAULT_OPENAI_MODEL if ai_provider == 'openai' else DEFAULT_CLAUDE_MODEL
            
            real_key = resolve_api_key(api_key, ai_provider)
            if real_key:
                ai = analyze_gap_with_ai('hinge', value, unit, real_key, model, ai_provider)
                if ai:
                    return jsonify(ai)

        action_items = []
        if not is_compliant:
            action_items.append({
                'severity': 'high',
                'category': 'Hinge Gap Compliance',
                'dueDate': get_due_date('high'),
                'actionDescription': f'Hinge gap ({value}mm) exceeds maximum allowed ({max_gap}mm).',
                'remediationOptions': [
                    {'option': 'Option 1: Quick Fix - Basic Strips', 'plan': 'Install basic intumescent strips at the hinge side.'},
                    {'option': 'Option 2: Standard Solution', 'plan': 'Quality strips and adjust hinges as needed.'},
                    {'option': 'Option 3: Comprehensive Fix', 'plan': 'Premium strips, alignment and frame adjustment.'},
                ],
                'confidenceScore': 92,
            })

        return jsonify({
            'success': True,
            'measurement_type': 'hinge_gap',
            'value': value,
            'unit': unit,
            'compliant': is_compliant,
            'max_allowed': max_gap,
            'severity': 'high' if not is_compliant else 'none',
            'actionItems': action_items,
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'ai' if (api_key and not is_compliant) else 'static',
            'ai_provider': ai_provider if (api_key and not is_compliant) else None,
        })
    except Exception as e:
        return jsonify({'error': f'Hinge gap analysis failed: {str(e)}'}), 500

@app.route('/api/action_item/closing', methods=['POST'])
@app.route('/api/action_item/closing/<value>/<unit>', methods=['GET'])
def slim_closing(value=None, unit=None):
    try:
        if request.method == 'POST':
            data = request.get_json() or {}
            value = data.get('value')
            unit = data.get('unit', 'mm')
            api_key = data.get('api_key')
            model = data.get('model')
            ai_provider = data.get('ai_provider', 'openai')
        else:
            api_key = request.args.get('api_key')
            model = request.args.get('model')
            ai_provider = request.args.get('ai_provider', 'openai')
        
        if value is None:
            return jsonify({'error': 'Value is required'}), 400
        try:
            value = float(value)
        except (ValueError, TypeError):
            return jsonify({'error': 'Value must be a valid number'}), 400

        max_gap = 4
        is_compliant = value <= max_gap

        if api_key and not is_compliant:
            if not rate_limiter.can_make_call():
                return jsonify({'error': 'Rate limit exceeded', 'remaining_calls': rate_limiter.get_remaining_calls(), 'reset_in_seconds': rate_limiter.get_reset_time()}), 429
            
            if not model:
                model = DEFAULT_OPENAI_MODEL if ai_provider == 'openai' else DEFAULT_CLAUDE_MODEL
            
            real_key = resolve_api_key(api_key, ai_provider)
            if real_key:
                ai = analyze_gap_with_ai('closing', value, unit, real_key, model, ai_provider)
                if ai:
                    return jsonify(ai)

        action_items = []
        if not is_compliant:
            action_items.append({
                'severity': 'high',
                'category': 'Closing Gap Compliance',
                'dueDate': get_due_date('high'),
                'actionDescription': f'Closing gap ({value}mm) exceeds maximum allowed ({max_gap}mm).',
                'remediationOptions': [
                    {'option': 'Option 1: Quick Fix - Basic Strips', 'plan': 'Install basic strips at the closing edge.'},
                    {'option': 'Option 2: Standard Solution', 'plan': 'Quality strips with alignment and frame adjustment.'},
                    {'option': 'Option 3: Comprehensive Fix', 'plan': 'Premium strips, alignment and professional testing.'},
                ],
                'confidenceScore': 92,
            })

        return jsonify({
            'success': True,
            'measurement_type': 'closing_gap',
            'value': value,
            'unit': unit,
            'compliant': is_compliant,
            'max_allowed': max_gap,
            'severity': 'high' if not is_compliant else 'none',
            'actionItems': action_items,
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'ai' if (api_key and not is_compliant) else 'static',
            'ai_provider': ai_provider if (api_key and not is_compliant) else None,
        })
    except Exception as e:
        return jsonify({'error': f'Closing gap analysis failed: {str(e)}'}), 500

@app.route('/api/action_item/threshold', methods=['POST'])
@app.route('/api/action_item/threshold/<value>/<unit>', methods=['GET'])
def slim_threshold(value=None, unit=None):
    try:
        if request.method == 'POST':
            data = request.get_json() or {}
            value = data.get('value')
            unit = data.get('unit', 'mm')
            api_key = data.get('api_key')
            model = data.get('model')
            ai_provider = data.get('ai_provider', 'openai')
        else:
            api_key = request.args.get('api_key')
            model = request.args.get('model')
            ai_provider = request.args.get('ai_provider', 'openai')
        
        if value is None:
            return jsonify({'error': 'Value is required'}), 400
        try:
            value = float(value)
        except (ValueError, TypeError):
            return jsonify({'error': 'Value must be a valid number'}), 400

        max_gap = 4
        is_compliant = value <= max_gap

        if api_key and not is_compliant:
            if not rate_limiter.can_make_call():
                return jsonify({'error': 'Rate limit exceeded', 'remaining_calls': rate_limiter.get_remaining_calls(), 'reset_in_seconds': rate_limiter.get_reset_time()}), 429
            
            if not model:
                model = DEFAULT_OPENAI_MODEL if ai_provider == 'openai' else DEFAULT_CLAUDE_MODEL
            
            real_key = resolve_api_key(api_key, ai_provider)
            if real_key:
                ai = analyze_gap_with_ai('threshold', value, unit, real_key, model, ai_provider)
                if ai:
                    return jsonify(ai)

        action_items = []
        if not is_compliant:
            action_items.append({
                'severity': 'high',
                'category': 'Threshold Gap Compliance',
                'dueDate': get_due_date('high'),
                'actionDescription': f'Threshold gap ({value}mm) exceeds maximum allowed ({max_gap}mm).',
                'remediationOptions': [
                    {'option': 'Option 1: Quick Fix - Basic Threshold Seal', 'plan': 'Install basic threshold seal.'},
                    {'option': 'Option 2: Standard Solution', 'plan': 'Quality threshold system with alignment.'},
                    {'option': 'Option 3: Comprehensive Fix', 'plan': 'Premium threshold system with full alignment and testing.'},
                ],
                'confidenceScore': 92,
            })

        return jsonify({
            'success': True,
            'measurement_type': 'threshold_gap',
            'value': value,
            'unit': unit,
            'compliant': is_compliant,
            'max_allowed': max_gap,
            'severity': 'high' if not is_compliant else 'none',
            'actionItems': action_items,
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'ai' if (api_key and not is_compliant) else 'static',
            'ai_provider': ai_provider if (api_key and not is_compliant) else None,
        })
    except Exception as e:
        return jsonify({'error': f'Threshold gap analysis failed: {str(e)}'}), 500

@app.route('/api/action_item/doorthick', methods=['POST'])
@app.route('/api/action_item/doorthick/<value>/<unit>', methods=['GET'])
def slim_doorthick(value=None, unit=None):
    try:
        if request.method == 'POST':
            data = request.get_json() or {}
            value = data.get('value')
            unit = data.get('unit', 'mm')
            api_key = data.get('api_key')
            model = data.get('model')
            ai_provider = data.get('ai_provider', 'openai')
        else:
            api_key = request.args.get('api_key')
            model = request.args.get('model')
            ai_provider = request.args.get('ai_provider', 'openai')
        
        if value is None:
            return jsonify({'error': 'Value is required'}), 400
        try:
            value = float(value)
        except (ValueError, TypeError):
            return jsonify({'error': 'Value must be a valid number'}), 400

        min_thickness = 20
        if value < min_thickness:
            return jsonify({'error': 'door thickness should be at least 20mm'}), 400
        is_compliant = value == min_thickness  # Only exactly 20mm is compliant

        if api_key and not is_compliant:
            if not rate_limiter.can_make_call():
                return jsonify({'error': 'Rate limit exceeded', 'remaining_calls': rate_limiter.get_remaining_calls(), 'reset_in_seconds': rate_limiter.get_reset_time()}), 429
            
            if not model:
                model = DEFAULT_OPENAI_MODEL if ai_provider == 'openai' else DEFAULT_CLAUDE_MODEL
            
            real_key = resolve_api_key(api_key, ai_provider)
            if real_key:
                ai = analyze_gap_with_ai('door_thickness', value, unit, real_key, model, ai_provider)
                if ai:
                    return jsonify(ai)

        action_items = []
        if not is_compliant:
            action_items.append({
                'severity': 'medium',
                'category': 'Door Thickness Compliance',
                'dueDate': get_due_date('medium'),
                'actionDescription': f'Door thickness ({value}mm) is below recommended minimum ({min_thickness}mm).',
                'remediationOptions': [
                    {'option': 'Option 1: Assessment & Verification', 'plan': 'Verify certification with manufacturer.'},
                    {'option': 'Option 2: Door Replacement', 'plan': 'Replace with certified 44mm fire door.'},
                    {'option': 'Option 3: Professional Assessment & Upgrade', 'plan': 'Comprehensive assessment and upgrades.'},
                ],
                'confidenceScore': 85,
            })

        return jsonify({
            'success': True,
            'measurement_type': 'door_thickness',
            'value': value,
            'unit': unit,
            'compliant': is_compliant,
            'min_required': min_thickness,
            'severity': 'medium' if not is_compliant else 'none',
            'actionItems': action_items,
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'ai' if (api_key and not is_compliant) else 'static',
            'ai_provider': ai_provider if (api_key and not is_compliant) else None,
        })
    except Exception as e:
        return jsonify({'error': f'Door thickness analysis failed: {str(e)}'}), 500

@app.route('/api/action_item/framedepth', methods=['POST'])
@app.route('/api/action_item/framedepth/<value>/<unit>', methods=['GET'])
def slim_framedepth(value=None, unit=None):
    try:
        if request.method == 'POST':
            data = request.get_json() or {}
            value = data.get('value')
            unit = data.get('unit', 'mm')
            api_key = data.get('api_key')
            model = data.get('model')
            ai_provider = data.get('ai_provider', 'openai')
        else:
            api_key = request.args.get('api_key')
            model = request.args.get('model')
            ai_provider = request.args.get('ai_provider', 'openai')
        
        if value is None:
            return jsonify({'error': 'Value is required'}), 400
        try:
            value = float(value)
        except (ValueError, TypeError):
            return jsonify({'error': 'Value must be a valid number'}), 400

        min_depth = 55
        if value < min_depth:
            return jsonify({'error': 'frame depth should be at least 55mm'}), 400
        is_compliant = value == min_depth  # Only exactly 55mm is compliant

        if api_key and not is_compliant:
            if not rate_limiter.can_make_call():
                return jsonify({'error': 'Rate limit exceeded', 'remaining_calls': rate_limiter.get_remaining_calls(), 'reset_in_seconds': rate_limiter.get_reset_time()}), 429
            
            if not model:
                model = DEFAULT_OPENAI_MODEL if ai_provider == 'openai' else DEFAULT_CLAUDE_MODEL
            
            real_key = resolve_api_key(api_key, ai_provider)
            if real_key:
                ai = analyze_gap_with_ai('frame_depth', value, unit, real_key, model, ai_provider)
                if ai:
                    return jsonify(ai)

        action_items = []
        if not is_compliant:
            action_items.append({
                'severity': 'medium',
                'category': 'Frame Depth Compliance',
                'dueDate': get_due_date('medium'),
                'actionDescription': f'Frame depth ({value}mm) is below recommended minimum (55mm).',
                'remediationOptions': [
                    {'option': 'Option 1: Assessment & Verification', 'plan': 'Verify frame meets fire resistance requirements.'},
                    {'option': 'Option 2: Frame Replacement', 'plan': 'Replace with certified 55mm+ frame.'},
                    {'option': 'Option 3: Professional Assessment', 'plan': 'Comprehensive frame assessment and upgrades.'},
                ],
                'confidenceScore': 85,
            })

        return jsonify({
            'success': True,
            'measurement_type': 'frame_depth',
            'value': value,
            'unit': unit,
            'compliant': is_compliant,
            'min_required': min_depth,
            'severity': 'medium' if not is_compliant else 'none',
            'actionItems': action_items,
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'ai' if (api_key and not is_compliant) else 'static',
            'ai_provider': ai_provider if (api_key and not is_compliant) else None,
        })
    except Exception as e:
        return jsonify({'error': f'Frame depth analysis failed: {str(e)}'}), 500

@app.route('/api/action_item/doorsize', methods=['POST'])
@app.route('/api/action_item/doorsize/<value>/<unit>', methods=['GET'])
def slim_doorsize(value=None, unit=None):
    try:
        if request.method == 'POST':
            data = request.get_json() or {}
            value = data.get('value')
            unit = data.get('unit', 'mm')
            api_key = data.get('api_key')
            model = data.get('model')
            ai_provider = data.get('ai_provider', 'openai')
        else:
            api_key = request.args.get('api_key')
            model = request.args.get('model')
            ai_provider = request.args.get('ai_provider', 'openai')
        
        if value is None:
            return jsonify({'error': 'Value is required'}), 400
        try:
            value = float(value)
        except (ValueError, TypeError):
            return jsonify({'error': 'Value must be a valid number'}), 400

        min_size = 500
        if value < min_size:
            return jsonify({'error': 'door size should be at least 500mm'}), 400
        is_compliant = value == min_size  # Only exactly 500mm is compliant

        if api_key and not is_compliant:
            if not rate_limiter.can_make_call():
                return jsonify({'error': 'Rate limit exceeded', 'remaining_calls': rate_limiter.get_remaining_calls(), 'reset_in_seconds': rate_limiter.get_reset_time()}), 429
            
            if not model:
                model = DEFAULT_OPENAI_MODEL if ai_provider == 'openai' else DEFAULT_CLAUDE_MODEL
            
            real_key = resolve_api_key(api_key, ai_provider)
            if real_key:
                ai = analyze_gap_with_ai('door_size', value, unit, real_key, model, ai_provider)
                if ai:
                    return jsonify(ai)

        action_items = []
        if not is_compliant:
            action_items.append({
                'severity': 'medium',
                'category': 'Door Size Compliance',
                'dueDate': get_due_date('medium'),
                'actionDescription': f'Door size ({value}mm) requires assessment for optimal fire resistance.',
                'remediationOptions': [
                    {'option': 'Option 1: Assessment & Verification', 'plan': 'Verify door meets fire resistance requirements.'},
                    {'option': 'Option 2: Door Replacement', 'plan': 'Replace with certified 500mm+ door.'},
                    {'option': 'Option 3: Professional Assessment', 'plan': 'Comprehensive door assessment and upgrades.'},
                ],
                'confidenceScore': 85,
            })

        return jsonify({
            'success': True,
            'measurement_type': 'door_size',
            'value': value,
            'unit': unit,
            'compliant': is_compliant,
            'min_required': min_size,
            'severity': 'medium' if not is_compliant else 'none',
            'actionItems': action_items,
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'ai' if (api_key and not is_compliant) else 'static',
            'ai_provider': ai_provider if (api_key and not is_compliant) else None,
        })
    except Exception as e:
        return jsonify({'error': f'Door size analysis failed: {str(e)}'}), 500

@app.route('/api/action_item/intustrips/<value>', methods=['GET'])
def slim_intustrips(value):
    try:
        api_key = request.args.get('api_key')
        model = request.args.get('model')
        ai_provider = request.args.get('ai_provider', 'openai')
        
        if value.lower() not in ['yes', 'no']:
            return jsonify({'error': 'Value must be "yes" or "no"'}), 400

        is_compliant = value.lower() == 'yes'

        action_items = []
        
        if api_key and not is_compliant:
            if not rate_limiter.can_make_call():
                return jsonify({'error': 'Rate limit exceeded', 'remaining_calls': rate_limiter.get_remaining_calls(), 'reset_in_seconds': rate_limiter.get_reset_time()}), 429
            
            if not model:
                model = DEFAULT_OPENAI_MODEL if ai_provider == 'openai' else DEFAULT_CLAUDE_MODEL
            
            real_key = resolve_api_key(api_key, ai_provider)
            if real_key:
                ai = analyze_gap_with_ai('intumescent_strips', value, 'boolean', real_key, model, ai_provider)
                if ai:
                    return jsonify(ai)
                action_items = []
        else:
            if not is_compliant:
                action_items.append({
                    'severity': 'high',
                    'category': 'Intumescent Strips Compliance',
                    'dueDate': get_due_date('high'),
                    'actionDescription': 'Intumescent strips are missing. This is critical for fire door performance.',
                    'remediationOptions': [
                        {'option': 'Option 1: Quick Fix - Basic Strips', 'plan': 'Install basic intumescent strips immediately.'},
                        {'option': 'Option 2: Standard Solution', 'plan': 'Install high-quality intumescent strips with proper sealing.'},
                        {'option': 'Option 3: Comprehensive Fix', 'plan': 'Install premium strips with smoke seals and professional testing.'},
                    ],
                    'confidenceScore': 95,
                })

        return jsonify({
            'success': True,
            'measurement_type': 'intumescent_strips',
            'value': value,
            'compliant': is_compliant,
            'severity': 'high' if not is_compliant else 'none',
            'actionItems': action_items,
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'ai' if (api_key and not is_compliant) else 'static',
            'ai_provider': ai_provider if (api_key and not is_compliant) else None,
        })
    except Exception as e:
        return jsonify({'error': f'Intumescent strips analysis failed: {str(e)}'}), 500

@app.route('/api/action_item/selfclosing/<value>', methods=['GET'])
def slim_selfclosing(value):
    try:
        api_key = request.args.get('api_key')
        model = request.args.get('model')
        ai_provider = request.args.get('ai_provider', 'openai')
        
        if value.lower() not in ['yes', 'no']:
            return jsonify({'error': 'Value must be "yes" or "no"'}), 400

        is_compliant = value.lower() == 'yes'

        action_items = []
        
        if api_key and not is_compliant:
            if not rate_limiter.can_make_call():
                return jsonify({'error': 'Rate limit exceeded', 'remaining_calls': rate_limiter.get_remaining_calls(), 'reset_in_seconds': rate_limiter.get_reset_time()}), 429
            
            if not model:
                model = DEFAULT_OPENAI_MODEL if ai_provider == 'openai' else DEFAULT_CLAUDE_MODEL
            
            real_key = resolve_api_key(api_key, ai_provider)
            if real_key:
                ai = analyze_gap_with_ai('self_closing_device', value, 'boolean', real_key, model, ai_provider)
                if ai:
                    return jsonify(ai)
                action_items = []
        else:
            if not is_compliant:
                action_items.append({
                    'severity': 'high',
                    'category': 'Self-Closing Device Compliance',
                    'dueDate': get_due_date('high'),
                    'actionDescription': 'Self-closing device is missing. This is critical for fire door safety.',
                    'remediationOptions': [
                        {'option': 'Option 1: Quick Fix - Basic Device', 'plan': 'Install basic self-closing device immediately.'},
                        {'option': 'Option 2: Standard Solution', 'plan': 'Install quality self-closing device with proper adjustment.'},
                        {'option': 'Option 3: Comprehensive Fix', 'plan': 'Install premium device with fire alarm integration and testing.'},
                    ],
                    'confidenceScore': 95,
                })

        return jsonify({
            'success': True,
            'measurement_type': 'self_closing_device',
            'value': value,
            'compliant': is_compliant,
            'severity': 'high' if not is_compliant else 'none',
            'actionItems': action_items,
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'ai' if (api_key and not is_compliant) else 'static',
            'ai_provider': ai_provider if (api_key and not is_compliant) else None,
        })
    except Exception as e:
        return jsonify({'error': f'Self-closing device analysis failed: {str(e)}'}), 500

@app.route('/api/action_item/shutsign/<value>', methods=['GET'])
def slim_shutsign(value):
    try:
        api_key = request.args.get('api_key')
        model = request.args.get('model')
        ai_provider = request.args.get('ai_provider', 'openai')
        
        if value.lower() not in ['yes', 'no']:
            return jsonify({'error': 'Value must be "yes" or "no"'}), 400

        is_compliant = value.lower() == 'yes'

        action_items = []
        
        if api_key and not is_compliant:
            if not rate_limiter.can_make_call():
                return jsonify({'error': 'Rate limit exceeded', 'remaining_calls': rate_limiter.get_remaining_calls(), 'reset_in_seconds': rate_limiter.get_reset_time()}), 429
            
            if not model:
                model = DEFAULT_OPENAI_MODEL if ai_provider == 'openai' else DEFAULT_CLAUDE_MODEL
            
            real_key = resolve_api_key(api_key, ai_provider)
            if real_key:
                ai = analyze_gap_with_ai('keep_shut_sign', value, 'boolean', real_key, model, ai_provider)
                if ai:
                    return jsonify(ai)
                action_items = []
        else:
            if not is_compliant:
                action_items.append({
                    'severity': 'medium',
                    'category': 'Keep Shut Sign Compliance',
                    'dueDate': get_due_date('medium'),
                    'actionDescription': 'Keep shut sign is missing. Required for fire door compliance.',
                    'remediationOptions': [
                        {'option': 'Option 1: Quick Fix - Basic Sign', 'plan': 'Install basic keep shut sign immediately.'},
                        {'option': 'Option 2: Standard Solution', 'plan': 'Install compliant sign meeting BS 5499 standards.'},
                        {'option': 'Option 3: Comprehensive Fix', 'plan': 'Install premium sign with proper mounting and visibility.'},
                    ],
                    'confidenceScore': 85,
                })

        return jsonify({
            'success': True,
            'measurement_type': 'keep_shut_sign',
            'value': value,
            'compliant': is_compliant,
            'severity': 'medium' if not is_compliant else 'none',
            'actionItems': action_items,
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'ai' if (api_key and not is_compliant) else 'static',
            'ai_provider': ai_provider if (api_key and not is_compliant) else None,
        })
    except Exception as e:
        return jsonify({'error': f'Keep shut sign analysis failed: {str(e)}'}), 500

@app.route('/api/action_item/holddevice/<value>', methods=['GET'])
def slim_holddevice(value):
    try:
        api_key = request.args.get('api_key')
        model = request.args.get('model')
        ai_provider = request.args.get('ai_provider', 'openai')
        
        if value.lower() not in ['yes', 'no']:
            return jsonify({'error': 'Value must be "yes" or "no"'}), 400

        is_compliant = value.lower() == 'yes'

        action_items = []
        
        if api_key and not is_compliant:
            if not rate_limiter.can_make_call():
                return jsonify({'error': 'Rate limit exceeded', 'remaining_calls': rate_limiter.get_remaining_calls(), 'reset_in_seconds': rate_limiter.get_reset_time()}), 429
            
            if not model:
                model = DEFAULT_OPENAI_MODEL if ai_provider == 'openai' else DEFAULT_CLAUDE_MODEL
            
            real_key = resolve_api_key(api_key, ai_provider)
            if real_key:
                ai = analyze_gap_with_ai('hold_open_device', value, 'boolean', real_key, model, ai_provider)
                if ai:
                    return jsonify(ai)
                action_items = []
        else:
            if not is_compliant:
                action_items.append({
                    'severity': 'medium',
                    'category': 'Hold Open Device Compliance',
                    'dueDate': get_due_date('medium'),
                    'actionDescription': 'Hold open device is missing. Required for fire door compliance.',
                    'remediationOptions': [
                        {'option': 'Option 1: Quick Fix - Basic Device', 'plan': 'Install basic hold open device.'},
                        {'option': 'Option 2: Standard Solution', 'plan': 'Install quality device with fire alarm integration.'},
                        {'option': 'Option 3: Comprehensive Fix', 'plan': 'Install premium device with full fire alarm system integration.'},
                    ],
                    'confidenceScore': 85,
                })

        return jsonify({
            'success': True,
            'measurement_type': 'hold_open_device',
            'value': value,
            'compliant': is_compliant,
            'severity': 'medium' if not is_compliant else 'none',
            'actionItems': action_items,
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'ai' if (api_key and not is_compliant) else 'static',
            'ai_provider': ai_provider if (api_key and not is_compliant) else None,
        })
    except Exception as e:
        return jsonify({'error': f'Hold open device analysis failed: {str(e)}'}), 500

@app.route('/api/action_item/certivisible/<value>', methods=['GET'])
def slim_certivisible(value):
    try:
        api_key = request.args.get('api_key')
        model = request.args.get('model')
        ai_provider = request.args.get('ai_provider', 'openai')
        
        if value.lower() not in ['yes', 'no']:
            return jsonify({'error': 'Value must be "yes" or "no"'}), 400

        is_compliant = value.lower() == 'yes'

        action_items = []
        
        if api_key and not is_compliant:
            if not rate_limiter.can_make_call():
                return jsonify({'error': 'Rate limit exceeded', 'remaining_calls': rate_limiter.get_remaining_calls(), 'reset_in_seconds': rate_limiter.get_reset_time()}), 429
            
            if not model:
                model = DEFAULT_OPENAI_MODEL if ai_provider == 'openai' else DEFAULT_CLAUDE_MODEL
            
            real_key = resolve_api_key(api_key, ai_provider)
            if real_key:
                ai = analyze_gap_with_ai('certification_visible', value, 'boolean', real_key, model, ai_provider)
                if ai:
                    return jsonify(ai)
                action_items = []
        else:
            if not is_compliant:
                action_items.append({
                    'severity': 'high',
                    'category': 'Certification Visible Compliance',
                    'dueDate': get_due_date('high'),
                    'actionDescription': 'Certification is not visible. This is critical for fire door compliance.',
                    'remediationOptions': [
                        {'option': 'Option 1: Quick Fix - Locate Certification', 'plan': 'Locate and display existing certification.'},
                        {'option': 'Option 2: Standard Solution', 'plan': 'Obtain proper certification documentation and display.'},
                        {'option': 'Option 3: Comprehensive Fix', 'plan': 'Complete certification process with professional assessment.'},
                    ],
                    'confidenceScore': 95,
                })

        return jsonify({
            'success': True,
            'measurement_type': 'certification_visible',
            'value': value,
            'compliant': is_compliant,
            'severity': 'high' if not is_compliant else 'none',
            'actionItems': action_items,
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'ai' if (api_key and not is_compliant) else 'static',
            'ai_provider': ai_provider if (api_key and not is_compliant) else None,
        })
    except Exception as e:
        return jsonify({'error': f'Certification visible analysis failed: {str(e)}'}), 500

@app.route('/api/action_item/glazing/<value>', methods=['GET'])
def slim_glazing(value):
    try:
        api_key = request.args.get('api_key')
        model = request.args.get('model')
        ai_provider = request.args.get('ai_provider', 'openai')
        
        if value.lower() not in ['yes', 'no']:
            return jsonify({'error': 'Value must be "yes" or "no"'}), 400

        is_compliant = value.lower() == 'yes'

        action_items = []
        
        if api_key and not is_compliant:
            if not rate_limiter.can_make_call():
                return jsonify({'error': 'Rate limit exceeded', 'remaining_calls': rate_limiter.get_remaining_calls(), 'reset_in_seconds': rate_limiter.get_reset_time()}), 429
            
            if not model:
                model = DEFAULT_OPENAI_MODEL if ai_provider == 'openai' else DEFAULT_CLAUDE_MODEL
            
            real_key = resolve_api_key(api_key, ai_provider)
            if real_key:
                ai = analyze_gap_with_ai('contains_glazing', value, 'boolean', real_key, model, ai_provider)
                if ai:
                    return jsonify(ai)
                action_items = []
        else:
            if not is_compliant:
                action_items.append({
                    'severity': 'medium',
                    'category': 'Glazing Compliance',
                    'dueDate': get_due_date('medium'),
                    'actionDescription': 'Door contains glazing but may not be fire-rated.',
                    'remediationOptions': [
                        {'option': 'Option 1: Quick Fix - Assessment', 'plan': 'Assess existing glazing for fire rating.'},
                        {'option': 'Option 2: Standard Solution', 'plan': 'Replace with certified fire-rated glazing.'},
                        {'option': 'Option 3: Comprehensive Fix', 'plan': 'Complete glazing assessment and replacement with testing.'},
                    ],
                    'confidenceScore': 85,
                })

        return jsonify({
            'success': True,
            'measurement_type': 'contains_glazing',
            'value': value,
            'compliant': is_compliant,
            'severity': 'medium' if not is_compliant else 'none',
            'actionItems': action_items,
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'ai' if (api_key and not is_compliant) else 'static',
            'ai_provider': ai_provider if (api_key and not is_compliant) else None,
        })
    except Exception as e:
        return jsonify({'error': f'Glazing analysis failed: {str(e)}'}), 500

@app.route('/api/action_item/pyroglazing/<value>', methods=['GET'])
def slim_pyroglazing(value):
    try:
        api_key = request.args.get('api_key')
        model = request.args.get('model')
        ai_provider = request.args.get('ai_provider', 'openai')
        
        if value.lower() not in ['yes', 'no']:
            return jsonify({'error': 'Value must be "yes" or "no"'}), 400

        is_compliant = value.lower() == 'yes'

        action_items = []
        
        if api_key and not is_compliant:
            if not rate_limiter.can_make_call():
                return jsonify({'error': 'Rate limit exceeded', 'remaining_calls': rate_limiter.get_remaining_calls(), 'reset_in_seconds': rate_limiter.get_reset_time()}), 429
            
            if not model:
                model = DEFAULT_OPENAI_MODEL if ai_provider == 'openai' else DEFAULT_CLAUDE_MODEL
            
            real_key = resolve_api_key(api_key, ai_provider)
            if real_key:
                ai = analyze_gap_with_ai('pyro_glazing', value, 'boolean', real_key, model, ai_provider)
                if ai:
                    return jsonify(ai)
                action_items = []
        else:
            if not is_compliant:
                action_items.append({
                    'severity': 'high',
                    'category': 'Pyro Glazing Compliance',
                    'dueDate': get_due_date('high'),
                    'actionDescription': 'Pyro glazing is missing. Critical for fire door safety.',
                    'remediationOptions': [
                        {'option': 'Option 1: Quick Fix - Assessment', 'plan': 'Assess existing glazing for pyro rating.'},
                        {'option': 'Option 2: Standard Solution', 'plan': 'Replace with certified pyro glazing.'},
                        {'option': 'Option 3: Comprehensive Fix', 'plan': 'Complete pyro glazing installation with testing.'},
                    ],
                    'confidenceScore': 95,
                })

        return jsonify({
            'success': True,
            'measurement_type': 'pyro_glazing',
            'value': value,
            'compliant': is_compliant,
            'severity': 'high' if not is_compliant else 'none',
            'actionItems': action_items,
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'ai' if (api_key and not is_compliant) else 'static',
            'ai_provider': ai_provider if (api_key and not is_compliant) else None,
        })
    except Exception as e:
        return jsonify({'error': f'Pyro glazing analysis failed: {str(e)}'}), 500

@app.route('/api/keys', methods=['GET'])
def get_api_keys():
    """Get API keys from environment variables for the UI"""
    return jsonify({
        'openai_key': os.getenv('OPENAI_API_KEY', ''),
        'claude_key': os.getenv('CLAUDE_API_KEY', ''),
        'openai_model': os.getenv('OPENAI_MODEL', 'gpt-4o'),
        'claude_model': os.getenv('DEFAULT_AI_MODEL', 'claude-sonnet-4-20250514')
    })

@app.route('/debug', methods=['GET'])
def debug_endpoint():
    """Debug endpoint to check API key resolution and provider info"""
    api_key = request.args.get('api_key')
    ai_provider = request.args.get('ai_provider', 'openai')
    
    debug_info = {
        'provided_api_key': api_key,
        'ai_provider': ai_provider,
        'api_key_mapping': API_KEY_MAPPING,
        'resolved_key': resolve_api_key(api_key, ai_provider),
        'environment_vars': {
            'OPENAI_API_KEY': os.getenv('OPENAI_API_KEY'),
            'CLAUDE_API_KEY': os.getenv('CLAUDE_API_KEY'),
            'DEV_KEY': os.getenv('DEV_KEY'),
            'PROD_KEY': os.getenv('PROD_KEY'),
            'TEST_KEY': os.getenv('TEST_KEY'),
            'OPENAI_MODEL': os.getenv('OPENAI_MODEL', 'gpt-4o'),
            'DEFAULT_AI_MODEL': os.getenv('DEFAULT_AI_MODEL', 'claude-sonnet-4-20250514')
        }
    }
    
    return jsonify(debug_info)

@app.route('/')
def serve_comparison_ui():
    """Serve the comparison UI HTML file"""
    return send_file('comparison_ui.html')

@app.route('/comparison')
def serve_comparison_ui_alt():
    """Alternative route for comparison UI"""
    return send_file('comparison_ui.html')

@app.route('/api/action_item/analyze', methods=['POST'])
def analyze_measurement():
    """Unified endpoint for all fire door measurements with OpenAI and Claude support"""
    try:
        data = request.get_json() or {}
        measurement_type = data.get('measurement_type')
        value = data.get('value')
        unit = data.get('unit', 'mm')
        api_key = data.get('api_key')
        model = data.get('model')
        ai_provider = data.get('ai_provider', 'openai')
        
        # Validation
        if not data:
            return jsonify({'error': 'JSON data required'}), 400
        if not measurement_type:
            return jsonify({'error': 'measurement_type is required'}), 400
        if value is None:
            return jsonify({'error': 'value is required'}), 400
        
        # Define valid measurement types
        numeric_types = ['head', 'hinge', 'closing', 'threshold', 'doorthick', 'framedepth', 'doorsize']
        boolean_types = ['intustrips', 'selfclosing', 'shutsign', 'holddevice', 'certivisible', 'glazing', 'pyroglazing']
        all_types = numeric_types + boolean_types
        
        if measurement_type not in all_types:
            return jsonify({
                'error': f'Invalid measurement_type. Must be one of: {", ".join(all_types)}'
            }), 400
        
        # Validate AI provider
        if ai_provider not in ['openai', 'claude']:
            return jsonify({'error': 'ai_provider must be "openai" or "claude"'}), 400
        
        # Set default model if not provided
        if not model:
            model = DEFAULT_OPENAI_MODEL if ai_provider == 'openai' else DEFAULT_CLAUDE_MODEL
        
        # Handle numeric measurements
        if measurement_type in numeric_types:
            try:
                value = float(value)
            except (ValueError, TypeError):
                return jsonify({'error': 'Value must be a valid number for numeric measurements'}), 400
            
            # Call the appropriate function based on measurement type
            if measurement_type == 'head':
                return handle_numeric_measurement_unified('head', value, unit, api_key, model, ai_provider, 4, 'max_allowed')
            elif measurement_type == 'hinge':
                return handle_numeric_measurement_unified('hinge', value, unit, api_key, model, ai_provider, 4, 'max_allowed')
            elif measurement_type == 'closing':
                return handle_numeric_measurement_unified('closing', value, unit, api_key, model, ai_provider, 4, 'max_allowed')
            elif measurement_type == 'threshold':
                return handle_numeric_measurement_unified('threshold', value, unit, api_key, model, ai_provider, 4, 'max_allowed')
            elif measurement_type == 'doorthick':
                return handle_numeric_measurement_unified('door_thickness', value, unit, api_key, model, ai_provider, 20, 'min_required')
            elif measurement_type == 'framedepth':
                return handle_numeric_measurement_unified('frame_depth', value, unit, api_key, model, ai_provider, 55, 'min_required')
            elif measurement_type == 'doorsize':
                return handle_numeric_measurement_unified('door_size', value, unit, api_key, model, ai_provider, 500, 'min_required')
        
        # Handle boolean measurements
        elif measurement_type in boolean_types:
            if value.lower() not in ['yes', 'no']:
                return jsonify({'error': 'Value must be "yes" or "no" for boolean measurements'}), 400
            
            # Call the appropriate function based on measurement type
            if measurement_type == 'intustrips':
                return handle_boolean_measurement_unified('intumescent_strips', value, api_key, model, ai_provider, 'high')
            elif measurement_type == 'selfclosing':
                return handle_boolean_measurement_unified('self_closing_device', value, api_key, model, ai_provider, 'high')
            elif measurement_type == 'shutsign':
                return handle_boolean_measurement_unified('keep_shut_sign', value, api_key, model, ai_provider, 'medium')
            elif measurement_type == 'holddevice':
                return handle_boolean_measurement_unified('hold_open_device', value, api_key, model, ai_provider, 'medium')
            elif measurement_type == 'certivisible':
                return handle_boolean_measurement_unified('certification_visible', value, api_key, model, ai_provider, 'high')
            elif measurement_type == 'glazing':
                return handle_boolean_measurement_unified('contains_glazing', value, api_key, model, ai_provider, 'medium')
            elif measurement_type == 'pyroglazing':
                return handle_boolean_measurement_unified('pyro_glazing', value, api_key, model, ai_provider, 'high')
        
    except Exception as e:
        return jsonify({'error': f'Analysis failed: {str(e)}'}), 500


def handle_numeric_measurement_unified(gap_type, value, unit, api_key, model, ai_provider, threshold, threshold_type):
    """Handle numeric measurements (gaps, thickness, etc.) with AI provider support"""
    try:
        if threshold_type == 'max_allowed':
            is_compliant = value <= threshold
        else:  # min_required
            if value < threshold:
                return jsonify({'error': f'{gap_type} should be at least {threshold}mm'}), 400
            is_compliant = value == threshold  # Only exactly the threshold is compliant
        
        if api_key and not is_compliant:
            if not rate_limiter.can_make_call():
                return jsonify({'error': 'Rate limit exceeded', 'remaining_calls': rate_limiter.get_remaining_calls(), 'reset_in_seconds': rate_limiter.get_reset_time()}), 429
            
            real_key = resolve_api_key(api_key, ai_provider)
            if real_key:
                ai = analyze_gap_with_ai(gap_type, value, unit, real_key, model, ai_provider)
                if ai:
                    return jsonify(ai)
        
        # Generate static action items
        action_items = []
        if not is_compliant:
            severity = 'high' if threshold_type == 'max_allowed' else 'medium'
            category = gap_type.replace('_', ' ').title() + ' Compliance'
            
            if threshold_type == 'max_allowed':
                description = f'{gap_type.replace("_", " ").title()} ({value}mm) exceeds maximum allowed ({threshold}mm).'
            else:
                description = f'{gap_type.replace("_", " ").title()} ({value}mm) is below recommended minimum ({threshold}mm).'
            
            action_items.append({
                'severity': severity,
                'category': category,
                'dueDate': get_due_date(severity),
                'actionDescription': description,
                'remediationOptions': [
                    {'option': 'Option 1: Quick Fix', 'plan': f'Basic solution for {gap_type.replace("_", " ")}.'},
                    {'option': 'Option 2: Standard Solution', 'plan': f'Quality solution for {gap_type.replace("_", " ")}.'},
                    {'option': 'Option 3: Comprehensive Fix', 'plan': f'Premium solution with professional testing.'},
                ],
                'confidenceScore': 92 if threshold_type == 'max_allowed' else 85,
            })
        
        result = {
            'success': True,
            'measurement_type': f'{gap_type}_gap' if threshold_type == 'max_allowed' else gap_type,
            'value': value,
            'unit': unit,
            'compliant': is_compliant,
            'severity': severity if not is_compliant else 'none',
            'actionItems': action_items,
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'ai' if (api_key and not is_compliant) else 'static',
            'ai_provider': ai_provider if (api_key and not is_compliant) else None,
        }
        
        if threshold_type == 'max_allowed':
            result['max_allowed'] = threshold
        else:
            result['min_required'] = threshold
            
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'error': f'{gap_type} analysis failed: {str(e)}'}), 500


def handle_boolean_measurement_unified(measurement_type, value, api_key, model, ai_provider, default_severity):
    """Handle boolean measurements (yes/no values) with AI provider support"""
    try:
        is_compliant = value.lower() == 'yes'
        
        action_items = []
        
        if api_key and not is_compliant:
            if not rate_limiter.can_make_call():
                return jsonify({'error': 'Rate limit exceeded', 'remaining_calls': rate_limiter.get_remaining_calls(), 'reset_in_seconds': rate_limiter.get_reset_time()}), 429
            
            real_key = resolve_api_key(api_key, ai_provider)
            if real_key:
                ai = analyze_gap_with_ai(measurement_type, value, 'boolean', real_key, model, ai_provider)
                if ai:
                    return jsonify(ai)
                action_items = []
        else:
            if not is_compliant:
                category = measurement_type.replace('_', ' ').title() + ' Compliance'
                description = f'{measurement_type.replace("_", " ").title()} is missing. This is critical for fire door compliance.'
                
                action_items.append({
                    'severity': default_severity,
                    'category': category,
                    'dueDate': get_due_date(default_severity),
                    'actionDescription': description,
                    'remediationOptions': [
                        {'option': 'Option 1: Quick Fix', 'plan': f'Install basic {measurement_type.replace("_", " ")} immediately.'},
                        {'option': 'Option 2: Standard Solution', 'plan': f'Install quality {measurement_type.replace("_", " ")} with proper setup.'},
                        {'option': 'Option 3: Comprehensive Fix', 'plan': f'Complete {measurement_type.replace("_", " ")} installation with testing.'},
                    ],
                    'confidenceScore': 95 if default_severity == 'high' else 85,
                })
        
        return jsonify({
            'success': True,
            'measurement_type': measurement_type,
            'value': value,
            'compliant': is_compliant,
            'severity': default_severity if not is_compliant else 'none',
            'actionItems': action_items,
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'ai' if (api_key and not is_compliant) else 'static',
            'ai_provider': ai_provider if (api_key and not is_compliant) else None,
        })
        
    except Exception as e:
        return jsonify({'error': f'{measurement_type} analysis failed: {str(e)}'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=True, host='0.0.0.0', port=port)