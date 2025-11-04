#!/usr/bin/env python3
"""
Azure-Optimized Flask Fire Door Compliance API with Cache Warming
Fixes for Azure App Service deployment issues
"""

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
import requests

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
CORS(app)

# Azure Detection
def is_azure_app_service():
    """Detect if running in Azure App Service"""
    return os.getenv('WEBSITE_SITE_NAME') is not None

# Cache Configuration with Azure fallbacks
CACHE_TTL = int(os.getenv('CACHE_TTL_HOURS', 24)) * 60 * 60  # 24 hours in seconds
MAX_CACHE_SIZE = int(os.getenv('MAX_CACHE_SIZE', 1000))
CACHE_CLEANUP_INTERVAL = int(os.getenv('CACHE_CLEANUP_INTERVAL', 3600))  # 1 hour
ENABLE_CACHING = os.getenv('ENABLE_CACHING', 'true').lower() == 'true'
AUTO_WARM_CACHE = os.getenv('AUTO_WARM_CACHE', 'true').lower() == 'true'

# Azure-specific settings
AZURE_WARMUP_TIMEOUT = int(os.getenv('AZURE_WARMUP_TIMEOUT', 300))  # 5 minutes
AZURE_STARTUP_DELAY = int(os.getenv('AZURE_STARTUP_DELAY', 1))  # 1 second for Azure

print(f"🌍 Environment: {'Azure App Service' if is_azure_app_service() else 'Local'}")
print(f"💾 Cache enabled: {ENABLE_CACHING}, TTL: {CACHE_TTL/3600} hours, Max size: {MAX_CACHE_SIZE}")
print(f"🔥 Auto warm cache: {AUTO_WARM_CACHE}")
if is_azure_app_service():
    print(f"⏱️ Azure warmup timeout: {AZURE_WARMUP_TIMEOUT}s, startup delay: {AZURE_STARTUP_DELAY}s")

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
        
        # Use non-daemon thread for Azure compatibility
        cleanup_thread = threading.Thread(target=cleanup_loop, daemon=False)
        cleanup_thread.start()
    
    def _cleanup_expired(self):
        """Remove expired entries"""
        with self.lock:
            current_time = time.time()
            expired_keys = []
            
            for key, (value, timestamp) in self.cache.items():
                if current_time - timestamp > self.ttl:
                    expired_keys.append(key)
            
            for key in expired_keys:
                del self.cache[key]
                self.stats['evictions'] += 1
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        with self.lock:
            self.stats['total_requests'] += 1
            
            if key in self.cache:
                value, timestamp = self.cache[key]
                current_time = time.time()
                
                if current_time - timestamp <= self.ttl:
                    # Move to end (most recently used)
                    self.cache.move_to_end(key)
                    self.stats['hits'] += 1
                    return value
                else:
                    # Expired, remove it
                    del self.cache[key]
                    self.stats['evictions'] += 1
            
            self.stats['misses'] += 1
            return None
    
    def set(self, key: str, value: Any) -> None:
        """Set value in cache"""
        with self.lock:
            current_time = time.time()
            
            # Remove oldest entries if at capacity
            while len(self.cache) >= self.max_size:
                self.cache.popitem(last=False)
                self.stats['evictions'] += 1
            
            self.cache[key] = (value, current_time)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self.lock:
            hit_rate = (self.stats['hits'] / self.stats['total_requests'] * 100) if self.stats['total_requests'] > 0 else 0
            return {
                'hits': self.stats['hits'],
                'misses': self.stats['misses'],
                'evictions': self.stats['evictions'],
                'total_requests': self.stats['total_requests'],
                'hit_rate': hit_rate,
                'current_size': len(self.cache),
                'max_size': self.max_size,
                'ttl_hours': self.ttl / 3600
            }

# Initialize cache
cache = OptimizedCache(MAX_CACHE_SIZE, CACHE_TTL)

