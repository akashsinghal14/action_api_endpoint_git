from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import openai
import anthropic
import json
import re
import time
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import os
from dotenv import load_dotenv
from collections import OrderedDict

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
CORS(app)

# Cache Configuration
CACHE_TTL = int(os.getenv('CACHE_TTL_HOURS', 24)) * 60 * 60  # 24 hours in seconds
MAX_CACHE_SIZE = int(os.getenv('MAX_CACHE_SIZE', 1000))
CACHE_CLEANUP_INTERVAL = int(os.getenv('CACHE_CLEANUP_INTERVAL', 3600))  # 1 hour
ENABLE_CACHING = os.getenv('ENABLE_CACHING', 'true').lower() == 'true'
AUTO_WARM_CACHE = os.getenv('AUTO_WARM_CACHE', 'true').lower() == 'true'

print(f"Cache enabled: {ENABLE_CACHING}, TTL: {CACHE_TTL/3600} hours, Max size: {MAX_CACHE_SIZE}")
print(f"Auto warm cache: {AUTO_WARM_CACHE}")

# In-Memory Cache with TTL and LRU eviction
class OptimizedCache:
    def __init__(self, max_size: int = 1000, ttl: int = 86400):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.ttl = ttl
        self.stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'total_requests': 0
        }
        self.lock = threading.RLock()
        self._start_cleanup_task()
    
    def _start_cleanup_task(self):
        """Start background cleanup task"""
        def cleanup_loop():
            while True:
                time.sleep(CACHE_CLEANUP_INTERVAL)
                self._cleanup_expired()
        
        cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
        cleanup_thread.start()
    
    def _cleanup_expired(self):
        """Remove expired entries from cache"""
        with self.lock:
            current_time = time.time()
            expired_keys = []
            
            for key, data in self.cache.items():
                if current_time - data['timestamp'] > self.ttl:
                    expired_keys.append(key)
            
            for key in expired_keys:
                del self.cache[key]
            
            if expired_keys:
                print(f"Cache cleanup: removed {len(expired_keys)} expired entries")
    
    def get(self, key: str) -> Optional[Dict]:
        """Get value from cache"""
        with self.lock:
            self.stats['total_requests'] += 1
            
            if key not in self.cache:
                self.stats['misses'] += 1
                return None
            
            data = self.cache[key]
            current_time = time.time()
            
            # Check if expired
            if current_time - data['timestamp'] > self.ttl:
                del self.cache[key]
                self.stats['misses'] += 1
                return None
            
            # Move to end (LRU)
            self.cache.move_to_end(key)
            self.stats['hits'] += 1
            return data['response']
    
    def set(self, key: str, value: Dict):
        """Set value in cache"""
        with self.lock:
            current_time = time.time()
            
            # Remove oldest entries if cache is full
            while len(self.cache) >= self.max_size:
                oldest_key = next(iter(self.cache))
                del self.cache[oldest_key]
                self.stats['evictions'] += 1
            
            self.cache[key] = {
                'response': value,
                'timestamp': current_time
            }
    
    def get_stats(self) -> Dict:
        """Get cache statistics"""
        with self.lock:
            total = self.stats['hits'] + self.stats['misses']
            hit_rate = (self.stats['hits'] / total * 100) if total > 0 else 0
            
            return {
                'hits': self.stats['hits'],
                'misses': self.stats['misses'],
                'hit_rate': round(hit_rate, 2),
                'evictions': self.stats['evictions'],
                'total_requests': self.stats['total_requests'],
                'current_size': len(self.cache),
                'max_size': self.max_size,
                'ttl_hours': self.ttl / 3600
            }
    
    def clear(self):
        """Clear all cache entries"""
        with self.lock:
            self.cache.clear()
            self.stats = {
                'hits': 0,
                'misses': 0,
                'evictions': 0,
                'total_requests': 0
            }

# Initialize cache
cache = OptimizedCache(MAX_CACHE_SIZE, CACHE_TTL)

# Unified API Key Mapping - Maps client keys to real AI keys
API_KEY_MAPPING = {
    # OpenAI keys
    'openai_key': os.getenv('OPENAI_API_KEY'),
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
        now = time.time()
        self.calls = [t for t in self.calls if now - t < self.time_window]
        if len(self.calls) < self.max_calls:
            self.calls.append(now)
            return True
        return False
    
    def get_remaining_calls(self):
        now = time.time()
        self.calls = [t for t in self.calls if now - t < self.time_window]
        return max(0, self.max_calls - len(self.calls))
    
    def get_reset_time(self):
        if not self.calls:
            return 0
        now = time.time()
        oldest = min(self.calls)
        return max(0, self.time_window - (now - oldest))

rate_limiter = RateLimiter()

def get_category_for_measurement(measurement_type: str) -> str:
    """Get appropriate category for measurement type"""
    category_mapping = {
        # Gap measurements
        'head': 'Firedoor Repair',
        'hinge': 'Firedoor Repair', 
        'closing': 'Firedoor Repair',
        'threshold': 'Firedoor Repair',
        
        # Door measurements
        'door_thickness': 'Door Repair',
        'frame_depth': 'Door Repair',
        'door_size': 'Door Repair',
        
        # Boolean measurements
        'intumescent_strips': 'Firedoor Repair',
        'self_closing_device': 'Firedoor Repair',
        'keep_shut_sign': 'Signage repair',
        'hold_open_device': 'Firedoor Repair',
        'certification_visible': 'Testing, Records, Log Book',
        'glazing': 'Firedoor Repair',
        'pyro_glazing': 'Firedoor Repair',
        'door_close_fully': 'Firedoor Repair',
        'hinges_fire_rated': 'Firedoor Repair',
        'cold_smoke_seals': 'Firedoor Repair',
        'keep_locked_sign': 'Signage repair'
    }
    
    return category_mapping.get(measurement_type, 'Firedoor Repair')

def get_due_date(severity: str) -> str:
    if severity == 'critical':
        days = 0  # Today
    elif severity == 'high':
        days = 30
    elif severity == 'medium':
        days = 90
    elif severity == 'low':
        days = 180
    else:
        days = 90  # Default to medium
    
    # Use UTC time to avoid timezone issues
    from datetime import timezone
    date = datetime.now(timezone.utc) + timedelta(days=days)
    
    # Debug logging
    print(f"Due date calculation: severity={severity}, days={days}, date={date.strftime('%d/%m/%Y')}")
    
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
        'claude-sonnet-4-20250514': {'input': 0.003, 'output': 0.015},
        'claude-3-5-sonnet-20241022': {'input': 0.003, 'output': 0.015},
        'claude-3-5-sonnet-20240620': {'input': 0.003, 'output': 0.015},
        'claude-3-opus-20240229': {'input': 0.015, 'output': 0.075},
        'claude-3-haiku-20240307': {'input': 0.00025, 'output': 0.00125},
    }
    
    model_pricing = pricing.get(model, pricing['claude-sonnet-4-20250514'])
    
    input_cost = (input_tokens / 1000) * model_pricing['input']
    output_cost = (output_tokens / 1000) * model_pricing['output']
    
    return round(input_cost + output_cost, 6)

