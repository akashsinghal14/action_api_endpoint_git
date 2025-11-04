# Azure App Service Deployment Guide for Cache Warming

## 🚀 Azure-Optimized Flask API with Cache Warming

This guide explains how to deploy the Azure-optimized Flask API with working cache warming to Azure App Services.

## 📁 Files Created

- `app_azure_optimized.py` - Main Flask application with Azure-specific fixes
- `run_azure_optimized.py` - Run script for Azure deployment
- `requirements_azure_optimized.txt` - Dependencies for Azure deployment

## 🔧 Azure App Service Configuration

### 1. Application Settings (Required)

Add these environment variables in Azure App Service Configuration:

```
AUTO_WARM_CACHE = true
ENABLE_CACHING = true
CACHE_TTL_HOURS = 24
MAX_CACHE_SIZE = 1000
AZURE_WARMUP_TIMEOUT = 300
AZURE_STARTUP_DELAY = 1
WEBSITES_CONTAINER_START_TIME_LIMIT = 600
```

### 2. Always On Feature

```
Configuration → General settings → Always On = On
```

### 3. Startup Command

Set the startup command in Azure App Service:
```
python run_azure_optimized.py
```

## 🛠️ Key Azure Fixes Implemented

### 1. **Non-Daemon Threads**
- **Problem**: Azure terminates daemon threads during startup
- **Fix**: Use `daemon=False` for cache warming threads
- **Code**: `threading.Thread(target=warm_in_background, daemon=False)`

### 2. **Azure Environment Detection**
- **Problem**: Different behavior needed for Azure vs Local
- **Fix**: Detect Azure using `WEBSITE_SITE_NAME` environment variable
- **Code**: `is_azure_app_service()` function

### 3. **Startup Timing Optimization**
- **Problem**: Azure has strict startup timeouts
- **Fix**: Shorter delay for Azure (1s vs 3s local)
- **Code**: `AZURE_STARTUP_DELAY = 1` for Azure

### 4. **Warmup Timeout Protection**
- **Problem**: Cache warming might exceed Azure startup limits
- **Fix**: Timeout protection for cache warming process
- **Code**: `AZURE_WARMUP_TIMEOUT = 300` (5 minutes)

### 5. **Azure-Specific Warmup Endpoint**
- **Problem**: Azure needs a specific endpoint for application initialization
- **Fix**: Added `/api/warmup` endpoint for Azure warmup
- **Code**: `@app.route('/api/warmup', methods=['GET'])`

### 6. **Enhanced Error Handling**
- **Problem**: Cache warming failures not properly handled in Azure
- **Fix**: Comprehensive error handling and logging
- **Code**: Try-catch blocks with detailed error reporting

### 7. **Resource Optimization**
- **Problem**: Azure has limited resources during startup
- **Fix**: Optimized cache warming with timeout checks
- **Code**: Early termination if timeout reached

## 📋 Deployment Steps

### 1. **Upload Files to Azure**
Upload these files to your Azure App Service:
- `app_azure_optimized.py`
- `run_azure_optimized.py`
- `requirements_azure_optimized.txt`

### 2. **Set Application Settings**
In Azure Portal → App Service → Configuration → Application settings:
```
AUTO_WARM_CACHE = true
ENABLE_CACHING = true
CACHE_TTL_HOURS = 24
MAX_CACHE_SIZE = 1000
AZURE_WARMUP_TIMEOUT = 300
AZURE_STARTUP_DELAY = 1
WEBSITES_CONTAINER_START_TIME_LIMIT = 600
```

### 3. **Enable Always On**
In Azure Portal → App Service → Configuration → General settings:
```
Always On = On
```

### 4. **Set Startup Command**
In Azure Portal → App Service → Configuration → General settings:
```
Startup Command = python run_azure_optimized.py
```

### 5. **Deploy and Test**
1. Deploy the application
2. Check logs for cache warming messages
3. Test the `/api/warmup` endpoint
4. Verify cache warming is working

## 🔍 Monitoring and Debugging

### 1. **Check Logs**
Look for these messages in Azure App Service logs:
```
🌍 Environment: Azure App Service
🔥 Starting Azure-optimized automatic cache warming...
📊 Azure-Optimized Cache Warming Results:
```

### 2. **Test Warmup Endpoint**
Call the warmup endpoint to verify Azure initialization:
```
GET https://yourapp.azurewebsites.net/api/warmup
```

### 3. **Check Cache Stats**
Monitor cache performance:
```
GET https://yourapp.azurewebsites.net/api/cache/stats
```

## 🚨 Troubleshooting

### Cache Warming Not Working
1. Check `AUTO_WARM_CACHE = true` in application settings
2. Verify `Always On` is enabled
3. Check startup timeout: `WEBSITES_CONTAINER_START_TIME_LIMIT = 600`
4. Review logs for error messages

### Slow Startup
1. Increase `WEBSITES_CONTAINER_START_TIME_LIMIT`
2. Reduce `AZURE_WARMUP_TIMEOUT` if needed
3. Check App Service pricing tier (higher tiers have more resources)

### Environment Detection Issues
1. Verify `WEBSITE_SITE_NAME` is set in Azure
2. Check application settings are properly configured
3. Review logs for environment detection messages

## ✅ Expected Results

After deployment, you should see:
- Cache warming starts automatically on app startup
- Azure-specific optimizations are applied
- Warmup endpoint responds successfully
- Cache statistics show warming activity
- API responses are fast due to pre-warmed cache

## 🎯 Benefits

- **Faster API responses** - Cache is pre-warmed
- **Azure compatibility** - Designed specifically for Azure App Services
- **Reliable startup** - Handles Azure-specific constraints
- **Better monitoring** - Enhanced logging and statistics
- **Automatic scaling** - Works with Azure App Service scaling

This Azure-optimized version should resolve all cache warming issues in Azure App Services!