# Rate Limiter
class RateLimiter:
    def __init__(self, max_calls: int = 10, time_window: int = 60):
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = []
        self.lock = threading.Lock()
    
    def can_make_call(self) -> bool:
        with self.lock:
            current_time = time.time()
            # Remove calls outside the time window
            self.calls = [call_time for call_time in self.calls if current_time - call_time < self.time_window]
            
            if len(self.calls) < self.max_calls:
                self.calls.append(current_time)
                return True
            return False
    
    def get_remaining_calls(self) -> int:
        with self.lock:
            return max(0, self.max_calls - len(self.calls))
    
    def get_reset_time(self) -> int:
        with self.lock:
            if not self.calls:
                return 0
            return int(self.time_window - (time.time() - self.calls[0]))

rate_limiter = RateLimiter()

# API Key Management
API_KEY_MAPPING = {
    'openai_key': os.getenv('OPENAI_API_KEY'),
    'claude_key': os.getenv('CLAUDE_API_KEY'),
    'sk-proj-': os.getenv('OPENAI_API_KEY'),  # Support for OpenAI key format
    'sk-': os.getenv('OPENAI_API_KEY'),  # Support for OpenAI key format
}

# Model Configuration
DEFAULT_OPENAI_MODEL = os.getenv('DEFAULT_OPENAI_MODEL', 'gpt-3.5-turbo')
DEFAULT_CLAUDE_MODEL = os.getenv('DEFAULT_CLAUDE_MODEL', 'claude-3-haiku-20240307')

def resolve_api_key(api_key: str, provider: str) -> Optional[str]:
    """Resolve API key from mapping"""
    if not api_key:
        return None
    
    # Direct key lookup
    if api_key in API_KEY_MAPPING:
        return API_KEY_MAPPING[api_key]
    
    # OpenAI key format detection
    if api_key.startswith('sk-proj-') or api_key.startswith('sk-'):
        return API_KEY_MAPPING.get('sk-proj-') or API_KEY_MAPPING.get('sk-')
    
    # Claude key format detection
    if api_key.startswith('sk-ant-'):
        return API_KEY_MAPPING.get('claude_key')
    
    return None

# AI Prompt Functions
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
- Frame Depth: Only 100mm compliant
- Door Size: Only 500mm compliant
- Boolean measurements: Only "yes" is compliant, "no" is NON-COMPLIANT and requires action items. IMPORTANT: For boolean measurements, if the value is "no", the door is NON-COMPLIANT and you MUST provide action items.

MEASUREMENTS:
{survey_text}

SEVERITY LEVELS:
- critical: Immediate danger (today)
- high: Significant risk (30 days)
- medium: Moderate risk (90 days)
- low: Minor risk (180 days)

RESPONSE FORMAT (JSON only):
{{
  "compliant": true/false,
  "severity": "critical|high|medium|low",
  "actionItems": [
    {{
      "severity": "critical|high|medium|low",
      "dueDate": "YYYY-MM-DD",
      "actionDescription": "Specific action required"
    }}
  ]
}}

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
- Frame Depth: Only 100mm compliant
- Door Size: Only 500mm compliant
- Boolean measurements: Only "yes" is compliant, "no" is NON-COMPLIANT and requires action items. IMPORTANT: For boolean measurements, if the value is "no", the door is NON-COMPLIANT and you MUST provide action items.

MEASUREMENTS:
{survey_text}

SEVERITY LEVELS:
- critical: Immediate danger (today)
- high: Significant risk (30 days)
- medium: Moderate risk (90 days)
- low: Minor risk (180 days)

RESPONSE FORMAT (JSON only):
{{
  "compliant": true/false,
  "severity": "critical|high|medium|low",
  "actionItems": [
    {{
      "severity": "critical|high|medium|low",
      "dueDate": "YYYY-MM-DD",
      "actionDescription": "Specific action required"
    }}
  ]
}}