def resolve_api_key(client_key: Optional[str], provider: str = 'openai') -> Optional[str]:
    """Resolve API key for the specified provider"""
    if not client_key:
        return None
    
    # Check if key is in mapping
    if client_key in API_KEY_MAPPING:
        real = API_KEY_MAPPING[client_key]
        if real:
            if provider == 'openai' and real.startswith('sk-'):
                return real
            elif provider == 'claude' and real.startswith('sk-ant-'):
                return real
            elif provider == 'openai' and real.startswith('sk-ant-'):
                # This is a Claude key, but user wants OpenAI - return None
                return None
            elif provider == 'claude' and real.startswith('sk-') and not real.startswith('sk-ant-'):
                # This is an OpenAI key, but user wants Claude - return None
                return None
    
    # Check if it's a direct API key
    if provider == 'openai' and client_key.startswith('sk-') and not client_key.startswith('sk-ant-'):
        return client_key
    elif provider == 'claude' and client_key.startswith('sk-ant-'):
        return client_key
    
    return None

def parse_openai_response(ai_response):
    """Parse OpenAI response - optimized for speed"""
    try:
        # Use compiled regex for better performance
        json_pattern = re.compile(r'\{[\s\S]*\}')
        json_match = json_pattern.search(ai_response)
        
        if json_match:
            parsed = json.loads(json_match.group(0))
            if 'actionItems' in parsed and isinstance(parsed['actionItems'], list):
                # Process due dates efficiently
                for item in parsed['actionItems']:
                    due_date = item.get('dueDate', '')
                    if due_date == 'DD/MM/YYYY' or re.match(r'\d{2}/\d{2}/\d{4}', due_date):
                        severity = item.get('severity', 'medium')
                        item['dueDate'] = get_due_date(severity)
                return parsed['actionItems']
        
        raise ValueError('Invalid response format')
    except Exception as e:
        print(f"Parsing error: {e}")
        raise ValueError('OpenAI response parsing failed')

def parse_claude_response(ai_response):
    """Parse Claude response - optimized for speed"""
    try:
        # Use compiled regex for better performance
        json_pattern = re.compile(r'\{[\s\S]*\}')
        json_match = json_pattern.search(ai_response)
        
        if json_match:
            parsed = json.loads(json_match.group(0))
            if 'actionItems' in parsed and isinstance(parsed['actionItems'], list):
                # Process due dates efficiently
                for item in parsed['actionItems']:
                    due_date = item.get('dueDate', '')
                    if due_date == 'DD/MM/YYYY' or re.match(r'\d{2}/\d{2}/\d{4}', due_date):
                        severity = item.get('severity', 'medium')
                        item['dueDate'] = get_due_date(severity)
                return parsed['actionItems']
        
        raise ValueError('Invalid response format')
    except Exception as e:
        print(f"Parsing error: {e}")
        raise ValueError('Claude response parsing failed')

