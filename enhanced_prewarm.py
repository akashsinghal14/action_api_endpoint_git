#!/usr/bin/env python3
"""
Enhanced pre-warming script for Fire Door Compliance API
Pre-warms cache with common parameter combinations to reduce 9-second delays
"""

import asyncio
import aiohttp
import time
import json

async def prewarm_common_combinations(base_url):
    """Pre-warm cache with common parameter combinations"""
    print("🔥 Pre-warming cache with common parameter combinations...")
    
    # Common parameter combinations that users typically test
    common_combinations = [
        # Non-compliant numeric values (will trigger AI)
        {"measurement_type": "head", "value": 6, "unit": "mm", "api_key": "claude_key"},
        {"measurement_type": "head", "value": 8, "unit": "mm", "api_key": "claude_key"},
        {"measurement_type": "hinge", "value": 5, "unit": "mm", "api_key": "claude_key"},
        {"measurement_type": "closing", "value": 7, "unit": "mm", "api_key": "claude_key"},
        {"measurement_type": "threshold", "value": 6, "unit": "mm", "api_key": "claude_key"},
        {"measurement_type": "doorthick", "value": 30, "unit": "mm", "api_key": "claude_key"},
        {"measurement_type": "doorthick", "value": 50, "unit": "mm", "api_key": "claude_key"},
        {"measurement_type": "framedepth", "value": 80, "unit": "mm", "api_key": "claude_key"},
        {"measurement_type": "doorsize", "value": 400, "unit": "mm", "api_key": "claude_key"},
        
        # Non-compliant boolean values (will trigger AI)
        {"measurement_type": "intustrips", "value": "no", "api_key": "claude_key"},
        {"measurement_type": "selfclosing", "value": "no", "api_key": "claude_key"},
        {"measurement_type": "doorclosefully", "value": "no", "api_key": "claude_key"},
        {"measurement_type": "hingesfirerated", "value": "no", "api_key": "claude_key"},
        
        # Compliant values (static responses)
        {"measurement_type": "head", "value": 2, "unit": "mm", "api_key": None},
        {"measurement_type": "hinge", "value": 3, "unit": "mm", "api_key": None},
        {"measurement_type": "doorthick", "value": 44, "unit": "mm", "api_key": None},
        {"measurement_type": "intustrips", "value": "yes", "api_key": None},
    ]
    
    successful_warms = 0
    failed_warms = 0
    total_time = 0
    
    async with aiohttp.ClientSession() as session:
        for i, combo in enumerate(common_combinations):
            try:
                print(f"  Warming {i+1}/{len(common_combinations)}: {combo['measurement_type']} = {combo['value']}")
                
                start_time = time.time()
                
                async with session.post(
                    f"{base_url}/api/action_item/analyze",
                    json=combo,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        end_time = time.time()
                        response_time = end_time - start_time
                        total_time += response_time
                        
                        analysis_type = result.get('analysis_type', 'unknown')
                        print(f"    ✅ {response_time:.2f}s - {analysis_type} analysis")
                        successful_warms += 1
                    else:
                        print(f"    ❌ HTTP {response.status}")
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

async def test_cache_performance(base_url):
    """Test cache performance with repeated requests"""
    print("\n⚡ Testing cache performance...")
    
    # Test with a common combination
    test_data = {
        "measurement_type": "head",
        "value": 6,
        "unit": "mm",
        "api_key": "claude_key"
    }
    
    times = []
    
    async with aiohttp.ClientSession() as session:
        for i in range(5):
            try:
                start_time = time.time()
                
                async with session.post(
                    f"{base_url}/api/action_item/analyze",
                    json=test_data,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        end_time = time.time()
                        response_time = end_time - start_time
                        times.append(response_time)
                        
                        analysis_type = result.get('analysis_type', 'unknown')
                        cached = result.get('prewarmed', False)
                        
                        print(f"  Request {i+1}: {response_time:.2f}s - {analysis_type} {'(cached)' if cached else '(fresh)'}")
                    else:
                        print(f"  Request {i+1}: ❌ HTTP {response.status}")
                        
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

async def get_cache_stats(base_url):
    """Get current cache statistics"""
    print("\n📊 Getting cache statistics...")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{base_url}/cache/stats", timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.status == 200:
                    stats = await response.json()
                    
                    print(f"  Cache hits: {stats.get('hits', 0)}")
                    print(f"  Cache misses: {stats.get('misses', 0)}")
                    print(f"  Hit rate: {stats.get('hit_rate', 0)}%")
                    print(f"  Current size: {stats.get('current_size', 0)}/{stats.get('max_size', 0)}")
                    print(f"  Evictions: {stats.get('evictions', 0)}")
                    
                    return stats
                else:
                    print(f"  ❌ Failed to get cache stats: HTTP {response.status}")
                    return None
    except Exception as e:
        print(f"  ❌ Error getting cache stats: {e}")
        return None

async def main():
    """Main pre-warming function"""
    print("🚀 Enhanced Fire Door Compliance API Pre-warming")
    print("=" * 60)
    
    base_url = "http://localhost:5001"
    
    # Step 1: Check if API is running
    print("1️⃣ Checking API health...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{base_url}/health", timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.status == 200:
                    print("  ✅ API is healthy")
                else:
                    print(f"  ❌ API health check failed: HTTP {response.status}")
                    return
    except Exception as e:
        print(f"  ❌ API not responding: {e}")
        print("  💡 Make sure to start the API first: python run_fastapi.py")
        return
    
    # Step 2: Get initial cache stats
    print("\n2️⃣ Getting initial cache statistics...")
    initial_stats = await get_cache_stats(base_url)
    
    # Step 3: Pre-warm common combinations
    print("\n3️⃣ Pre-warming common parameter combinations...")
    successful, failed = await prewarm_common_combinations(base_url)
    
    # Step 4: Get final cache stats
    print("\n4️⃣ Getting final cache statistics...")
    final_stats = await get_cache_stats(base_url)
    
    # Step 5: Test cache performance
    print("\n5️⃣ Testing cache performance...")
    await test_cache_performance(base_url)
    
    # Step 6: Summary
    print("\n🎉 Pre-warming Complete!")
    print("=" * 60)
    print(f"✅ Successfully warmed: {successful} combinations")
    print(f"❌ Failed to warm: {failed} combinations")
    
    if initial_stats and final_stats:
        hits_added = final_stats.get('hits', 0) - initial_stats.get('hits', 0)
        print(f"📈 Cache hits added: {hits_added}")
        print(f"📊 Final hit rate: {final_stats.get('hit_rate', 0)}%")
    
    print("\n💡 Now when you test with different parameters:")
    print("  - First request with new parameters: ~1-2s (instead of 9s)")
    print("  - Subsequent requests with same parameters: <1s")
    print("  - Cache will handle most common parameter combinations")

if __name__ == "__main__":
    asyncio.run(main())