If compliant (all measurements meet requirements), return empty actionItems array."""

# Due Date Calculation
def get_due_date(severity: str) -> str:
    """Calculate due date based on severity"""
    today = datetime.now()
    
    if severity == 'critical':
        return today.strftime('%Y-%m-%d')
    elif severity == 'high':
        return (today + timedelta(days=30)).strftime('%Y-%m-%d')
    elif severity == 'medium':
        return (today + timedelta(days=90)).strftime('%Y-%m-%d')
    elif severity == 'low':
        return (today + timedelta(days=180)).strftime('%Y-%m-%d')
    else:
        return (today + timedelta(days=90)).strftime('%Y-%m-%d')

# AI Analysis Functions
def analyze_gap_with_ai(gap_type: str, value: float, unit: str, api_key: str, model: str, provider: str) -> Optional[Dict[str, Any]]:
    """Analyze gap measurement with AI"""
    try:
        # Check cache first
        cache_key = f"{gap_type}_{value}_{unit}_{provider}_{model}"
        if ENABLE_CACHING:
            cached_result = cache.get(cache_key)
            if cached_result:
                print(f"Cache hit for {gap_type}: {value} ({provider})")
                return cached_result
        
        # Build survey data
        if gap_type == 'head':
            survey_data = {'headGap': value}
        elif gap_type == 'hinge':
            survey_data = {'hingeGap': value}
        elif gap_type == 'closing':
            survey_data = {'closingGap': value}
        elif gap_type == 'threshold':
            survey_data = {'thresholdGap': value}
        elif gap_type == 'door_thickness':
            survey_data = {'doorThickness': value}
        elif gap_type == 'frame_depth':
            survey_data = {'frameDepth': value}
        elif gap_type == 'door_size':
            survey_data = {'doorSize': value}
        elif gap_type in ['intumescent_strips', 'self_closing_device', 'keep_shut_sign', 'hold_open_device', 'certification_visible', 'glazing', 'pyro_glazing', 'door_close_fully', 'hinges_fire_rated', 'cold_smoke_seals', 'keep_locked_sign']:
            survey_data = {gap_type: value}
        else:
            survey_data = {f'{gap_type}Gap': value}
        
        # Generate prompt
        if provider == 'openai':
            prompt = create_openai_prompt(survey_data)
        else:
            prompt = create_claude_prompt(survey_data)
        
        # Make AI API call
        if provider == 'openai':
            response = openai.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.1
            )
            ai_response = response.choices[0].message.content
            total_tokens = response.usage.total_tokens
        else:  # Claude
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=model,
                max_tokens=500,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}]
            )
            ai_response = response.content[0].text
            total_tokens = response.usage.input_tokens + response.usage.output_tokens
        
        # Parse AI response
        try:
            ai_data = json.loads(ai_response)
        except json.JSONDecodeError:
            print(f"Failed to parse AI response: {ai_response}")
            return None
        
        # Process action items
        action_items = []
        if not ai_data.get('compliant', True) and ai_data.get('actionItems'):
            for item in ai_data['actionItems']:
                severity = item.get('severity', 'medium')
                due_date = get_due_date(severity)
                
                action_items.append({
                    'severity': severity,
                    'dueDate': due_date,
                    'actionDescription': item.get('actionDescription', 'Action required')
                })
        
        # Determine compliance and severity
        compliant = ai_data.get('compliant', True)
        ai_severity = ai_data.get('severity', 'medium')
        
        # Override severity for specific measurements
        if gap_type in ['head', 'hinge', 'closing', 'threshold']:
            ai_severity = 'critical'
        elif gap_type in ['intumescent_strips', 'self_closing_device', 'door_close_fully', 'hinges_fire_rated']:
            ai_severity = 'critical'
        elif gap_type in ['glazing', 'pyro_glazing', 'cold_smoke_seals', 'keep_locked_sign']:
            ai_severity = 'medium'
        else:
            ai_severity = 'high'
        
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
            'cost': calculate_cost(total_tokens, provider, model)
        }
        
        # Add measurement-specific fields
        if gap_type == 'door_thickness':
            response_data['min_required'] = 44
        elif gap_type == 'frame_depth':
            response_data['min_required'] = 100
        elif gap_type == 'door_size':
            response_data['min_required'] = 500
        elif gap_type not in ['intumescent_strips', 'self_closing_device', 'keep_shut_sign', 'hold_open_device', 'certification_visible', 'glazing', 'pyro_glazing', 'door_close_fully', 'hinges_fire_rated']:
            response_data['max_allowed'] = 4
        
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

def calculate_cost(tokens: int, provider: str, model: str) -> float:
    """Calculate cost based on tokens and provider"""
    if provider == 'openai':
        if 'gpt-4' in model:
            return tokens * 0.00003  # $0.03 per 1K tokens
        else:
            return tokens * 0.000002  # $0.002 per 1K tokens
    else:  # Claude
        return tokens * 0.000008  # $0.008 per 1K tokens

# Azure-Optimized Cache Warming
def warm_cache_automatically():
    """Automatically warm cache with common parameter combinations - Azure optimized"""
    if not AUTO_WARM_CACHE:
        print("Auto cache warming disabled")
        return
    
    print("🔥 Starting Azure-optimized automatic cache warming...")
    
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
    start_time = time.time()
    
    for i, combo in enumerate(common_combinations):
        try:
            # Azure timeout check
            if is_azure_app_service() and (time.time() - start_time) > AZURE_WARMUP_TIMEOUT:
                print(f"⏱️ Azure warmup timeout reached ({AZURE_WARMUP_TIMEOUT}s), stopping...")
                break
            
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
    
    elapsed_time = time.time() - start_time
    print(f"\n📊 Azure-Optimized Cache Warming Results:")
    print(f"  ✅ Successful: {successful_warms}")
    print(f"  ❌ Failed: {failed_warms}")
    print(f"  ⏱️ Elapsed time: {elapsed_time:.1f}s")
    print(f"  🎯 Success rate: {(successful_warms/(successful_warms+failed_warms)*100):.1f}%")
    print("🔥 Azure cache warming complete!")

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
                action_items = []
        else:
            if not is_compliant:
                category = gap_type.replace('_', ' ').title() + ' Compliance'
                description = f'{gap_type.replace("_", " ").title()} exceeds maximum allowed {threshold}mm. This is critical for fire door compliance.'
                
                action_items = [{
                    'severity': 'critical',
                    'dueDate': get_due_date('critical'),
                    'actionDescription': description
                }]
            else:
                action_items = []
        
        return {
            'success': True,
            'measurement_type': f'{gap_type}_gap',
            'value': value,
            'unit': unit,
            'compliant': is_compliant,
            'severity': 'critical' if not is_compliant else 'none',
            'actionItems': action_items,
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'static',
            'max_allowed': threshold if threshold_type == 'max_allowed' else None,
            'min_required': threshold if threshold_type == 'min_required' else None
        }
        
    except Exception as e:
        print(f"Error in handle_numeric_measurement_internal: {e}")
        return None

def handle_boolean_measurement_internal(measurement_type, value, api_key, model, ai_provider, severity):
    """Handle boolean measurements internally for cache warming"""
    try:
        is_compliant = str(value).lower() == 'yes'
        
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
                category = measurement_type.replace('_', ' ').title() + ' Compliance'
                description = f'{measurement_type.replace("_", " ").title()} is missing. This is critical for fire door compliance.'
                
                action_items = [{
                    'severity': severity,
                    'dueDate': get_due_date(severity),
                    'actionDescription': description
                }]
            else:
                action_items = []
        
        return {
            'success': True,
            'measurement_type': measurement_type,
            'value': value,
            'unit': None,
            'compliant': is_compliant,
            'severity': severity if not is_compliant else 'none',
            'actionItems': action_items,
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'static'
        }
        
    except Exception as e:
        print(f"Error in handle_boolean_measurement_internal: {e}")
        return None

# Azure-Optimized Startup Function
def start_cache_warming():
    """Start cache warming with Azure-specific optimizations"""
    if AUTO_WARM_CACHE:
        print("🔥 Starting Azure-optimized automatic cache warming...")
        
        def warm_in_background():
            # Azure-specific delay (shorter than local)
            delay = AZURE_STARTUP_DELAY if is_azure_app_service() else 3
            time.sleep(delay)
            
            try:
                warm_cache_automatically()
            except Exception as e:
                print(f"❌ Cache warming failed: {e}")
                import traceback
                print(f"Traceback: {traceback.format_exc()}")
        
        # Use non-daemon thread for Azure compatibility
        warm_thread = threading.Thread(target=warm_in_background, daemon=False)
        warm_thread.start()
        
        print(f"🔥 Cache warming thread started (Azure-optimized)")
    else:
        print("Cache warming disabled")

# API Endpoints
@app.route('/api/action_item/analyze', methods=['POST'])
def analyze_action_item():
    """Unified endpoint for all measurement analysis"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
        
        measurement_type = data.get('measurement_type')
        value = data.get('value')
        unit = data.get('unit', 'mm')
        api_key = data.get('api_key')
        ai_provider = data.get('ai_provider', 'claude')
        
        if not measurement_type or value is None:
            return jsonify({'error': 'measurement_type and value are required'}), 400
        
        # Set default model
        model = DEFAULT_OPENAI_MODEL if ai_provider == 'openai' else DEFAULT_CLAUDE_MODEL
        
        # Handle numeric measurements
        if measurement_type in ['head', 'hinge', 'closing', 'threshold', 'doorthick', 'framedepth', 'doorsize']:
            try:
                value = float(value)
            except (ValueError, TypeError):
                return jsonify({'error': 'Invalid numeric value'}), 400
            
            # Map measurement types
            gap_type_map = {
                'head': 'head',
                'hinge': 'hinge', 
                'closing': 'closing',
                'threshold': 'threshold',
                'doorthick': 'door_thickness',
                'framedepth': 'frame_depth',
                'doorsize': 'door_size'
            }
            
            gap_type = gap_type_map[measurement_type]
            
            # Determine threshold and type
            if gap_type in ['head', 'hinge', 'closing', 'threshold']:
                threshold, threshold_type = 4, 'max_allowed'
            elif gap_type == 'door_thickness':
                threshold, threshold_type = 44, 'min_required'
            elif gap_type == 'frame_depth':
                threshold, threshold_type = 100, 'min_required'
            elif gap_type == 'door_size':
                threshold, threshold_type = 500, 'min_required'
            
            return handle_numeric_measurement_unified(gap_type, value, unit, api_key, model, ai_provider, threshold, threshold_type)
        
        # Handle boolean measurements
        elif measurement_type in ['intustrips', 'selfclosing', 'shutsign', 'holddevice', 'certivisible', 'glazing', 'pyroglazing', 'doorclosefully', 'hingesfirerated', 'coldsmokeseals', 'keepLockedSign']:
            if str(value).lower() not in ['yes', 'no']:
                return jsonify({'error': 'Boolean values must be "yes" or "no"'}), 400
            
            # Map to internal handlers
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
        
        else:
            return jsonify({'error': f'Unknown measurement type: {measurement_type}'}), 400
            
    except Exception as e:
        print(f"Error in analyze_action_item: {e}")
        return jsonify({'error': 'Internal server error'}), 500