def create_openai_prompt(survey_data):
    """Create prompt for OpenAI - optimized for speed"""
    data_lines = []
    
    # Build focused prompt based on what data is provided
    if 'headGap' in survey_data:
        data_lines.append(f"Head Gap: {survey_data['headGap']}mm")
    if 'hingeGap' in survey_data:
        data_lines.append(f"Hinge Gap: {survey_data['hingeGap']}mm")
    if 'closingGap' in survey_data:
        data_lines.append(f"Closing Gap: {survey_data['closingGap']}mm")
    if 'thresholdGap' in survey_data:
        data_lines.append(f"Threshold Gap: {survey_data['thresholdGap']}mm")
    if 'doorThickness' in survey_data:
        data_lines.append(f"Door Thickness: {survey_data['doorThickness']}mm")
    if 'frameDepth' in survey_data:
        data_lines.append(f"Frame Depth: {survey_data['frameDepth']}mm")
    if 'doorSize' in survey_data:
        data_lines.append(f"Door Size: {survey_data['doorSize']}mm")
    if 'intumescent_strips' in survey_data:
        data_lines.append(f"Intumescent Strips: {survey_data['intumescent_strips']}")
    if 'self_closing_device' in survey_data:
        data_lines.append(f"Self-closing Device: {survey_data['self_closing_device']}")
    if 'keep_shut_sign' in survey_data:
        data_lines.append(f"Keep Shut Sign: {survey_data['keep_shut_sign']}")
    if 'hold_open_device' in survey_data:
        data_lines.append(f"Hold Open Device: {survey_data['hold_open_device']}")
    if 'certification_visible' in survey_data:
        data_lines.append(f"Certification Visible: {survey_data['certification_visible']}")
    if 'glazing' in survey_data:
        data_lines.append(f"Glazing: {survey_data['glazing']}")
    if 'pyro_glazing' in survey_data:
        data_lines.append(f"Pyro Glazing: {survey_data['pyro_glazing']}")
    if 'door_close_fully' in survey_data:
        data_lines.append(f"Door Close Fully: {survey_data['door_close_fully']}")
    if 'hinges_fire_rated' in survey_data:
        data_lines.append(f"Hinges Fire Rated: {survey_data['hinges_fire_rated']}")
    if 'cold_smoke_seals' in survey_data:
        data_lines.append(f"Cold Smoke Seals: {survey_data['cold_smoke_seals']}")
    if 'keep_locked_sign' in survey_data:
        data_lines.append(f"Keep Locked Sign: {survey_data['keep_locked_sign']}")
    
    survey_text = "\n".join(data_lines) if data_lines else "No measurements provided"
    
    # Optimized prompt - 60% smaller than original
    return f"""UK fire safety expert. Analyze measurement and provide action items.

RULES:
- Gaps: Max 4mm (head, hinge, closing, threshold)
- Thickness: Only 44mm compliant
- Frame: Only 100mm compliant  
- Door: Only 500mm compliant
- Boolean measurements: Only "yes" is compliant, "no" is NON-COMPLIANT and requires action items

Data: {survey_text}

IMPORTANT: For boolean measurements, if the value is "no", the door is NON-COMPLIANT and you MUST provide action items.

Return JSON:
{{
    "actionItems": [
        {{
            "severity": "critical|high|medium|low",
            "category": "Firedoor Repair|Signage repair|Fire door Replacement|Testing, Records, Log Book|Door Replacement required|Door Repair",
            "dueDate": "DD/MM/YYYY",
            "actionDescription": "description",
            "remediationOptions": [
                {{"option": "Option 1: ", "plan": "steps"}},
                {{"option": "Option 2: ", "plan": "steps"}},
                {{"option": "Option 3: ", "plan": "steps"}}
            ],
            "confidenceScore": "70-98"
        }}
    ]
}}

IMPORTANT: For the "category" field, you MUST choose ONLY from these 6 values:
- Firedoor Repair
- Signage repair  
- Fire door Replacement
- Testing, Records, Log Book
- Door Replacement required
- Door Repair

ANALYZE the action items and remediation options you provide, then choose the most appropriate category based on the actual work required. For example:
- If action involves replacing the entire door → "Fire door Replacement"
- If action involves installing/repairing signs → "Signage repair"
- If action involves adjusting gaps, strips, hinges → "Firedoor Repair"
- If action involves updating records, testing → "Testing, Records, Log Book"
- If action involves door replacement due to thickness → "Door Replacement required"
- If action involves minor door repairs → "Door Repair"

For "confidenceScore", choose a value between 70-98 based on:
- 90-98%: High confidence (well-established solutions, precise measurements, clear compliance requirements)
- 80-89%: Medium-high confidence (standard solutions, some minor uncertainties)
- 70-79%: Medium confidence (complex issues, multiple variables, or less certain solutions)
- Consider: measurement precision, solution complexity, compliance certainty, and potential variables

If compliant (all measurements meet requirements), return empty actionItems array."""

def create_claude_prompt(survey_data):
    """Create prompt for Claude - optimized for speed"""
    data_lines = []
    
    # Build focused prompt based on what data is provided
    if 'headGap' in survey_data:
        data_lines.append(f"Head Gap: {survey_data['headGap']}mm")
    if 'hingeGap' in survey_data:
        data_lines.append(f"Hinge Gap: {survey_data['hingeGap']}mm")
    if 'closingGap' in survey_data:
        data_lines.append(f"Closing Gap: {survey_data['closingGap']}mm")
    if 'thresholdGap' in survey_data:
        data_lines.append(f"Threshold Gap: {survey_data['thresholdGap']}mm")
    if 'doorThickness' in survey_data:
        data_lines.append(f"Door Thickness: {survey_data['doorThickness']}mm")
    if 'frameDepth' in survey_data:
        data_lines.append(f"Frame Depth: {survey_data['frameDepth']}mm")
    if 'doorSize' in survey_data:
        data_lines.append(f"Door Size: {survey_data['doorSize']}mm")
    if 'intumescent_strips' in survey_data:
        data_lines.append(f"Intumescent Strips: {survey_data['intumescent_strips']}")
    if 'self_closing_device' in survey_data:
        data_lines.append(f"Self-closing Device: {survey_data['self_closing_device']}")
    if 'keep_shut_sign' in survey_data:
        data_lines.append(f"Keep Shut Sign: {survey_data['keep_shut_sign']}")
    if 'hold_open_device' in survey_data:
        data_lines.append(f"Hold Open Device: {survey_data['hold_open_device']}")
    if 'certification_visible' in survey_data:
        data_lines.append(f"Certification Visible: {survey_data['certification_visible']}")
    if 'glazing' in survey_data:
        data_lines.append(f"Glazing: {survey_data['glazing']}")
    if 'pyro_glazing' in survey_data:
        data_lines.append(f"Pyro Glazing: {survey_data['pyro_glazing']}")
    if 'door_close_fully' in survey_data:
        data_lines.append(f"Door Close Fully: {survey_data['door_close_fully']}")
    if 'hinges_fire_rated' in survey_data:
        data_lines.append(f"Hinges Fire Rated: {survey_data['hinges_fire_rated']}")
    if 'cold_smoke_seals' in survey_data:
        data_lines.append(f"Cold Smoke Seals: {survey_data['cold_smoke_seals']}")
    if 'keep_locked_sign' in survey_data:
        data_lines.append(f"Keep Locked Sign: {survey_data['keep_locked_sign']}")
    
    survey_text = "\n".join(data_lines) if data_lines else "No measurements provided"
    
    # Optimized prompt - 60% smaller than original
    return f"""UK fire safety expert. Analyze measurement and provide action items.

RULES:
- Gaps: Max 4mm (head, hinge, closing, threshold)
- Thickness: Only 44mm compliant
- Frame: Only 100mm compliant  
- Door: Only 500mm compliant
- Boolean measurements: Only "yes" is compliant, "no" is NON-COMPLIANT and requires action items

Data: {survey_text}

IMPORTANT: For boolean measurements, if the value is "no", the door is NON-COMPLIANT and you MUST provide action items.

Return JSON:
{{
    "actionItems": [
        {{
            "severity": "critical|high|medium|low",
            "category": "Firedoor Repair|Signage repair|Fire door Replacement|Testing, Records, Log Book|Door Replacement required|Door Repair",
            "dueDate": "DD/MM/YYYY",
            "actionDescription": "description",
            "remediationOptions": [
                {{"option": "Option 1: ", "plan": "steps"}},
                {{"option": "Option 2: ", "plan": "steps"}},
                {{"option": "Option 3: ", "plan": "steps"}}
            ],
            "confidenceScore": "70-98"
        }}
    ]
}}

IMPORTANT: For the "category" field, you MUST choose ONLY from these 6 values:
- Firedoor Repair
- Signage repair  
- Fire door Replacement
- Testing, Records, Log Book
- Door Replacement required
- Door Repair

ANALYZE the action items and remediation options you provide, then choose the most appropriate category based on the actual work required. For example:
- If action involves replacing the entire door → "Fire door Replacement"
- If action involves installing/repairing signs → "Signage repair"
- If action involves adjusting gaps, strips, hinges → "Firedoor Repair"
- If action involves updating records, testing → "Testing, Records, Log Book"
- If action involves door replacement due to thickness → "Door Replacement required"
- If action involves minor door repairs → "Door Repair"

For "confidenceScore", choose a value between 70-98 based on:
- 90-98%: High confidence (well-established solutions, precise measurements, clear compliance requirements)
- 80-89%: Medium-high confidence (standard solutions, some minor uncertainties)
- 70-79%: Medium confidence (complex issues, multiple variables, or less certain solutions)
- Consider: measurement precision, solution complexity, compliance certainty, and potential variables

If compliant (all measurements meet requirements), return empty actionItems array."""

