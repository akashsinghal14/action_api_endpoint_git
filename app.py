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
import base64
import requests
from urllib.parse import urlparse
from PIL import Image
import io

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

# Image optimization configuration
MAX_IMAGE_SIZE_MB = 20
MAX_IMAGE_DIMENSION = 512  # Resize images to max 512px on longest side
JPEG_QUALITY = 65  # Good balance between quality and file size

# Connection pooling for requests
session = requests.Session()
session.headers.update({'User-Agent': 'FireDoorCompliance/1.0'})

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

def get_compliance_category(measurement_type: str, action_description: str = '') -> str:
    """Get compliance category based on measurement type and action description
    
    NOTE: This is a FALLBACK function. The AI (OpenAI/Claude) is instructed to provide
    complianceCategory in its response. This function is only used if the AI doesn't provide it.
    
    Returns one of the following UK fire door compliance categories:
    - Building Regulations Part B: General fire safety requirements
    - BS 476 / BS EN 1634: Fire resistance testing standards
    - BS 8214: Fire door assembly code of practice
    - BS 5499: Signage standards
    - Regulatory Reform (Fire Safety) Order 2005: Legal requirements
    - BS EN 13501: Fire classification standards
    """
    # Normalize measurement type
    measurement_lower = measurement_type.lower()
    action_lower = action_description.lower()
    
    # Signage-related issues -> BS 5499
    if 'sign' in measurement_lower or 'signage' in action_lower:
        return 'BS 5499'
    
    # Certification and testing -> Regulatory Reform (Fire Safety) Order 2005
    if 'certification' in measurement_lower or 'certificate' in action_lower or 'testing' in action_lower or 'records' in action_lower:
        return 'Regulatory Reform (Fire Safety) Order 2005'
    
    # Gap measurements (head, hinge, closing, threshold) -> BS 8214
    if measurement_lower in ['head', 'hinge', 'closing', 'threshold'] or 'gap' in action_lower:
        return 'BS 8214'
    
    # Door thickness, frame depth, door size -> BS 476 / BS EN 1634 (Fire resistance)
    if measurement_lower in ['door_thickness', 'frame_depth', 'door_size'] or 'thickness' in action_lower or 'depth' in action_lower:
        return 'BS 476 / BS EN 1634'
    
    # Intumescent strips and smoke seals -> BS 8214
    if 'intumescent' in measurement_lower or 'smoke seal' in measurement_lower or 'intumescent' in action_lower or 'smoke seal' in action_lower:
        return 'BS 8214'
    
    # Self-closing devices, hold open devices -> Building Regulations Part B
    if 'self_closing' in measurement_lower or 'hold_open' in measurement_lower or 'self-closing' in action_lower or 'hold open' in action_lower:
        return 'Building Regulations Part B'
    
    # Glazing and pyro glazing -> BS EN 13501 (Fire classification)
    if 'glazing' in measurement_lower or 'glazing' in action_lower or 'glass' in action_lower:
        return 'BS EN 13501'
    
    # Hinges and door close -> BS 8214
    if 'hinge' in measurement_lower or 'door_close' in measurement_lower or 'hinge' in action_lower:
        return 'BS 8214'
    
    # Door replacement -> BS 476 / BS EN 1634
    if 'replacement' in action_lower or 'replace' in action_lower:
        return 'BS 476 / BS EN 1634'
    
    # Door damage and visual defects -> BS 8214 (door assembly integrity)
    if 'door_damage' in measurement_lower or 'visual_defect' in measurement_lower or 'damage' in action_lower:
        return 'BS 8214'
    
    # Full doorset size and number of hinges -> BS 8214
    if 'full_doorset_size' in measurement_lower or 'no_of_hinges' in measurement_lower:
        return 'BS 8214'
    
    # Default: BS 8214 (most common for fire door assemblies)
    return 'BS 8214'

def get_compliance_category_description(compliance_category: str) -> str:
    """Get description for compliance category"""
    descriptions = {
        'Building Regulations Part B': 'General fire safety requirements, self-closing devices, hold-open devices, and operational fire safety measures required by UK Building Regulations.',
        'BS 476 / BS EN 1634': 'Fire resistance testing standards. Applies to door thickness, frame depth, door size measurements, and door replacement actions that relate to fire resistance performance.',
        'BS 8214': 'Fire door assembly code of practice. Applies to gap measurements (head, hinge, closing, threshold), intumescent strips, smoke seals, hinges, door closing mechanisms, and general fire door assembly components.',
        'BS 5499': 'Signage standards. Applies to keep shut signs, keep locked signs, and any signage-related compliance issues.',
        'Regulatory Reform (Fire Safety) Order 2005': 'Legal requirements related to certification visibility, testing documentation, records, log books, and administrative compliance obligations.',
        'BS EN 13501': 'Fire classification standards. Applies to glazing, pyro glazing, glass-related issues, and fire-rated glazing components.'
    }
    return descriptions.get(compliance_category, 'UK fire door compliance standard.')