def handle_numeric_measurement_unified(gap_type, value, unit, api_key, model, ai_provider, threshold, threshold_type):
    """Handle numeric measurements in unified endpoint"""
    try:
        if threshold_type == 'max_allowed':
            is_compliant = value <= threshold
        else:  # min_required
            if value < threshold:
                return jsonify({'error': f'Value {value} is below minimum required {threshold}'}), 400
            is_compliant = value == threshold  # Only exactly the threshold is compliant
        
        if api_key and not is_compliant:
            if not rate_limiter.can_make_call():
                return jsonify({'error': 'Rate limit exceeded', 'remaining_calls': rate_limiter.get_remaining_calls(), 'reset_in_seconds': rate_limiter.get_reset_time()}), 429
            
            real_key = resolve_api_key(api_key, ai_provider)
            if real_key:
                ai = analyze_gap_with_ai(gap_type, value, unit, real_key, model, ai_provider)
                if ai:
                    return jsonify(ai)
                action_items = []
        else:
            if not is_compliant:
                category = gap_type.replace('_', ' ').title() + ' Compliance'
                description = f'{gap_type.replace("_", " ").title()} exceeds maximum allowed {threshold}mm. This is critical for fire door compliance.'
                
                action_items = [{
                    'severity': 'critical',
                    'dueDate': get_due_date('critical'),
                    'actionDescription': description
                }]
            else:
                action_items = []
        
        return jsonify({
            'success': True,
            'measurement_type': f'{gap_type}_gap',
            'value': value,
            'unit': unit,
            'compliant': is_compliant,
            'severity': 'critical' if not is_compliant else 'none',
            'actionItems': action_items,
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'static',
            'max_allowed': threshold if threshold_type == 'max_allowed' else None,
            'min_required': threshold if threshold_type == 'min_required' else None
        })
        
    except Exception as e:
        print(f"Error in handle_numeric_measurement_unified: {e}")
        return jsonify({'error': 'Internal server error'}), 500

