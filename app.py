#!/usr/bin/env python3
"""
Combined Flask Fire Door Compliance API with Auto Pre-warming
Starts Flask API with caching and automatically pre-warms it
"""

import os
import time
import threading
import requests
import json
from app_fastapi_optimized import app

def prewarm_common_combinations(base_url):
    """Pre-warm cache with common parameter combinations"""
    print("🔥 Pre-warming Flask API cache with common parameter combinations...")
    
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
    ]
    
    successful_warms = 0
    failed_warms = 0
    total_time = 0
    
    for i, combo in enumerate(common_combinations):
        try:
            print(f"  Warming {i+1}/{len(common_combinations)}: {combo['measurement_type']} = {combo['value']}")
            
            start_time = time.time()
            
            response = requests.post(
                f"{base_url}/api/action_item/analyze",
                json=combo,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                end_time = time.time()
                response_time = end_time - start_time
                total_time += response_time
                
                analysis_type = result.get('analysis_type', 'unknown')
                print(f"    ✅ {response_time:.2f}s - {analysis_type} analysis")
                successful_warms += 1
            else:
                print(f"    ❌ HTTP {response.status_code}")
                failed_warms += 1
                
        except Exception as e:
            print(f"    ❌ Error: {str(e)[:50]}...")
            failed_warms += 1
    
    avg_time = total_time / successful_warms if successful_warms > 0 else 0
    
    print(f"\n📊 Pre-warming Results:")
    print(f"  ✅ Successful: {successful_warms}")
    print(f"  ❌ Failed: {failed_warms}")
    print(f"  ⏱️ Average time: {avg_time:.2f}s")
    print(f"  🎯 Success rate: {(successful_warms/(successful_warms+failed_warms)*100):.1f}%")
    
    return successful_warms, failed_warms

def test_cache_performance(base_url):
    """Test cache performance with repeated requests"""
    print("\n⚡ Testing cache performance...")
    
    # Test with a common combination
    test_data = {
        "measurement_type": "head",
        "value": 6,
        "unit": "mm",
        "api_key": "claude_key",
        "ai_provider": "claude"
    }
    
    times = []
    
    for i in range(5):
        try:
            start_time = time.time()
            
            response = requests.post(
                f"{base_url}/api/action_item/analyze",
                json=test_data,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                end_time = time.time()
                response_time = end_time - start_time
                times.append(response_time)
                
                analysis_type = result.get('analysis_type', 'unknown')
                print(f"  Request {i+1}: {response_time:.2f}s - {analysis_type}")
            else:
                print(f"  Request {i+1}: ❌ HTTP {response.status_code}")
                
        except Exception as e:
            print(f"  Request {i+1}: ❌ Error: {str(e)[:30]}...")
    
    if times:
        avg_time = sum(times) / len(times)
        min_time = min(times)
        max_time = max(times)
        
        print(f"\n📈 Cache Performance:")
        print(f"  Average: {avg_time:.2f}s")
        print(f"  Min: {min_time:.2f}s")
        print(f"  Max: {max_time:.2f}s")
        
        if avg_time < 1.0:
            print("  🎉 Excellent! Cache is working perfectly")
        elif avg_time < 2.0:
            print("  👍 Good! Cache is working well")
        else:
            print("  ⚠️ Cache performance could be better")

def get_cache_stats(base_url):
    """Get current cache statistics"""
    try:
        response = requests.get(f"{base_url}/cache/stats", timeout=5)
        if response.status_code == 200:
            stats = response.json()
            
            print(f"  Cache hits: {stats.get('hits', 0)}")
            print(f"  Cache misses: {stats.get('misses', 0)}")
            print(f"  Hit rate: {stats.get('hit_rate', 0)}%")
            print(f"  Current size: {stats.get('current_size', 0)}/{stats.get('max_size', 0)}")
            print(f"  Evictions: {stats.get('evictions', 0)}")
            
            return stats
        else:
            print(f"  ❌ Failed to get cache stats: HTTP {response.status_code}")
            return None
    except Exception as e:
        print(f"  ❌ Error getting cache stats: {e}")
        return None

def wait_for_api(base_url, max_retries=30, delay=2):
    """Wait for API to be ready"""
    print("⏳ Waiting for API to be ready...")
    
    for attempt in range(max_retries):
        try:
            response = requests.get(f"{base_url}/health", timeout=5)
            if response.status_code == 200:
                print("  ✅ API is ready!")
                return True
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"  ⏳ Attempt {attempt + 1}/{max_retries}: API not ready yet...")
                time.sleep(delay)
            else:
                print(f"  ❌ API failed to start after {max_retries} attempts")
                return False
    
    return False

def prewarm_api_async(base_url):
    """Pre-warm API in a separate thread"""
    def prewarm_worker():
        # Wait for API to be ready
        if not wait_for_api(base_url):
            print("❌ Failed to start pre-warming - API not ready")
            return
        
        print("\n" + "="*60)
        print("🔥 STARTING AUTO PRE-WARMING")
        print("="*60)
        
        # Get initial cache stats
        print("\n1️⃣ Getting initial cache statistics...")
        initial_stats = get_cache_stats(base_url)
        
        # Pre-warm common combinations
        print("\n2️⃣ Pre-warming common parameter combinations...")
        successful, failed = prewarm_common_combinations(base_url)
        
        # Get final cache stats
        print("\n3️⃣ Getting final cache statistics...")
        final_stats = get_cache_stats(base_url)
        
        # Test cache performance
        print("\n4️⃣ Testing cache performance...")
        test_cache_performance(base_url)
        
        # Summary
        print("\n🎉 AUTO PRE-WARMING COMPLETE!")
        print("="*60)
        print(f"✅ Successfully warmed: {successful} combinations")
        print(f"❌ Failed to warm: {failed} combinations")
        
        if initial_stats and final_stats:
            hits_added = final_stats.get('hits', 0) - initial_stats.get('hits', 0)
            print(f"📈 Cache hits added: {hits_added}")
            print(f"📊 Final hit rate: {final_stats.get('hit_rate', 0)}%")
        
        print("\n💡 API is now optimized and ready for fast requests!")
        print("🚀 All subsequent requests should be much faster!")
    
    # Start pre-warming in background thread
    prewarm_thread = threading.Thread(target=prewarm_worker, daemon=True)
    prewarm_thread.start()

def main():
    """Main startup function"""
    print("🚀 Flask Fire Door Compliance API with Auto Pre-warming")
    print("="*70)
    
    # Get port from environment variable (Azure App Service compatibility)
    port = int(os.environ.get('PORT', 5001))
    base_url = f"http://localhost:{port}"
    
    print(f"📊 Port: {port}")
    print(f"🧠 AI Providers: OpenAI + Claude")
    print(f"💾 Caching: Enabled (24-hour TTL)")
    print(f"⚡ Performance: Optimized with auto pre-warming")
    print("-" * 70)
    
    # Start pre-warming in background
    print("🔥 Starting auto pre-warming in background...")
    prewarm_api_async(base_url)
    
    # Show API information
    print(f"\n🌐 API Server: {base_url}")
    print(f"📚 API Docs: {base_url}/docs")
    print(f"❤️ Health Check: {base_url}/health")
    print(f"📊 Cache Stats: {base_url}/cache/stats")
    print(f"🎯 Metrics: {base_url}/metrics")
    
    print("\n💡 The API will start pre-warming automatically in the background")
    print("🛑 Press Ctrl+C to stop the server")
    print("="*70)
    
    try:
        # Run the Flask app
        app.run(
            debug=False,  # Set to False for production-like behavior
            host='0.0.0.0',
            port=port,
            use_reloader=False  # Disable reloader to prevent issues with pre-warming
        )
    except KeyboardInterrupt:
        print("\n🛑 Stopping Flask API server...")
        print("✅ Server stopped successfully")

if __name__ == '__main__':
    main()
