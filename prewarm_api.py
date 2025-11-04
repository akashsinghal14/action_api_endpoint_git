#!/usr/bin/env python3
"""
Pre-warm script to reduce first API call latency
Runs a lightweight request to initialize the API
"""

import asyncio
import aiohttp
import time
import json

async def prewarm_api():
    """Pre-warm the API with a lightweight request"""
    base_url = "http://localhost:5001"
    
    print("🔥 Pre-warming API to reduce first call latency...")
    
    # Test data - use a simple, fast request
    test_data = {
        "measurement_type": "head",
        "value": 2,  # Compliant value (no AI needed)
        "unit": "mm",
        "api_key": None  # No API key = static response (faster)
    }
    
    try:
        start_time = time.time()
        
        async with aiohttp.ClientSession() as session:
            # Make a simple request to initialize everything
            async with session.post(
                f"{base_url}/api/action_item/analyze",
                json=test_data,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    end_time = time.time()
                    response_time = end_time - start_time
                    
                    print(f"✅ Pre-warm successful!")
                    print(f"📊 Response time: {response_time:.2f}s")
                    print(f"📋 Result: {result.get('analysis_type', 'unknown')} analysis")
                    print(f"🎯 Compliant: {result.get('compliant', False)}")
                    
                    return True
                else:
                    print(f"❌ Pre-warm failed: HTTP {response.status}")
                    return False
                    
    except Exception as e:
        print(f"❌ Pre-warm error: {e}")
        return False

async def prewarm_with_ai():
    """Pre-warm with AI call to initialize Claude connection"""
    base_url = "http://localhost:5001"
    
    print("🧠 Pre-warming with AI call to initialize Claude...")
    
    # Test data that will trigger AI
    test_data = {
        "measurement_type": "head",
        "value": 6,  # Non-compliant value (triggers AI)
        "unit": "mm",
        "api_key": "claude_key",  # Use your API key
        "ai_provider": "claude"
    }
    
    try:
        start_time = time.time()
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base_url}/api/action_item/analyze",
                json=test_data,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    end_time = time.time()
                    response_time = end_time - start_time
                    
                    print(f"✅ AI Pre-warm successful!")
                    print(f"📊 Response time: {response_time:.2f}s")
                    print(f"🧠 AI Provider: {result.get('ai_provider', 'unknown')}")
                    print(f"💰 Cost: ${result.get('cost_usd', 0)}")
                    
                    return True
                else:
                    print(f"❌ AI Pre-warm failed: HTTP {response.status}")
                    return False
                    
    except Exception as e:
        print(f"❌ AI Pre-warm error: {e}")
        return False

async def main():
    """Main pre-warm function"""
    print("🚀 Starting API Pre-warming Process")
    print("=" * 50)
    
    # Step 1: Basic pre-warm (static response)
    print("\n1️⃣ Basic Pre-warm (Static Response)...")
    basic_success = await prewarm_api()
    
    if basic_success:
        print("\n2️⃣ AI Pre-warm (Claude Connection)...")
        ai_success = await prewarm_with_ai()
        
        if ai_success:
            print("\n🎉 Pre-warming Complete!")
            print("📈 Subsequent API calls should be much faster now")
        else:
            print("\n⚠️ AI Pre-warm failed, but basic pre-warm succeeded")
    else:
        print("\n❌ Pre-warming failed. Make sure the API is running.")

if __name__ == "__main__":
    asyncio.run(main())