def handle_boolean_measurement_unified(measurement_type, value, api_key, model, ai_provider, severity, original_measurement_type):
    """Handle boolean measurements in unified endpoint"""
    try:
        is_compliant = str(value).lower() == 'yes'
        
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
                category = measurement_type.replace('_', ' ').title() + ' Compliance'
                description = f'{measurement_type.replace("_", " ").title()} is missing. This is critical for fire door compliance.'
                
                action_items = [{
                    'severity': severity,
                    'dueDate': get_due_date(severity),
                    'actionDescription': description
                }]
            else:
                action_items = []
        
        return jsonify({
            'success': True,
            'measurement_type': original_measurement_type,
            'value': value,
            'unit': None,
            'compliant': is_compliant,
            'severity': severity if not is_compliant else 'none',
            'actionItems': action_items,
            'timestamp': datetime.now().isoformat(),
            'analysis_type': 'static'
        })
        
    except Exception as e:
        print(f"Error in handle_boolean_measurement_unified: {e}")
        return jsonify({'error': 'Internal server error'}), 500

# Azure-specific warmup endpoint
@app.route('/api/warmup', methods=['GET'])
def azure_warmup():
    """Azure App Service warmup endpoint"""
    try:
        print("🌍 Azure warmup endpoint called")
        
        # Check if cache warming is in progress
        cache_stats = cache.get_stats()
        
        return jsonify({
            'success': True,
            'message': 'Azure warmup successful',
            'environment': 'Azure App Service' if is_azure_app_service() else 'Local',
            'cache_stats': cache_stats,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        print(f"Error in azure_warmup: {e}")
        return jsonify({'error': 'Warmup failed'}), 500

@app.route('/api/cache/stats', methods=['GET'])
def get_cache_stats():
    """Get cache statistics"""
    try:
        stats = cache.get_stats()
        return jsonify({
            'success': True,
            'cache_stats': stats,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'error': 'Failed to get cache stats'}), 500

@app.route('/api/cache/clear', methods=['POST'])
def clear_cache():
    """Clear cache"""
    try:
        cache.cache.clear()
        cache.stats = {'hits': 0, 'misses': 0, 'evictions': 0, 'total_requests': 0}
        return jsonify({
            'success': True,
            'message': 'Cache cleared',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'error': 'Failed to clear cache'}), 500

@app.route('/comparison')
def serve_comparison_ui():
    """Serve the comparison UI HTML file"""
    return send_file('comparison_ui.html')

@app.route('/comparison')
def serve_comparison_ui_alt():
    """Alternative route for comparison UI"""
    return send_file('comparison_ui.html')

# Initialize cache warming on app startup
if __name__ == '__main__':
    # Start cache warming immediately for Azure compatibility
    start_cache_warming()
    
    # Get port from environment variable (Azure App Service compatibility)
    port = int(os.environ.get('PORT', 5001))
    
    print("🚀 Starting Azure-Optimized Flask Fire Door Compliance API")
    print(f"📊 Port: {port}")
    print(f"🌍 Environment: {'Azure App Service' if is_azure_app_service() else 'Local'}")
    print(f"🧠 AI Providers: OpenAI + Claude")
    print(f"💾 Caching: Enabled (24-hour TTL)")
    print(f"🔥 Auto Warm: Enabled (Azure-optimized)")
    print("-" * 50)
    
    # Run the Flask app
    app.run(
        debug=False,  # Set to False for production
        host='0.0.0.0',
        port=port,
        use_reloader=False  # Disable reloader to prevent issues with cache warming
    )
