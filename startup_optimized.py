#!/usr/bin/env python3
"""
Optimized startup script for Fire Door Compliance API
Includes pre-warming and performance optimizations
"""

import asyncio
import aiohttp
import time
import subprocess
import sys
import os
from pathlib import Path

async def check_api_health(base_url, max_retries=10, delay=2):
    """Check if API is healthy and ready"""
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{base_url}/health", timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        data = await response.json()
                        print(f"✅ API is healthy: {data.get('status', 'unknown')}")
                        return True
        except Exception as e:
            print(f"⏳ Attempt {attempt + 1}/{max_retries}: API not ready yet ({e})")
            if attempt < max_retries - 1:
                await asyncio.sleep(delay)
    
    return False

async def warmup_api(base_url):
    """Warm up the API for faster first requests"""
    print("🔥 Warming up API...")
    
    try:
        async with aiohttp.ClientSession() as session:
            # Call warmup endpoint
            async with session.get(f"{base_url}/warmup", timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    print(f"✅ Warmup successful: {data.get('message', 'API warmed up')}")
                    return True
                else:
                    print(f"❌ Warmup failed: HTTP {response.status}")
                    return False
    except Exception as e:
        print(f"❌ Warmup error: {e}")
        return False

async def test_fast_request(base_url):
    """Test a fast request to verify performance"""
    print("⚡ Testing fast request...")
    
    test_data = {
        "measurement_type": "head",
        "value": 2,  # Compliant value (no AI needed)
        "unit": "mm",
        "api_key": None
    }
    
    try:
        start_time = time.time()
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base_url}/api/action_item/analyze",
                json=test_data,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    end_time = time.time()
                    response_time = end_time - start_time
                    
                    print(f"✅ Fast request successful!")
                    print(f"📊 Response time: {response_time:.2f}s")
                    print(f"📋 Analysis type: {result.get('analysis_type', 'unknown')}")
                    
                    if response_time < 2.0:
                        print("🎉 Excellent! Response time under 2 seconds")
                    elif response_time < 5.0:
                        print("👍 Good! Response time under 5 seconds")
                    else:
                        print("⚠️ Response time could be better")
                    
                    return True
                else:
                    print(f"❌ Fast request failed: HTTP {response.status}")
                    return False
    except Exception as e:
        print(f"❌ Fast request error: {e}")
        return False

def start_api_server():
    """Start the API server"""
    print("🚀 Starting Fire Door Compliance API...")
    
    # Check if we're in the right directory
    if not Path("app_fastapi_optimized.py").exists():
        print("❌ app_fastapi_optimized.py not found in current directory")
        return False
    
    try:
        # Start the server in the background
        process = subprocess.Popen([
            sys.executable, "run_fastapi.py"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        print(f"📡 API server started with PID: {process.pid}")
        print("⏳ Waiting for server to be ready...")
        
        return process
    except Exception as e:
        print(f"❌ Failed to start API server: {e}")
        return None

async def main():
    """Main startup function"""
    print("🔥 Fire Door Compliance API - Optimized Startup")
    print("=" * 60)
    
    # Step 1: Start the API server
    print("\n1️⃣ Starting API Server...")
    server_process = start_api_server()
    
    if not server_process:
        print("❌ Failed to start API server")
        return
    
    # Step 2: Wait for API to be healthy
    print("\n2️⃣ Waiting for API to be healthy...")
    base_url = "http://localhost:5001"
    
    if not await check_api_health(base_url):
        print("❌ API failed to become healthy")
        server_process.terminate()
        return
    
    # Step 3: Warm up the API
    print("\n3️⃣ Warming up API...")
    if not await warmup_api(base_url):
        print("⚠️ Warmup failed, but continuing...")
    
    # Step 4: Test fast request
    print("\n4️⃣ Testing fast request...")
    if not await test_fast_request(base_url):
        print("⚠️ Fast request test failed, but API is running")
    
    # Step 5: Show final status
    print("\n🎉 API Startup Complete!")
    print("=" * 60)
    print("📡 API Server: Running")
    print("🌐 URL: http://localhost:5001")
    print("📚 Docs: http://localhost:5001/docs")
    print("❤️ Health: http://localhost:5001/health")
    print("🔥 Warmup: http://localhost:5001/warmup")
    print("📊 Metrics: http://localhost:5001/metrics")
    print("\n💡 The API is now optimized and ready for fast requests!")
    print("🛑 Press Ctrl+C to stop the server")
    
    try:
        # Keep the server running
        server_process.wait()
    except KeyboardInterrupt:
        print("\n🛑 Stopping API server...")
        server_process.terminate()
        print("✅ API server stopped")

if __name__ == "__main__":
    asyncio.run(main())