def map_compliance_check_to_measurement_type(compliance_check_name: str) -> str:
    """Map compliance check name to internal measurement type"""
    check_lower = compliance_check_name.lower()
    
    # Map compliance check names to measurement types
    if 'damage' in check_lower and 'door' in check_lower:
        return 'door_damage'
    elif 'visual defect' in check_lower:
        return 'visual_defects'
    elif 'hinge' in check_lower and 'fire rated' in check_lower:
        return 'hinges_fire_rated'
    elif 'cold smoke seal' in check_lower:
        return 'cold_smoke_seals'
    elif 'intumescent strip' in check_lower:
        return 'intumescent_strips'
    elif 'door close fully' in check_lower or 'close fully' in check_lower:
        return 'door_close_fully'
    elif 'glazing' in check_lower and 'contain' in check_lower:
        return 'glazing'
    elif 'keep locked sign' in check_lower:
        return 'keep_locked_sign'
    elif 'keep shut sign' in check_lower:
        return 'keep_shut_sign'
    elif 'certification visible' in check_lower:
        return 'certification_visible'
    elif 'pyro glazing' in check_lower:
        return 'pyro_glazing'
    elif 'hold open device' in check_lower:
        return 'hold_open_device'
    elif 'self closing device' in check_lower or 'self-closing' in check_lower:
        return 'self_closing_device'
    else:
        return 'unknown'

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
            "complianceCategory": "Building Regulations Part B|BS 476 / BS EN 1634|BS 8214|BS 5499|Regulatory Reform (Fire Safety) Order 2005|BS EN 13501",
            "dueDate": "DD/MM/YYYY",
            "actionDescription": "description",
            "remediationOptions": [
                {{"option": "Option 1: Quick Fix", "plan": "steps"}},
                {{"option": "Option 2: Standard Solution", "plan": "steps"}},
                {{"option": "Option 3: Comprehensive Fix", "plan": "steps"}}
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

CRITICAL: For the "complianceCategory" field, you MUST analyze the action description and remediation options to determine which UK fire door compliance standard/regulation applies. Choose ONLY ONE from these 6 values:

1. "Building Regulations Part B" - Use for general fire safety requirements, self-closing devices, hold-open devices, and operational fire safety measures required by UK Building Regulations.

2. "BS 476 / BS EN 1634" - Use for fire resistance testing standards. Applies to door thickness, frame depth, door size measurements, and door replacement actions that relate to fire resistance performance.

3. "BS 8214" - Use for fire door assembly code of practice. Applies to gap measurements (head, hinge, closing, threshold), intumescent strips, smoke seals, hinges, door closing mechanisms, and general fire door assembly components.

4. "BS 5499" - Use for signage standards. Applies to keep shut signs, keep locked signs, and any signage-related compliance issues.

5. "Regulatory Reform (Fire Safety) Order 2005" - Use for legal requirements related to certification visibility, testing documentation, records, log books, and administrative compliance obligations.

6. "BS EN 13501" - Use for fire classification standards. Applies to glazing, pyro glazing, glass-related issues, and fire-rated glazing components.

ANALYZE the specific action and remediation to determine the most appropriate compliance category. Consider:
- What type of component or measurement is being addressed?
- What UK standard or regulation specifically governs this requirement?
- Which compliance framework would an inspector reference for this issue?

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
            "complianceCategory": "Building Regulations Part B|BS 476 / BS EN 1634|BS 8214|BS 5499|Regulatory Reform (Fire Safety) Order 2005|BS EN 13501",
            "dueDate": "DD/MM/YYYY",
            "actionDescription": "description",
            "remediationOptions": [
                {{"option": "Option 1: Quick Fix", "plan": "steps"}},
                {{"option": "Option 2: Standard Solution", "plan": "steps"}},
                {{"option": "Option 3: Comprehensive Fix", "plan": "steps"}}
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

CRITICAL: For the "complianceCategory" field, you MUST analyze the action description and remediation options to determine which UK fire door compliance standard/regulation applies. Choose ONLY ONE from these 6 values:

1. "Building Regulations Part B" - Use for general fire safety requirements, self-closing devices, hold-open devices, and operational fire safety measures required by UK Building Regulations.

2. "BS 476 / BS EN 1634" - Use for fire resistance testing standards. Applies to door thickness, frame depth, door size measurements, and door replacement actions that relate to fire resistance performance.

3. "BS 8214" - Use for fire door assembly code of practice. Applies to gap measurements (head, hinge, closing, threshold), intumescent strips, smoke seals, hinges, door closing mechanisms, and general fire door assembly components.

4. "BS 5499" - Use for signage standards. Applies to keep shut signs, keep locked signs, and any signage-related compliance issues.

5. "Regulatory Reform (Fire Safety) Order 2005" - Use for legal requirements related to certification visibility, testing documentation, records, log books, and administrative compliance obligations.

6. "BS EN 13501" - Use for fire classification standards. Applies to glazing, pyro glazing, glass-related issues, and fire-rated glazing components.

ANALYZE the specific action and remediation to determine the most appropriate compliance category. Consider:
- What type of component or measurement is being addressed?
- What UK standard or regulation specifically governs this requirement?
- Which compliance framework would an inspector reference for this issue?

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
            # AI should provide complianceCategory, but use fallback if missing
            for item in action_items:
                if 'complianceCategory' not in item or not item.get('complianceCategory'):
                    # Fallback: Use hardcoded logic only if AI didn't provide complianceCategory
                    action_desc = item.get('actionDescription', '')
                    item['complianceCategory'] = get_compliance_category(gap_type, action_desc)
                    print(f"  Fallback: Added complianceCategory using rule-based logic for {gap_type}")
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
            # AI should provide complianceCategory, but use fallback if missing
            for item in action_items:
                if 'complianceCategory' not in item or not item.get('complianceCategory'):
                    # Fallback: Use hardcoded logic only if AI didn't provide complianceCategory
                    action_desc = item.get('actionDescription', '')
                    item['complianceCategory'] = get_compliance_category(gap_type, action_desc)
                    print(f"  Fallback: Added complianceCategory using rule-based logic for {gap_type}")
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
    
    # Warm batch cache for measurements and compliance checks
    print("\n🔥 Warming batch cache for measurements and compliance checks...")
    batch_successful = 0
    batch_failed = 0
    
    # All measurement types for batch cache
    batch_measurement_types = [
        'Head', 'Hinge', 'Closing', 'Threshold', 
        'DoorThickness', 'FrameDepth', 'DoorSize', 
        'FullDoorsetSize', 'NoOfHinges'
    ]
    
    # All compliance check names
    batch_compliance_checks = [
        'Any damage to the door?',
        'Any Visual defects on the door?',
        'Are all hinges fire rated?',
        'Are there cold smoke seals?',
        'Are there intumescent strips?',
        'Does the door close fully?',
        'Does the door contain glazing?',
        'Fire door Keep Locked sign?',
        'Fire door Keep Shut sign?',
        'Is certification visible on fire door?',
        'Is glazing pyro glazing?',
        'Is there a hold open device?',
        'Self closing device?'
    ]
    
    # Get API key for batch warming (use OpenAI)
    batch_api_key = resolve_api_key('openai_key', 'openai')
    if not batch_api_key:
        print("  ⚠️  No OpenAI API key available for batch cache warming, skipping...")
    else:
        batch_model = DEFAULT_OPENAI_MODEL
        
        # Warm measurements cache (one at a time to avoid rate limits)
        measurement_mapping = {
            'Head': ('head', 4, 'max_allowed'),
            'Hinge': ('hinge', 4, 'max_allowed'),
            'Closing': ('closing', 4, 'max_allowed'),
            'Threshold': ('threshold', 4, 'max_allowed'),
            'DoorThickness': ('door_thickness', 44, 'min_required'),
            'FrameDepth': ('frame_depth', 100, 'min_required'),
            'DoorSize': ('door_size', 500, 'min_required'),
            'FullDoorsetSize': ('full_doorset_size', 500, 'min_required'),
            'NoOfHinges': ('no_of_hinges', 3, 'min_required')
        }
        
        for i, measurement_name in enumerate(batch_measurement_types):
            try:
                measurement_type, threshold, threshold_type = measurement_mapping[measurement_name]
                
                # Use a non-compliant value (doesn't matter what value, just needs to be non-compliant)
                if threshold_type == 'max_allowed':
                    test_value = threshold + 1  # Non-compliant
                else:
                    test_value = threshold - 1  # Non-compliant
                
                print(f"  Warming batch measurement {i+1}/{len(batch_measurement_types)}: {measurement_name}")
                
                measurements_list = [{
                    'measurementName': measurement_name,
                    'value': test_value,
                    'threshold': threshold,
                    'thresholdType': threshold_type
                }]
                
                result = analyze_batch_with_ai(measurements_list, [], batch_api_key, batch_model)
                
                if result and result.get('measurements'):
                    print(f"    ✅ Cached: {measurement_name}")
                    batch_successful += 1
                else:
                    print(f"    ❌ Failed to cache: {measurement_name}")
                    batch_failed += 1
                
                # Small delay to avoid rate limits
                time.sleep(0.5)
                
            except Exception as e:
                print(f"    ❌ Error warming {measurement_name}: {str(e)[:50]}...")
                batch_failed += 1
        
        # Warm compliance checks cache (one at a time)
        for i, check_name in enumerate(batch_compliance_checks):
            try:
                print(f"  Warming batch compliance check {i+1}/{len(batch_compliance_checks)}: {check_name}")
                
                compliance_checks_list = [{
                    'ComplianceCheckName': check_name,
                    'NonCompliantCount': 1  # Value doesn't matter, just needs to be > 0
                }]
                
                result = analyze_batch_with_ai([], compliance_checks_list, batch_api_key, batch_model)
                
                if result and result.get('complianceChecks'):
                    print(f"    ✅ Cached: {check_name}")
                    batch_successful += 1
                else:
                    print(f"    ❌ Failed to cache: {check_name}")
                    batch_failed += 1
                
                # Small delay to avoid rate limits
                time.sleep(0.5)
                
            except Exception as e:
                print(f"    ❌ Error warming {check_name}: {str(e)[:50]}...")
                batch_failed += 1
    
    print(f"\n📊 Auto Cache Warming Results:")
    print(f"  ✅ Successful: {successful_warms}")
    print(f"  ❌ Failed: {failed_warms}")
    print(f"  🎯 Success rate: {(successful_warms/(successful_warms+failed_warms)*100):.1f}%")
    if batch_api_key:
        print(f"\n📊 Batch Cache Warming Results:")
        print(f"  ✅ Successful: {batch_successful}")
        print(f"  ❌ Failed: {batch_failed}")
        print(f"  🎯 Success rate: {(batch_successful/(batch_successful+batch_failed)*100):.1f}%")
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
                    {'option': 'Option 1: Quick Fix', 'plan': f'Basic solution for {gap_type.replace("_", " ")}.'},
                    {'option': 'Option 2: Standard Solution', 'plan': f'Quality solution for {gap_type.replace("_", " ")}.'},
                    {'option': 'Option 3: Comprehensive Fix', 'plan': f'Premium solution with professional testing.'},
                ],
                'confidenceScore': 98 if threshold_type == 'max_allowed' else 85,
                'complianceCategory': get_compliance_category(gap_type, description),
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
                        {'option': 'Option 1: Quick Fix', 'plan': f'Install basic {measurement_type.replace("_", " ")} immediately.'},
                        {'option': 'Option 2: Standard Solution', 'plan': f'Install quality {measurement_type.replace("_", " ")} with proper setup.'},
                        {'option': 'Option 3: Comprehensive Fix', 'plan': f'Complete {measurement_type.replace("_", " ")} installation with testing.'},
                    ],
                    'confidenceScore': 98 if default_severity == 'critical' else (95 if default_severity == 'high' else 85),
                    'complianceCategory': get_compliance_category(measurement_type, description),
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
            description = f'Head gap ({value}mm) exceeds maximum allowed ({max_gap}mm).'
            action_items.append({
                'severity': 'critical',
                'category': get_category_for_measurement('head'),
                'dueDate': get_due_date('critical'),
                'actionDescription': description,
                'remediationOptions': [
                    {'option': 'Option 1: Quick Fix - Basic Strips', 'plan': 'Install basic intumescent strips at the head.'},
                    {'option': 'Option 2: Standard Solution - Quality Strips', 'plan': 'Install high-quality strips; adjust alignment if needed.'},
                    {'option': 'Option 3: Comprehensive Fix', 'plan': 'Premium strips with smoke seals and full alignment.'},
                ],
                'confidenceScore': 92,
                'complianceCategory': get_compliance_category('head', description),
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

def create_batch_prompt(measurements_list, compliance_checks_list):
    """Create prompt for batch analysis with OpenAI"""
    prompt_parts = []
    
    # Add measurements section
    if measurements_list:
        prompt_parts.append("NON-COMPLIANT MEASUREMENTS:")
        for m in measurements_list:
            prompt_parts.append(f"- {m['measurementName']}: {m['value']}mm (Threshold: {m['threshold']}mm, Type: {m['thresholdType']})")
        prompt_parts.append("")
    
    # Add compliance checks section
    if compliance_checks_list:
        prompt_parts.append("NON-COMPLIANT COMPLIANCE CHECKS:")
        for c in compliance_checks_list:
            prompt_parts.append(f"- {c['ComplianceCheckName']}: {c['NonCompliantCount']} non-compliant items")
        prompt_parts.append("")
    
    data_text = "\n".join(prompt_parts)
    
    return f"""You are a UK fire safety compliance expert. Analyze the following non-compliant fire door measurements and compliance checks.

For each item, determine the appropriate UK fire door compliance category and provide a description.

{data_text}

Return a JSON object with the following structure:
{{
    "measurements": [
        {{
            "measurementName": "Head",
            "complianceCategory": "Building Regulations Part B|BS 476 / BS EN 1634|BS 8214|BS 5499|Regulatory Reform (Fire Safety) Order 2005|BS EN 13501",
            "complianceCategoryDescription": "Detailed description of what this compliance category covers and why it applies to this measurement"
        }}
    ],
    "complianceChecks": [
        {{
            "ComplianceCheckName": "Any damage to the door?",
            "complianceCategory": "Building Regulations Part B|BS 476 / BS EN 1634|BS 8214|BS 5499|Regulatory Reform (Fire Safety) Order 2005|BS EN 13501",
            "complianceCategoryDescription": "Detailed description of what this compliance category covers and why it applies to this compliance check"
        }}
    ]
}}

CRITICAL: For the "complianceCategory" field, you MUST choose ONLY ONE from these 6 values:

1. "Building Regulations Part B" - Use for general fire safety requirements, self-closing devices, hold-open devices, and operational fire safety measures required by UK Building Regulations.

2. "BS 476 / BS EN 1634" - Use for fire resistance testing standards. Applies to door thickness, frame depth, door size measurements, and door replacement actions that relate to fire resistance performance.

3. "BS 8214" - Use for fire door assembly code of practice. Applies to gap measurements (head, hinge, closing, threshold), intumescent strips, smoke seals, hinges, door closing mechanisms, and general fire door assembly components.

4. "BS 5499" - Use for signage standards. Applies to keep shut signs, keep locked signs, and any signage-related compliance issues.

5. "Regulatory Reform (Fire Safety) Order 2005" - Use for legal requirements related to certification visibility, testing documentation, records, log books, and administrative compliance obligations.

6. "BS EN 13501" - Use for fire classification standards. Applies to glazing, pyro glazing, glass-related issues, and fire-rated glazing components.

For "complianceCategoryDescription", provide a clear, detailed explanation (2-3 sentences) that:
- Explains what the compliance category/standard covers
- Explains why it specifically applies to this measurement or compliance check
- Helps users understand the regulatory context

ANALYZE each item carefully and determine the most appropriate compliance category based on:
- What type of component or measurement is being addressed?
- What UK standard or regulation specifically governs this requirement?
- Which compliance framework would an inspector reference for this issue?

Return ONLY valid JSON, no additional text."""

def analyze_batch_with_ai(measurements_list, compliance_checks_list, api_key, model):
    """Analyze batch measurements and compliance checks with OpenAI API - with caching"""
    try:
        # Check cache for each item first
        cached_measurements = {}
        uncached_measurements = []
        
        for m in measurements_list:
            cache_key = f"batch:measurement:{m['measurementName']}"
            if ENABLE_CACHING:
                cached = cache.get(cache_key)
                if cached:
                    cached_measurements[m['measurementName']] = cached
                    print(f"Cache HIT for measurement: {m['measurementName']}")
                    continue
            uncached_measurements.append(m)
        
        cached_checks = {}
        uncached_checks = []
        
        for c in compliance_checks_list:
            cache_key = f"batch:compliance:{c['ComplianceCheckName']}"
            if ENABLE_CACHING:
                cached = cache.get(cache_key)
                if cached:
                    cached_checks[c['ComplianceCheckName']] = cached
                    print(f"Cache HIT for compliance check: {c['ComplianceCheckName']}")
                    continue
            uncached_checks.append(c)
        
        # If all items are cached, return cached results
        if not uncached_measurements and not uncached_checks:
            print("All items found in cache, returning cached results")
            result = {
                'measurements': [cached_measurements[name] for name in [m['measurementName'] for m in measurements_list]],
                'complianceChecks': [cached_checks[name] for name in [c['ComplianceCheckName'] for c in compliance_checks_list]],
                'tokens_used': 0,
                'input_tokens': 0,
                'output_tokens': 0,
                'cost_usd': 0
            }
            return result
        
        # Only call API for uncached items
        if uncached_measurements or uncached_checks:
            print(f"Cache MISS: {len(uncached_measurements)} measurements, {len(uncached_checks)} compliance checks - calling OpenAI API")
            
            # Create prompt only for uncached items
            prompt = create_batch_prompt(uncached_measurements, uncached_checks)
            
            # Rate limiting check
            if not rate_limiter.can_make_call():
                raise Exception('Rate limit exceeded')
            
            # Call OpenAI API
            client = openai.OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=2000,  # Increased for batch processing
                temperature=0.3
            )
            
            ai_response = response.choices[0].message.content
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens
            total_tokens = response.usage.total_tokens
            cost = calculate_openai_cost(model, input_tokens, output_tokens)
            
            print(f"OpenAI Batch API response: {ai_response[:200]}...")
            print(f"Cost: ${cost} (Input: {input_tokens}, Output: {output_tokens})")
            
            # Parse JSON response
            json_pattern = re.compile(r'\{[\s\S]*\}')
            json_match = json_pattern.search(ai_response)
            
            if not json_match:
                raise ValueError('No JSON found in AI response')
            
            parsed_response = json.loads(json_match.group(0))
            
            # Validate response structure
            if 'measurements' not in parsed_response and 'complianceChecks' not in parsed_response:
                raise ValueError('Invalid response format - missing measurements or complianceChecks')
            
            # Cache the new results
            if ENABLE_CACHING:
                for m in parsed_response.get('measurements', []):
                    cache_key = f"batch:measurement:{m['measurementName']}"
                    cache.set(cache_key, m)
                    print(f"Cached measurement: {m['measurementName']}")
                
                for c in parsed_response.get('complianceChecks', []):
                    cache_key = f"batch:compliance:{c['ComplianceCheckName']}"
                    cache.set(cache_key, c)
                    print(f"Cached compliance check: {c['ComplianceCheckName']}")
            
            # Merge cached and new results
            all_measurements = {}
            all_checks = {}
            
            # Add cached measurements
            for name, data in cached_measurements.items():
                all_measurements[name] = data
            
            # Add new measurements from API
            for m in parsed_response.get('measurements', []):
                all_measurements[m['measurementName']] = m
            
            # Add cached checks
            for name, data in cached_checks.items():
                all_checks[name] = data
            
            # Add new checks from API
            for c in parsed_response.get('complianceChecks', []):
                all_checks[c['ComplianceCheckName']] = c
            
            # Build final result in original order
            final_measurements = []
            for m in measurements_list:
                if m['measurementName'] in all_measurements:
                    final_measurements.append(all_measurements[m['measurementName']])
            
            final_checks = []
            for c in compliance_checks_list:
                if c['ComplianceCheckName'] in all_checks:
                    final_checks.append(all_checks[c['ComplianceCheckName']])
            
            result = {
                'measurements': final_measurements,
                'complianceChecks': final_checks,
                'tokens_used': total_tokens,
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'cost_usd': cost
            }
            
            return result
        else:
            # All cached (shouldn't reach here, but just in case)
            result = {
                'measurements': [cached_measurements[name] for name in [m['measurementName'] for m in measurements_list]],
                'complianceChecks': [cached_checks[name] for name in [c['ComplianceCheckName'] for c in compliance_checks_list]],
                'tokens_used': 0,
                'input_tokens': 0,
                'output_tokens': 0,
                'cost_usd': 0
            }
            return result
        
    except Exception as e:
        print(f"Error in analyze_batch_with_ai: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return None

@app.route('/api/action_item/batch', methods=['POST'])
def analyze_batch_measurements():
    """Batch endpoint for processing measurements and compliance checks with complianceCategory and complianceCategoryDescription
    
    Accepts:
    - measurements: Dict with numeric measurements (Head, Hinge, Closing, Threshold, DoorThickness, FrameDepth, DoorSize, FullDoorsetSize, NoOfHinges)
    - complianceChecks: Array of compliance check objects with ComplianceCheckName and NonCompliantCount
    - api_key: OpenAI API key (required)
    - model: OpenAI model name (optional, defaults to DEFAULT_OPENAI_MODEL)
    
    Returns:
    - measurements: Array of processed measurements with complianceCategory and complianceCategoryDescription
    - complianceChecks: Array of processed compliance checks with complianceCategory and complianceCategoryDescription
    """
    try:
        data = request.get_json() or {}
        
        if not data:
            return jsonify({'error': 'JSON data required'}), 400
        
        # Accept measurements - can be at top level or nested under 'measurements'
        if 'measurements' in data:
            measurements = data.get('measurements', {})
        else:
            # Check if top-level keys match measurement names
            measurement_keys = ['Head', 'Hinge', 'Closing', 'Threshold', 'DoorThickness', 'FrameDepth', 'DoorSize', 'FullDoorsetSize', 'NoOfHinges']
            measurements = {k: v for k, v in data.items() if k in measurement_keys and k != 'complianceChecks'}
        
        # Accept complianceChecks - can be nested under 'complianceChecks' or at top level as array
        compliance_checks = data.get('complianceChecks', [])
        if not compliance_checks:
            # If no complianceChecks key, check if data itself is an array (for backward compatibility)
            if isinstance(data, list):
                compliance_checks = data
        
        if not measurements and not compliance_checks:
            return jsonify({'error': 'Either measurements or complianceChecks must be provided'}), 400
        
        # Extract API key and model
        api_key_param = data.get('api_key')
        model = data.get('model') or DEFAULT_OPENAI_MODEL
        
        # Validate API key is provided
        if not api_key_param:
            return jsonify({'error': 'api_key is required'}), 400
        
        # Resolve API key
        real_key = resolve_api_key(api_key_param, 'openai')
        if not real_key:
            return jsonify({'error': 'Invalid OpenAI API key'}), 400
        
        # Prepare measurements list for AI (only non-compliant)
        measurement_mapping = {
            'Head': ('head', 4, 'max_allowed'),
            'Hinge': ('hinge', 4, 'max_allowed'),
            'Closing': ('closing', 4, 'max_allowed'),
            'Threshold': ('threshold', 4, 'max_allowed'),
            'DoorThickness': ('door_thickness', 44, 'min_required'),
            'FrameDepth': ('frame_depth', 100, 'min_required'),
            'DoorSize': ('door_size', 500, 'min_required'),
            'FullDoorsetSize': ('full_doorset_size', 500, 'min_required'),
            'NoOfHinges': ('no_of_hinges', 3, 'min_required')
        }
        
        measurements_list = []
        for measurement_name, value in measurements.items():
            if value is None or value == 0:
                continue  # Skip zero or null values
                
            if measurement_name not in measurement_mapping:
                continue  # Skip unknown measurements
            
            measurement_type, threshold, threshold_type = measurement_mapping[measurement_name]
            
            # Determine compliance
            if threshold_type == 'max_allowed':
                is_compliant = value <= threshold
            else:  # min_required
                is_compliant = value >= threshold
            
            # Only process non-compliant measurements
            if not is_compliant:
                measurements_list.append({
                    'measurementName': measurement_name,
                    'value': value,
                    'threshold': threshold,
                    'thresholdType': threshold_type
                })
        
        # Prepare compliance checks list for AI (only non-compliant)
        compliance_checks_list = []
        for check in compliance_checks:
            compliance_check_name = check.get('ComplianceCheckName', '')
            non_compliant_count = check.get('NonCompliantCount', 0)
            
            if not compliance_check_name or non_compliant_count == 0:
                continue  # Skip if no name or no non-compliant items
            
            compliance_checks_list.append({
                'ComplianceCheckName': compliance_check_name,
                'NonCompliantCount': non_compliant_count
            })
        
        # If no items to process, return empty results
        if not measurements_list and not compliance_checks_list:
            return jsonify({
                'success': True,
                'timestamp': datetime.now().isoformat(),
                'measurements': [],
                'complianceChecks': []
            })
        
        # Call OpenAI API for batch analysis
        ai_result = analyze_batch_with_ai(measurements_list, compliance_checks_list, real_key, model)
        
        if not ai_result:
            return jsonify({'error': 'Failed to analyze with OpenAI API'}), 500
        
        # Merge AI results with original data
        # Create lookup maps for AI results
        ai_measurements_map = {m['measurementName']: m for m in ai_result.get('measurements', [])}
        ai_checks_map = {c['ComplianceCheckName']: c for c in ai_result.get('complianceChecks', [])}
        
        # Build final results
        final_measurements = []
        for m in measurements_list:
            ai_data = ai_measurements_map.get(m['measurementName'], {})
            final_measurements.append({
                'measurementName': m['measurementName'],
                'value': m['value'],
                'complianceCategory': ai_data.get('complianceCategory', 'BS 8214'),
                'complianceCategoryDescription': ai_data.get('complianceCategoryDescription', 'UK fire door compliance standard.')
            })
        
        final_compliance_checks = []
        for c in compliance_checks_list:
            ai_data = ai_checks_map.get(c['ComplianceCheckName'], {})
            final_compliance_checks.append({
                'ComplianceCheckName': c['ComplianceCheckName'],
                'NonCompliantCount': c['NonCompliantCount'],
                'complianceCategory': ai_data.get('complianceCategory', 'BS 8214'),
                'complianceCategoryDescription': ai_data.get('complianceCategoryDescription', 'UK fire door compliance standard.')
            })
        
        results = {
            'success': True,
            'timestamp': datetime.now().isoformat(),
            'measurements': final_measurements,
            'complianceChecks': final_compliance_checks,
            'ai_analysis': {
                'model': model,
                'tokens_used': ai_result.get('tokens_used', 0),
                'input_tokens': ai_result.get('input_tokens', 0),
                'output_tokens': ai_result.get('output_tokens', 0),
                'cost_usd': ai_result.get('cost_usd', 0)
            }
        }
        
        return jsonify(results)
        
    except Exception as e:
        print(f"Error in analyze_batch_measurements: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return jsonify({'error': f'Batch analysis failed: {str(e)}'}), 500

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
                    {'option': 'Option 1: Quick Fix', 'plan': f'Basic solution for {gap_type.replace("_", " ")}.'},
                    {'option': 'Option 2: Standard Solution', 'plan': f'Quality solution for {gap_type.replace("_", " ")}.'},
                    {'option': 'Option 3: Comprehensive Fix', 'plan': f'Premium solution with professional testing.'},
                ],
                'confidenceScore': 98 if threshold_type == 'max_allowed' else 85,
                'complianceCategory': get_compliance_category(gap_type, description),
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
                        {'option': 'Option 1: Quick Fix', 'plan': f'Install basic {measurement_type.replace("_", " ")} immediately.'},
                        {'option': 'Option 2: Standard Solution', 'plan': f'Install quality {measurement_type.replace("_", " ")} with proper setup.'},
                        {'option': 'Option 3: Comprehensive Fix', 'plan': f'Complete {measurement_type.replace("_", " ")} installation with testing.'},
                    ],
                    'confidenceScore': 98 if default_severity == 'critical' else (95 if default_severity == 'high' else 85),
                    'complianceCategory': get_compliance_category(measurement_type, description),
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

def optimize_image(image_data: bytes) -> bytes:
    """
    Optimize image by resizing and compressing.
    Returns optimized image as JPEG bytes.
    """
    try:
        start_time = time.time()
        
        # Open image
        image = Image.open(io.BytesIO(image_data))
        original_size = len(image_data)
        
        # Convert RGBA to RGB if necessary (removes alpha channel, reduces size)
        if image.mode in ('RGBA', 'LA', 'P'):
            # Create white background
            rgb_image = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            rgb_image.paste(image, mask=image.split()[-1] if image.mode in ('RGBA', 'LA') else None)
            image = rgb_image
        elif image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Resize if image is too large
        width, height = image.size
        if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
            # Calculate new dimensions maintaining aspect ratio
            if width > height:
                new_width = MAX_IMAGE_DIMENSION
                new_height = int(height * (MAX_IMAGE_DIMENSION / width))
            else:
                new_height = MAX_IMAGE_DIMENSION
                new_width = int(width * (MAX_IMAGE_DIMENSION / height))
            
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            print(f"  Resized image: {width}x{height} -> {new_width}x{new_height}")
        
        # Save as optimized JPEG
        output = io.BytesIO()
        image.save(output, format='JPEG', quality=JPEG_QUALITY, optimize=True)
        optimized_data = output.getvalue()
        optimized_size = len(optimized_data)
        
        optimization_time = time.time() - start_time
        reduction = ((original_size - optimized_size) / original_size) * 100
        
        print(f"  Image optimization: {original_size/1024:.1f}KB -> {optimized_size/1024:.1f}KB ({reduction:.1f}% reduction) in {optimization_time:.2f}s")
        
        return optimized_data
        
    except Exception as e:
        print(f"  Warning: Image optimization failed: {e}. Using original image.")
        return image_data

def analyze_image_compliance(image_data: bytes, api_key: str, model: str = 'gpt-4o'):
    """
    Analyze door image for compliance using OpenAI Vision API.
    Optimized for performance with image compression and optimizations.
    """
    try:
        total_start_time = time.time()
        
        # Optimize image
        print("  Optimizing image...")
        optimize_start = time.time()
        optimized_image = optimize_image(image_data)
        optimize_time = time.time() - optimize_start
        
        # Encode to base64
        encode_start = time.time()
        image_base64 = base64.b64encode(optimized_image).decode('utf-8')
        encode_time = time.time() - encode_start
        print(f"  Base64 encoding: {len(image_base64)/1024:.1f}KB in {encode_time:.3f}s")
        
        # Optimized vision prompt - shorter and more focused
        OPTIMIZED_VISION_PROMPT = """UK fire safety inspector. Analyze fire door image for compliance.

Return JSON with exactly 9 categories. Do NOT include Gap Measurements or Frame Integrity. For each category, set compliance_status: true if compliant, false if non-compliant or missing.

Categories to analyze:
1. Keep Shut Sign - Visible, legible signage
2. Self-Closing Device - Present and functional
3. Intumescent Strips - Visible, continuous, properly installed
4. Hold Open Device - Present and compliant (if visible)
5. Certification Visible - Label/plate visible and legible
6. Contains Glazing - Mark true only if glazing is visible, sealed, intact; else false
7. Pyro Glazing - Fire-rated if glazing present
8. Hinge Condition - Mark true only if 3 hinges are clearly visible, secure, undamaged; else false
9. Door Damage Check - Inspect for visible physical damage only

DO NOT include: Gap Measurements, Frame Integrity

Return format:
{
  "compliance_status": true | false,
  "door_damaged": true | false,
  "issues_found": [
    {
      "category": "Category Name",
      "compliance_status": true | false,
      "details": "Brief observation"
    }
  ],
  "overall_comments": "Summary"
}

Only report visible evidence. Do not speculate."""
        
        # Rate limiting check
        if not rate_limiter.can_make_call():
            raise Exception('Rate limit exceeded')
        
        # Call OpenAI Vision API
        api_start = time.time()
        client = openai.OpenAI(api_key=api_key, timeout=60.0)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": OPTIMIZED_VISION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=500,  # Reduced for faster response
            temperature=0.1  # Lower temperature for faster, more deterministic responses
        )
        api_time = time.time() - api_start
        
        ai_response = response.choices[0].message.content
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens
        total_tokens = response.usage.total_tokens
        cost = calculate_openai_cost(model, input_tokens, output_tokens)
        
        print(f"  OpenAI API call: {api_time:.2f}s (Input: {input_tokens}, Output: {output_tokens}, Cost: ${cost:.4f})")
        
        # Parse JSON response
        parse_start = time.time()
        json_pattern = re.compile(r'\{[\s\S]*\}')
        json_match = json_pattern.search(ai_response)
        
        if not json_match:
            raise ValueError('No JSON found in AI response')
        
        parsed_response = json.loads(json_match.group(0))
        parse_time = time.time() - parse_start
        
        # Process response
        process_start = time.time()
        if 'issues_found' in parsed_response:
            compliance_status = parsed_response.get('compliance_status', False)
            door_damaged = parsed_response.get('door_damaged', False)
            issues_found = parsed_response.get('issues_found', [])
            
            # Map category names to component keys
            category_mapping = {
                'Keep Shut Sign': 'keep_shut_sign',
                'Self-Closing Device': 'self_closing_device',
                'Intumescent Strips': 'intumescent_strips',
                'Hold Open Device': 'hold_open_device',
                'Certification Visible': 'certification_visible',
                'Contains Glazing': 'contains_glazing',
                'Pyro Glazing': 'pyro_glazing',
                # 'Gaps': 'gap_measurements',  # COMMENTED OUT
                'Hinges': 'hinge_condition',
                # 'Frame': 'frame_integrity',  # COMMENTED OUT
                'Door Damage Check': 'door_damage_check'
            }
            
            # Categories to skip (commented out)
            skip_categories = ['Gaps', 'Gap Measurements', 'Frame', 'Frame Integrity']
            
            component_breakdown = {}
            for issue in issues_found:
                category_name = issue.get('category', '')
                
                # Skip commented out categories
                if category_name in skip_categories:
                    continue
                
                component_key = category_mapping.get(category_name, category_name.lower().replace(' ', '_'))
                component_breakdown[component_key] = {
                    'compliant': issue.get('compliance_status', False)
                }
            
            result = {
                'success': True,
                'compliance_status': compliance_status,
                'door_damaged': door_damaged,
                'components': component_breakdown,
                'timestamp': datetime.now().isoformat(),
                'ai_model': model,
                'tokens_used': total_tokens,
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'cost_usd': round(cost, 6),
                'performance': {
                    'total_time': round(time.time() - total_start_time, 2),
                    'image_optimization': round(optimize_time, 2),
                    'base64_encoding': round(encode_time, 3),
                    'api_call': round(api_time, 2),
                    'parsing': round(parse_time, 3),
                    'processing': round(time.time() - process_start, 3)
                }
            }
        else:
            raise ValueError('Invalid response format from AI - missing issues_found')
        
        total_time = time.time() - total_start_time
        print(f"  Total analysis time: {total_time:.2f}s")
        
        return result
        
    except Exception as e:
        print(f"Error in analyze_image_compliance: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return None

def download_image_from_url(url: str, max_size: int = MAX_IMAGE_SIZE_MB * 1024 * 1024, timeout: int = 15) -> bytes:
    """
    Download image from URL with optimized settings.
    Uses connection pooling for better performance.
    """
    try:
        start_time = time.time()
        
        # Validate URL
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError('Invalid URL format')
        
        if parsed.scheme not in ['http', 'https']:
            raise ValueError(f'Unsupported URL scheme: {parsed.scheme}')
        
        # Download with connection pooling
        response = session.get(url, timeout=timeout, stream=True)
        response.raise_for_status()
        
        # Check content type
        content_type = response.headers.get('content-type', '').lower()
        if not content_type.startswith('image/'):
            raise ValueError(f'URL does not point to an image. Content-Type: {content_type}')
        
        # Stream download with size limit
        image_data = b''
        for chunk in response.iter_content(chunk_size=8192):
            image_data += chunk
            if len(image_data) > max_size:
                raise ValueError(f'Image too large. Maximum size is {max_size / 1024 / 1024}MB')
        
        if len(image_data) == 0:
            raise ValueError('Downloaded image is empty')
        
        download_time = time.time() - start_time
        print(f"  Downloaded image: {len(image_data)/1024:.1f}KB in {download_time:.2f}s")
        
        return image_data
        
    except requests.exceptions.RequestException as e:
        raise ValueError(f'Failed to download image from URL: {str(e)}')
    except Exception as e:
        raise ValueError(f'Error downloading image: {str(e)}')

@app.route('/api/compliance_check/analyze', methods=['POST'])
def analyze_compliance_image():
    """Analyze door image for compliance check using OpenAI Vision API
    
    Supports four input formats:
    1. JSON with image_path: Local file path (priority)
    2. JSON with image_url: Download image from URL
    3. JSON with image_base64: Base64-encoded image
    4. Multipart form-data: Direct file upload with 'image' key
    
    Optimized for performance with image compression and optimizations.
    """
    try:
        request_start_time = time.time()
        image_data = None
        api_key_param = None
        model = None
        
        # Check if request is JSON or multipart (file upload)
        if request.is_json:
            # JSON request
            data = request.get_json() or {}
            api_key_param = data.get('api_key')
            model = data.get('model') or DEFAULT_OPENAI_MODEL
            
            # Priority order: image_path → image_base64 → image_url
            image_path = data.get('image_path')
            image_url = data.get('image_url') or data.get('imageUrl')
            image_base64_str = data.get('image_base64') or data.get('imageBase64')
            
            if image_path:
                # Read image from local file path
                try:
                    print(f"  Reading image from local path: {image_path}")
                    if not os.path.exists(image_path):
                        return jsonify({'error': f'Image file not found at path: {image_path}'}), 400
                    
                    with open(image_path, 'rb') as f:
                        image_data = f.read()
                    print(f"  Read image from path: {len(image_data)/1024:.1f}KB")
                except Exception as e:
                    return jsonify({'error': f'Failed to read image from path: {str(e)}'}), 400
            
            elif image_base64_str:
                # Decode base64 image
                try:
                    print(f"  Using base64 image data")
                    # Remove data URL prefix if present (e.g., "data:image/jpeg;base64,")
                    if ',' in image_base64_str:
                        image_base64_str = image_base64_str.split(',')[1]
                    
                    image_data = base64.b64decode(image_base64_str)
                    print(f"  Decoded base64 image: {len(image_data)/1024:.1f}KB")
                except Exception as e:
                    return jsonify({'error': f'Invalid base64 image data: {str(e)}'}), 400
            
            elif image_url:
                # Download image from URL
                try:
                    print(f"  Downloading image from URL: {image_url}")
                    image_data = download_image_from_url(image_url)
                    print(f"  Successfully downloaded image: {len(image_data)} bytes")
                except Exception as e:
                    return jsonify({'error': f'Failed to download image from URL: {str(e)}'}), 400
            else:
                return jsonify({
                    'error': 'No image provided. Use one of: "image_path" (local file path), "image_url" (URL to image), "image_base64" (base64 string), or multipart/form-data with "image" file.'
                }), 400
        else:
            # Multipart form-data request with file upload
            if 'image' not in request.files:
                return jsonify({
                    'error': 'No image file provided. Please upload an image file with key "image", or use JSON with "image_path", "image_url", or "image_base64" field.'
                }), 400
            
            image_file = request.files['image']
            
            # Validate file
            if image_file.filename == '':
                return jsonify({'error': 'No file selected'}), 400
            
            # Get optional parameters from form data
            api_key_param = request.form.get('api_key') or request.args.get('api_key')
            model = request.form.get('model') or request.args.get('model') or DEFAULT_OPENAI_MODEL
            
            # Read image data
            image_data = image_file.read()
        
        # Validate image data
        if not image_data or len(image_data) == 0:
            return jsonify({'error': 'Image data is empty'}), 400
        
        # Validate image size (max 20MB for OpenAI)
        max_size = MAX_IMAGE_SIZE_MB * 1024 * 1024
        if len(image_data) > max_size:
            return jsonify({'error': f'Image file too large. Maximum size is {MAX_IMAGE_SIZE_MB}MB, got {len(image_data) / 1024 / 1024:.2f}MB'}), 400
        
        # Use default API key from environment if not provided
        if not api_key_param:
            # Try to use default 'openai_key' from API_KEY_MAPPING
            api_key_param = 'openai_key'
            print("  No API key provided, using default 'openai_key' from environment")
        
        # Resolve API key
        real_key = resolve_api_key(api_key_param, 'openai')
        if not real_key:
            return jsonify({'error': 'Invalid OpenAI API key. Please provide a valid api_key parameter or set OPENAI_API_KEY in environment variables.'}), 400
        
        # Validate model (must be vision-capable)
        if model not in ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo']:
            # Default to gpt-4o if model doesn't support vision
            model = 'gpt-4o'
            print(f"Warning: Model may not support vision, defaulting to gpt-4o")
        
        print(f"\n{'='*60}")
        print(f"Starting image compliance analysis")
        print(f"  Model: {model}")
        print(f"{'='*60}")
        
        # Analyze image
        result = analyze_image_compliance(image_data, real_key, model)
        
        if not result:
            return jsonify({'error': 'Failed to analyze image. Please check image format and try again.'}), 500
        
        # Add download/read time to performance metrics if available
        if 'performance' in result:
            download_time = time.time() - request_start_time - result['performance'].get('total_time', 0)
            result['performance']['download'] = round(download_time, 2)
            result['performance']['request_total'] = round(time.time() - request_start_time, 2)
        
        print(f"\n{'='*60}")
        print(f"Analysis complete in {result.get('performance', {}).get('request_total', 0):.2f}s")
        print(f"{'='*60}\n")
        
        return jsonify(result)
        
    except Exception as e:
        print(f"Error in analyze_compliance_image: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return jsonify({'error': f'Compliance check failed: {str(e)}'}), 500

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
