#!/usr/bin/env python3
"""
Pre-warming script for Flask Fire Door Compliance API with Caching
Pre-warms cache with common parameter combinations
"""

import requests
import time
import json

def prewarm_common_combinations(base_url):
    """Pre-warm cache with common parameter combinations"""
    print("Pre-warming Flask API cache with common parameter combinations...")
    
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
                print(f"    [OK] {response_time:.2f}s - {analysis_type} analysis")
                successful_warms += 1
            else:
                print(f"    [ERROR] HTTP {response.status_code}")
                failed_warms += 1
                
        except Exception as e:
            print(f"    [ERROR] Error: {str(e)[:50]}...")
            failed_warms += 1
    
    avg_time = total_time / successful_warms if successful_warms > 0 else 0
    
    print(f"\nPre-warming Results:")
    print(f"  [SUCCESS] Successful: {successful_warms}")
    print(f"  [FAILED] Failed: {failed_warms}")
    print(f"  [TIME] Average time: {avg_time:.2f}s")
    print(f"  [RATE] Success rate: {(successful_warms/(successful_warms+failed_warms)*100):.1f}%")
    
    return successful_warms, failed_warms

def test_cache_performance(base_url):
    """Test cache performance with repeated requests"""
    print("\nTesting cache performance...")
    
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
                print(f"  Request {i+1}: [ERROR] HTTP {response.status_code}")
                
        except Exception as e:
            print(f"  Request {i+1}: [ERROR] Error: {str(e)[:30]}...")
    
    if times:
        avg_time = sum(times) / len(times)
        min_time = min(times)
        max_time = max(times)
        
        print(f"\nCache Performance:")
        print(f"  Average: {avg_time:.2f}s")
        print(f"  Min: {min_time:.2f}s")
        print(f"  Max: {max_time:.2f}s")
        
        if avg_time < 1.0:
            print("  [EXCELLENT] Cache is working perfectly")
        elif avg_time < 2.0:
            print("  [GOOD] Cache is working well")
        else:
            print("  [WARNING] Cache performance could be better")

def get_cache_stats(base_url):
    """Get current cache statistics"""
    print("\nGetting cache statistics...")
    
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
            print(f"  [ERROR] Failed to get cache stats: HTTP {response.status_code}")
            return None
    except Exception as e:
        print(f"  [ERROR] Error getting cache stats: {e}")
        return None

def main():
    """Main pre-warming function"""
    print("Flask Fire Door Compliance API Pre-warming")
    print("=" * 60)
    
    base_url = "https://psl-dev-ai-uksouth-b5a3e4d8g3frdugq.uksouth-01.azurewebsites.net"  # Local development
    
    # Step 1: Check if API is running
    print("1. Checking API health...")
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        if response.status_code == 200:
            print("  [OK] API is healthy")
        else:
            print(f"  [ERROR] API health check failed: HTTP {response.status_code}")
            return
    except Exception as e:
        print(f"  [ERROR] API not responding: {e}")
        print("  [INFO] Make sure to start the API first: python run_flask_cached.py")
        return
    
    # Step 2: Get initial cache stats
    print("\n2. Getting initial cache statistics...")
    initial_stats = get_cache_stats(base_url)
    
    # Step 3: Pre-warm common combinations
    print("\n3. Pre-warming common parameter combinations...")
    successful, failed = prewarm_common_combinations(base_url)
    
    # Step 4: Get final cache stats
    print("\n4. Getting final cache statistics...")
    final_stats = get_cache_stats(base_url)
    
    # Step 5: Test cache performance
    print("\n5. Testing cache performance...")
    test_cache_performance(base_url)
    
    # Step 6: Summary
    print("\n[COMPLETE] Pre-warming Complete!")
    print("=" * 60)
    print(f"[SUCCESS] Successfully warmed: {successful} combinations")
    print(f"[FAILED] Failed to warm: {failed} combinations")
    
    if initial_stats and final_stats:
        hits_added = final_stats.get('hits', 0) - initial_stats.get('hits', 0)
        print(f"[INFO] Cache hits added: {hits_added}")
        print(f"[INFO] Final hit rate: {final_stats.get('hit_rate', 0)}%")
    
    print("\n[INFO] Now when you test with different parameters:")
    print("  - First request with new parameters: ~1-2s (instead of 9s)")
    print("  - Subsequent requests with same parameters: <1s")
    print("  - Cache will handle most common parameter combinations")

if __name__ == "__main__":
    main()