def analyze_gap_with_ai(gap_type, value, unit, api_key, model, provider):
    """Analyze gap with AI provider - with caching"""
    try:
        # Create cache key
        cache_key = f"{gap_type}:{value}:{unit}:{provider}:{model}"
        
        # Check cache first
        if ENABLE_CACHING:
            cached_response = cache.get(cache_key)
            if cached_response:
                print(f"Cache HIT for {gap_type}: {value} ({provider})")
                return cached_response
        
        print(f"Cache MISS for {gap_type}: {value} - calling {provider} API")
        
        # Create focused survey data
        survey_data = {}
        if gap_type == 'door_thickness':
            survey_data = {'doorThickness': value}
        elif gap_type == 'frame_depth':
            survey_data = {'frameDepth': value}
        elif gap_type == 'door_size':
            survey_data = {'doorSize': value}
        elif gap_type in ['intumescent_strips', 'self_closing_device', 'keep_shut_sign', 'hold_open_device', 'certification_visible', 'glazing', 'pyro_glazing', 'door_close_fully', 'hinges_fire_rated', 'cold_smoke_seals', 'keep_locked_sign']:
            survey_data = {gap_type: value}
        else:
            survey_data = {f'{gap_type}Gap': value}
        
        if provider == 'openai':
            prompt = create_openai_prompt(survey_data)
        else:
            prompt = create_claude_prompt(survey_data)
        
        # Rate limiting check
        if not rate_limiter.can_make_call():
            raise Exception('Rate limit exceeded')
        
        if provider == 'openai':
            # OpenAI API call
            client = openai.OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1000,
                temperature=0.3
            )
            
            ai_response = response.choices[0].message.content
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens
            total_tokens = response.usage.total_tokens
            cost = calculate_openai_cost(model, input_tokens, output_tokens)
            
            print(f"OpenAI API response for {gap_type}: {ai_response[:100]}...")
            action_items = parse_openai_response(ai_response)
            print(f"Parsed action items for {gap_type}: {len(action_items)} items")
            print(f"Cost for {gap_type}: ${cost} (Input: {input_tokens}, Output: {output_tokens})")
            
        else:  # Claude
            # Claude API call
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=model,
                max_tokens=1000,
                temperature=0.3,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            ai_response = response.content[0].text
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            total_tokens = input_tokens + output_tokens
            cost = calculate_claude_cost(model, input_tokens, output_tokens)
            
            print(f"Claude API response for {gap_type}: {ai_response[:100]}...")
            action_items = parse_claude_response(ai_response)
            print(f"Parsed action items for {gap_type}: {len(action_items)} items")
            print(f"Cost for {gap_type}: ${cost} (Input: {input_tokens}, Output: {output_tokens})")

        # Determine compliance
        if gap_type == 'door_thickness':
            min_thickness = 44
            compliant = value == min_thickness
            max_gap = None
        elif gap_type == 'frame_depth':
            min_depth = 100
            compliant = value == min_depth
            min_thickness = None
            max_gap = None
        elif gap_type == 'door_size':
            min_size = 500
            compliant = value == min_size
            min_thickness = None
            max_gap = None
        elif gap_type in ['intumescent_strips', 'self_closing_device', 'keep_shut_sign', 'hold_open_device', 'certification_visible', 'glazing', 'pyro_glazing', 'door_close_fully', 'hinges_fire_rated', 'cold_smoke_seals', 'keep_locked_sign']:
            compliant = str(value).lower() == 'yes'
            min_thickness = None
            max_gap = None
        else:
            max_gap = 4
            # Ensure value is numeric for gap measurements
            try:
                numeric_value = float(value)
                compliant = numeric_value <= max_gap
            except (ValueError, TypeError):
                # If value can't be converted to float, treat as non-compliant
                compliant = False
            min_thickness = None

        # Determine severity
        ai_severity = 'none'
        if action_items:
            severities = [item.get('severity', 'low') for item in action_items]
            if 'critical' in severities:
                ai_severity = 'critical'
            elif 'high' in severities:
                ai_severity = 'high'
            elif 'medium' in severities:
                ai_severity = 'medium'
            elif 'low' in severities:
                ai_severity = 'low'

        # Build response
        response_data = {
            'success': True,
            'measurement_type': gap_type if gap_type in ['intumescent_strips', 'self_closing_device', 'keep_shut_sign', 'hold_open_device', 'certification_visible', 'glazing', 'pyro_glazing', 'door_close_fully', 'hinges_fire_rated', 'cold_smoke_seals', 'keep_locked_sign'] else f'{gap_type}_gap',
            'value': value,
            'unit': unit if gap_type not in ['intumescent_strips', 'self_closing_device', 'keep_shut_sign', 'hold_open_device', 'certification_visible', 'glazing', 'pyro_glazing', 'door_close_fully', 'hinges_fire_rated', 'cold_smoke_seals', 'keep_locked_sign'] else None,
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
        
        # Add threshold information
        if gap_type == 'door_thickness':
            response_data['min_required'] = min_thickness
        elif gap_type == 'frame_depth':
            response_data['min_required'] = min_depth
        elif gap_type == 'door_size':
            response_data['min_required'] = min_size
        elif gap_type not in ['intumescent_strips', 'self_closing_device', 'keep_shut_sign', 'hold_open_device', 'certification_visible', 'glazing', 'pyro_glazing', 'door_close_fully', 'hinges_fire_rated']:
            response_data['max_allowed'] = max_gap
        
        # Cache the response
        if ENABLE_CACHING:
            cache.set(cache_key, response_data)
            print(f"Cached response for {gap_type}: {value} ({provider})")
        
        return response_data
        
    except Exception as e:
        print(f"Error in analyze_gap_with_ai: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return None

# Auto Cache Warming Function
def warm_cache_automatically():
    """Automatically warm cache with common parameter combinations"""
    if not AUTO_WARM_CACHE:
        print("Auto cache warming disabled")
        return
    
    print("🔥 Starting automatic cache warming...")
    
    # Common parameter combinations that users typically test
    common_combinations = [
        # Non-compliant numeric values (will trigger AI) - head, hinge, threshold only with values 5-8
        {"measurement_type": "head", "value": 5, "unit": "mm", "api_key": "claude_key", "ai_provider": "claude"},
        {"measurement_type": "head", "value": 6, "unit": "mm", "api_key": "claude_key", "ai_provider": "claude"},
        {"measurement_type": "head", "value": 7, "unit": "mm", "api_key": "claude_key", "ai_provider": "claude"},
        {"measurement_type": "head", "value": 8, "unit": "mm", "api_key": "claude_key", "ai_provider": "claude"},
        {"measurement_type": "hinge", "value": 5, "unit": "mm", "api_key": "claude_key", "ai_provider": "claude"},
        {"measurement_type": "hinge", "value": 6, "unit": "mm", "api_key": "claude_key", "ai_provider": "claude"},
        {"measurement_type": "hinge", "value": 7, "unit": "mm", "api_key": "claude_key", "ai_provider": "claude"},
        {"measurement_type": "hinge", "value": 8, "unit": "mm", "api_key": "claude_key", "ai_provider": "claude"},
        {"measurement_type": "threshold", "value": 5, "unit": "mm", "api_key": "claude_key", "ai_provider": "claude"},
        {"measurement_type": "threshold", "value": 6, "unit": "mm", "api_key": "claude_key", "ai_provider": "claude"},
        {"measurement_type": "threshold", "value": 7, "unit": "mm", "api_key": "claude_key", "ai_provider": "claude"},
        {"measurement_type": "threshold", "value": 8, "unit": "mm", "api_key": "claude_key", "ai_provider": "claude"},
        
        # All boolean values (will trigger AI)
        {"measurement_type": "intustrips", "value": "no", "api_key": "claude_key", "ai_provider": "claude"},
        {"measurement_type": "selfclosing", "value": "no", "api_key": "claude_key", "ai_provider": "claude"},
        {"measurement_type": "shutsign", "value": "no", "api_key": "claude_key", "ai_provider": "claude"},
        {"measurement_type": "holddevice", "value": "no", "api_key": "claude_key", "ai_provider": "claude"},
        {"measurement_type": "certivisible", "value": "no", "api_key": "claude_key", "ai_provider": "claude"},
        {"measurement_type": "glazing", "value": "no", "api_key": "claude_key", "ai_provider": "claude"},
        {"measurement_type": "pyroglazing", "value": "no", "api_key": "claude_key", "ai_provider": "claude"},
        {"measurement_type": "doorclosefully", "value": "no", "api_key": "claude_key", "ai_provider": "claude"},
        {"measurement_type": "hingesfirerated", "value": "no", "api_key": "claude_key", "ai_provider": "claude"},
        {"measurement_type": "coldsmokeseals", "value": "no", "api_key": "claude_key", "ai_provider": "claude"},
        {"measurement_type": "keepLockedSign", "value": "no", "api_key": "claude_key", "ai_provider": "claude"},
        
        # Compliant values (static responses)
        {"measurement_type": "head", "value": 2, "unit": "mm", "api_key": None},
        {"measurement_type": "hinge", "value": 3, "unit": "mm", "api_key": None},
        {"measurement_type": "threshold", "value": 2, "unit": "mm", "api_key": None},
        {"measurement_type": "intustrips", "value": "yes", "api_key": None},
        {"measurement_type": "selfclosing", "value": "yes", "api_key": None},
        {"measurement_type": "shutsign", "value": "yes", "api_key": None},
        {"measurement_type": "holddevice", "value": "yes", "api_key": None},
        {"measurement_type": "certivisible", "value": "yes", "api_key": None},
        {"measurement_type": "glazing", "value": "yes", "api_key": None},
        {"measurement_type": "pyroglazing", "value": "yes", "api_key": None},
        {"measurement_type": "doorclosefully", "value": "yes", "api_key": None},
        {"measurement_type": "hingesfirerated", "value": "yes", "api_key": None},
        {"measurement_type": "coldsmokeseals", "value": "yes", "api_key": None},
        {"measurement_type": "keepLockedSign", "value": "yes", "api_key": None},
    ]
    
    successful_warms = 0
    failed_warms = 0
    
    for i, combo in enumerate(common_combinations):
        try:
            print(f"  Warming {i+1}/{len(common_combinations)}: {combo['measurement_type']} = {combo['value']}")
            
            # Simulate the API call internally instead of making HTTP requests
            measurement_type = combo['measurement_type']
            value = combo['value']
            unit = combo.get('unit', 'mm')
            api_key = combo.get('api_key')
            ai_provider = combo.get('ai_provider', 'claude')
            
            # Set default model if not provided
            model = DEFAULT_OPENAI_MODEL if ai_provider == 'openai' else DEFAULT_CLAUDE_MODEL
            
            # Handle numeric measurements
            if measurement_type in ['head', 'hinge', 'threshold']:
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    print(f"    ❌ Invalid numeric value: {value}")
                    failed_warms += 1
                    continue
                
                # Call the appropriate function based on measurement type
                if measurement_type == 'head':
                    result = handle_numeric_measurement_internal('head', value, unit, api_key, model, ai_provider, 4, 'max_allowed')
                elif measurement_type == 'hinge':
                    result = handle_numeric_measurement_internal('hinge', value, unit, api_key, model, ai_provider, 4, 'max_allowed')
                elif measurement_type == 'threshold':
                    result = handle_numeric_measurement_internal('threshold', value, unit, api_key, model, ai_provider, 4, 'max_allowed')
            
            # Handle boolean measurements
            elif measurement_type in ['intustrips', 'selfclosing', 'shutsign', 'holddevice', 'certivisible', 'glazing', 'pyroglazing', 'doorclosefully', 'hingesfirerated', 'coldsmokeseals', 'keepLockedSign']:
                if str(value).lower() not in ['yes', 'no']:
                    print(f"    ❌ Invalid boolean value: {value}")
                    failed_warms += 1
                    continue
                
                # Call the appropriate function based on measurement type
                if measurement_type == 'intustrips':
                    result = handle_boolean_measurement_internal('intumescent_strips', str(value), api_key, model, ai_provider, 'critical')
                elif measurement_type == 'selfclosing':
                    result = handle_boolean_measurement_internal('self_closing_device', str(value), api_key, model, ai_provider, 'critical')
                elif measurement_type == 'shutsign':
                    result = handle_boolean_measurement_internal('keep_shut_sign', str(value), api_key, model, ai_provider, 'medium')
                elif measurement_type == 'holddevice':
                    result = handle_boolean_measurement_internal('hold_open_device', str(value), api_key, model, ai_provider, 'medium')
                elif measurement_type == 'certivisible':
                    result = handle_boolean_measurement_internal('certification_visible', str(value), api_key, model, ai_provider, 'high')
                elif measurement_type == 'glazing':
                    result = handle_boolean_measurement_internal('glazing', str(value), api_key, model, ai_provider, 'medium')
                elif measurement_type == 'pyroglazing':
                    result = handle_boolean_measurement_internal('pyro_glazing', str(value), api_key, model, ai_provider, 'high')
                elif measurement_type == 'doorclosefully':
                    result = handle_boolean_measurement_internal('door_close_fully', str(value), api_key, model, ai_provider, 'critical')
                elif measurement_type == 'hingesfirerated':
                    result = handle_boolean_measurement_internal('hinges_fire_rated', str(value), api_key, model, ai_provider, 'critical')
                elif measurement_type == 'coldsmokeseals':
                    result = handle_boolean_measurement_internal('cold_smoke_seals', str(value), api_key, model, ai_provider, 'critical')
                elif measurement_type == 'keepLockedSign':
                    result = handle_boolean_measurement_internal('keep_locked_sign', str(value), api_key, model, ai_provider, 'high')
            
            if result and result.get('success'):
                analysis_type = result.get('analysis_type', 'unknown')
                print(f"    ✅ {analysis_type} analysis")
                successful_warms += 1
            else:
                print(f"    ❌ Failed to process")
                failed_warms += 1
                
        except Exception as e:
            print(f"    ❌ Error: {str(e)[:50]}...")
            failed_warms += 1
    
    print(f"\n📊 Auto Cache Warming Results:")
    print(f"  ✅ Successful: {successful_warms}")
    print(f"  ❌ Failed: {failed_warms}")
    print(f"  🎯 Success rate: {(successful_warms/(successful_warms+failed_warms)*100):.1f}%")
    print("🔥 Cache warming complete!")

def handle_numeric_measurement_internal(gap_type, value, unit, api_key, model, ai_provider, threshold, threshold_type):
    """Handle numeric measurements internally for cache warming"""
    try:
        if threshold_type == 'max_allowed':
            is_compliant = value <= threshold
        else:  # min_required
            if value < threshold:
                return None
            is_compliant = value == threshold  # Only exactly the threshold is compliant
        
        if api_key and not is_compliant:
            if not rate_limiter.can_make_call():
                return None
            
            real_key = resolve_api_key(api_key, ai_provider)
            if real_key:
                ai = analyze_gap_with_ai(gap_type, value, unit, real_key, model, ai_provider)
                if ai:
                    return ai
        
        # Generate static action items
        action_items = []
        if not is_compliant:
            severity = 'critical' if threshold_type == 'max_allowed' else 'medium'
            category = get_category_for_measurement(gap_type)
            
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
                    {'option': 'Option 1: ', 'plan': f'Basic solution for {gap_type.replace("_", " ")}.'},
                    {'option': 'Option 2: ', 'plan': f'Quality solution for {gap_type.replace("_", " ")}.'},
                    {'option': 'Option 3: ', 'plan': f'Premium solution with professional testing.'},
                ],
                'confidenceScore': 98 if threshold_type == 'max_allowed' else 85,
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
            
        return result
        
    except Exception as e:
        print(f"Error in handle_numeric_measurement_internal: {e}")
        return None

def handle_boolean_measurement_internal(measurement_type, value, api_key, model, ai_provider, default_severity):
    """Handle boolean measurements internally for cache warming"""
    try:
        is_compliant = value.lower() == 'yes'
        
        action_items = []
        
        if api_key and not is_compliant:
            if not rate_limiter.can_make_call():
                return None
            
            real_key = resolve_api_key(api_key, ai_provider)
            if real_key:
                ai = analyze_gap_with_ai(measurement_type, value, 'boolean', real_key, model, ai_provider)
                if ai:
                    return ai
                action_items = []
        else:
            if not is_compliant:
                category = get_category_for_measurement(measurement_type)
                description = f'{measurement_type.replace("_", " ").title()} is missing. This is critical for fire door compliance.'
                
                action_items.append({
                    'severity': default_severity,
                    'category': category,
                    'dueDate': get_due_date(default_severity),
                    'actionDescription': description,
                    'remediationOptions': [
                        {'option': 'Option 1: ', 'plan': f'Install basic {measurement_type.replace("_", " ")} immediately.'},
                        {'option': 'Option 2: ', 'plan': f'Install quality {measurement_type.replace("_", " ")} with proper setup.'},
                        {'option': 'Option 3: ', 'plan': f'Complete {measurement_type.replace("_", " ")} installation with testing.'},
                    ],
                    'confidenceScore': 98 if default_severity == 'critical' else (95 if default_severity == 'high' else 85),
                })
        
        return {
            'success': True,
            'measurement_type': measurement_type,
            'value': value,
            'compliant': is_compliant,
            'severity': default_severity if not is_compliant else 'none',
            'actionItems': action_items,
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'ai' if (api_key and not is_compliant) else 'static',
            'ai_provider': ai_provider if (api_key and not is_compliant) else None,
        }
        
    except Exception as e:
        print(f"Error in handle_boolean_measurement_internal: {e}")
        return None

# API Endpoints - Same structure as original app.py

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
            
            if not model:
                model = DEFAULT_OPENAI_MODEL if ai_provider == 'openai' else DEFAULT_CLAUDE_MODEL
            
            real_key = resolve_api_key(api_key, ai_provider)
            if real_key:
                ai = analyze_gap_with_ai('head', value, unit, real_key, model, ai_provider)
                if ai:
                    return jsonify(ai)

        action_items = []
        if not is_compliant:
            action_items.append({
                'severity': 'critical',
                'category': get_category_for_measurement('head'),
                'dueDate': get_due_date('critical'),
                'actionDescription': f'Head gap ({value}mm) exceeds maximum allowed ({max_gap}mm).',
                'remediationOptions': [
                    {'option': 'Option 1:  - Basic Strips', 'plan': 'Install basic intumescent strips at the head.'},
                    {'option': 'Option 2:  - Quality Strips', 'plan': 'Install high-quality strips; adjust alignment if needed.'},
                    {'option': 'Option 3: ', 'plan': 'Premium strips with smoke seals and full alignment.'},
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
            'severity': 'critical' if not is_compliant else 'none',
            'actionItems': action_items,
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'ai' if (api_key and not is_compliant) else 'static',
            'ai_provider': ai_provider if (api_key and not is_compliant) else None,
        })
    except Exception as e:
        return jsonify({'error': f'Head gap analysis failed: {str(e)}'}), 500

# Add other endpoints here - same pattern as head but with caching
# For brevity, I'll add the unified endpoint and monitoring endpoints

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
        boolean_types = ['intustrips', 'selfclosing', 'shutsign', 'holddevice', 'certivisible', 'glazing', 'pyroglazing', 'doorclosefully', 'hingesfirerated', 'coldsmokeseals', 'keepLockedSign']
        all_types = numeric_types + boolean_types
        
        if measurement_type not in all_types:
            return jsonify({
                'error': f'Invalid measurement_type. Must be one of: {", ".join(all_types)}'
            }), 400
        
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
                return handle_numeric_measurement_unified('door_thickness', value, unit, api_key, model, ai_provider, 44, 'min_required')
            elif measurement_type == 'framedepth':
                return handle_numeric_measurement_unified('frame_depth', value, unit, api_key, model, ai_provider, 100, 'min_required')
            elif measurement_type == 'doorsize':
                return handle_numeric_measurement_unified('door_size', value, unit, api_key, model, ai_provider, 500, 'min_required')
        
        # Handle boolean measurements
        elif measurement_type in boolean_types:
            if value.lower() not in ['yes', 'no']:
                return jsonify({'error': 'Value must be "yes" or "no" for boolean measurements'}), 400
            
            # Call the appropriate function based on measurement type
            if measurement_type == 'intustrips':
                return handle_boolean_measurement_unified('intumescent_strips', value, api_key, model, ai_provider, 'critical', 'intustrips')
            elif measurement_type == 'selfclosing':
                return handle_boolean_measurement_unified('self_closing_device', value, api_key, model, ai_provider, 'critical', 'selfclosing')
            elif measurement_type == 'shutsign':
                return handle_boolean_measurement_unified('keep_shut_sign', value, api_key, model, ai_provider, 'medium', 'shutsign')
            elif measurement_type == 'holddevice':
                return handle_boolean_measurement_unified('hold_open_device', value, api_key, model, ai_provider, 'medium', 'holddevice')
            elif measurement_type == 'certivisible':
                return handle_boolean_measurement_unified('certification_visible', value, api_key, model, ai_provider, 'high', 'certivisible')
            elif measurement_type == 'glazing':
                return handle_boolean_measurement_unified('glazing', value, api_key, model, ai_provider, 'medium', 'glazing')
            elif measurement_type == 'pyroglazing':
                return handle_boolean_measurement_unified('pyro_glazing', value, api_key, model, ai_provider, 'high', 'pyroglazing')
            elif measurement_type == 'doorclosefully':
                return handle_boolean_measurement_unified('door_close_fully', value, api_key, model, ai_provider, 'critical', 'doorclosefully')
            elif measurement_type == 'hingesfirerated':
                return handle_boolean_measurement_unified('hinges_fire_rated', value, api_key, model, ai_provider, 'critical', 'hingesfirerated')
            elif measurement_type == 'coldsmokeseals':
                return handle_boolean_measurement_unified('cold_smoke_seals', value, api_key, model, ai_provider, 'critical', 'coldsmokeseals')
            elif measurement_type == 'keepLockedSign':
                return handle_boolean_measurement_unified('keep_locked_sign', value, api_key, model, ai_provider, 'high', 'keepLockedSign')
        
    except Exception as e:
        return jsonify({'error': f'Analysis failed: {str(e)}'}), 500

def handle_numeric_measurement_unified(gap_type, value, unit, api_key, model, ai_provider, threshold, threshold_type):
    """Handle numeric measurements with AI provider support"""
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
            severity = 'critical' if threshold_type == 'max_allowed' else 'medium'
            category = get_category_for_measurement(gap_type)
            
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
                    {'option': 'Option 1: ', 'plan': f'Basic solution for {gap_type.replace("_", " ")}.'},
                    {'option': 'Option 2: ', 'plan': f'Quality solution for {gap_type.replace("_", " ")}.'},
                    {'option': 'Option 3: ', 'plan': f'Premium solution with professional testing.'},
                ],
                'confidenceScore': 98 if threshold_type == 'max_allowed' else 85,
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

def handle_boolean_measurement_unified(measurement_type, value, api_key, model, ai_provider, default_severity, original_measurement_type=None):
    """Handle boolean measurements with AI provider support"""
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
                    # Map the response back to the original measurement type
                    if original_measurement_type:
                        ai['measurement_type'] = original_measurement_type
                    return jsonify(ai)
                action_items = []
        else:
            if not is_compliant:
                category = get_category_for_measurement(measurement_type)
                description = f'{measurement_type.replace("_", " ").title()} is missing. This is critical for fire door compliance.'
                
                action_items.append({
                    'severity': default_severity,
                    'category': category,
                    'dueDate': get_due_date(default_severity),
                    'actionDescription': description,
                    'remediationOptions': [
                        {'option': 'Option 1: ', 'plan': f'Install basic {measurement_type.replace("_", " ")} immediately.'},
                        {'option': 'Option 2: ', 'plan': f'Install quality {measurement_type.replace("_", " ")} with proper setup.'},
                        {'option': 'Option 3: ', 'plan': f'Complete {measurement_type.replace("_", " ")} installation with testing.'},
                    ],
                    'confidenceScore': 98 if default_severity == 'critical' else (95 if default_severity == 'high' else 85),
                })
        
        # Use original measurement type for response if provided, otherwise use internal name
        response_measurement_type = original_measurement_type if original_measurement_type else measurement_type
        
        return jsonify({
            'success': True,
            'measurement_type': response_measurement_type,
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

# Monitoring Endpoints

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'cache_enabled': ENABLE_CACHING,
        'auto_warm_enabled': AUTO_WARM_CACHE,
        'cache_stats': cache.get_stats()
    })

@app.route('/metrics', methods=['GET'])
def get_metrics():
    """Performance metrics endpoint"""
    return jsonify({
        'cache_stats': cache.get_stats(),
        'rate_limiter': {
            'remaining_calls': rate_limiter.get_remaining_calls(),
            'reset_in_seconds': rate_limiter.get_reset_time()
        },
        'app_info': {
            'openai_model': DEFAULT_OPENAI_MODEL,
            'claude_model': DEFAULT_CLAUDE_MODEL,
            'cache_ttl_hours': CACHE_TTL / 3600,
            'max_cache_size': MAX_CACHE_SIZE,
            'auto_warm_enabled': AUTO_WARM_CACHE
        }
    })

@app.route('/cache/stats', methods=['GET'])
def get_cache_stats():
    """Cache statistics endpoint"""
    return jsonify(cache.get_stats())

@app.route('/cache/clear', methods=['POST'])
def clear_cache():
    """Clear cache endpoint (admin)"""
    cache.clear()
    return jsonify({'message': 'Cache cleared successfully'})

@app.route('/warmup', methods=['POST'])
def manual_warmup():
    """Manual cache warmup endpoint"""
    try:
        warm_cache_automatically()
        return jsonify({'message': 'Cache warming completed successfully'})
    except Exception as e:
        return jsonify({'error': f'Cache warming failed: {str(e)}'}), 500

@app.route('/api/keys', methods=['GET'])
def get_api_keys():
    """Get API keys from environment variables for the UI"""
    return jsonify({
        'openai_key': os.getenv('OPENAI_API_KEY', ''),
        'claude_key': os.getenv('CLAUDE_API_KEY', ''),
        'openai_model': os.getenv('OPENAI_MODEL', 'gpt-4o'),
        'claude_model': os.getenv('DEFAULT_AI_MODEL', 'claude-sonnet-4-20250514')
    })

@app.route('/')
def serve_comparison_ui():
    """Serve the comparison UI HTML file"""
    return send_file('comparison_ui.html')

@app.route('/comparison')
def serve_comparison_ui_alt():
    """Alternative route for comparison UI"""
    return send_file('comparison_ui.html')

# Auto warm cache on startup - moved to app initialization
def start_cache_warming():
    """Start cache warming in background thread during app initialization"""
    if AUTO_WARM_CACHE:
        print("🔥 Starting automatic cache warming during app startup...")
        def warm_in_background():
            time.sleep(3)  # Wait 3 seconds for the app to be fully ready
            warm_cache_automatically()
        
        threading.Thread(target=warm_in_background, daemon=True).start()
    else:
        print("Cache warming disabled")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    print(f"🚀 Starting Flask Fire Door Compliance API with Auto Cache Warming")
    print(f"📊 Port: {port}")
    print(f"🧠 AI Providers: OpenAI + Claude")
    print(f"💾 Caching: Enabled (24-hour TTL)")
    print(f"🔥 Auto Warm: {AUTO_WARM_CACHE}")
    print("-" * 50)
    
    # Start cache warming during app initialization
    start_cache_warming()
    
    app.run(debug=True, host='0.0.0.0', port=port)
