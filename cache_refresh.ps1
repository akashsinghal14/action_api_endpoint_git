# Cache Refresh Script for Azure WebJob (PowerShell)
# This script clears and warms the cache automatically
# Deploy this as an Azure WebJob with scheduled trigger

# Configuration
$API_BASE_URL = "https://psl-dev-ai-uksouth-b5a3e4d8g3frdugq.uksouth-01.azurewebsites.net"
$CLEAR_ENDPOINT = "/cache/clear"
$WARMUP_ENDPOINT = "/warmup"
$LOG_FILE = "cache_refresh.log"

# Function to log with timestamp
function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss UTC"
    $logEntry = "[$timestamp] $Message"
    Write-Output $logEntry
    Add-Content -Path $LOG_FILE -Value $logEntry
}

# Function to make HTTP request with retry
function Invoke-RequestWithRetry {
    param(
        [string]$Endpoint,
        [string]$Description,
        [int]$MaxRetries = 3
    )
    
    $retryCount = 0
    
    while ($retryCount -lt $MaxRetries) {
        Write-Log "Attempting $Description (Attempt $($retryCount + 1)/$MaxRetries)"
        
        try {
            $response = Invoke-RestMethod -Uri "$API_BASE_URL$Endpoint" -Method POST -ContentType "application/json" -UserAgent "Azure-WebJob-Cache-Refresh/1.0" -TimeoutSec 300
            
            Write-Log "SUCCESS: $Description completed"
            return $true
        }
        catch {
            $retryCount++
            Write-Log "ERROR: $Description failed - $($_.Exception.Message)"
            
            if ($retryCount -lt $MaxRetries) {
                $waitTime = $retryCount * 30
                Write-Log "Retrying in $waitTime seconds..."
                Start-Sleep -Seconds $waitTime
            }
        }
    }
    
    Write-Log "FAILED: $Description failed after $MaxRetries attempts"
    return $false
}

# Main execution
function Main {
    Write-Log "=== Starting Cache Refresh Process ==="
    Write-Log "API Base URL: $API_BASE_URL"
    Write-Log "Current time: $(Get-Date)"
    Write-Log "Timezone: $([System.TimeZoneInfo]::Local.Id)"
    
    # Step 1: Clear cache
    Write-Log "Step 1: Clearing existing cache..."
    if (Invoke-RequestWithRetry -Endpoint $CLEAR_ENDPOINT -Description "Cache Clear") {
        Write-Log "Cache cleared successfully"
    } else {
        Write-Log "WARNING: Cache clear failed, but continuing with warmup..."
    }
    
    # Wait a moment between operations
    Write-Log "Waiting 5 seconds before warmup..."
    Start-Sleep -Seconds 5
    
    # Step 2: Warm cache
    Write-Log "Step 2: Warming cache with common combinations..."
    if (Invoke-RequestWithRetry -Endpoint $WARMUP_ENDPOINT -Description "Cache Warmup") {
        Write-Log "Cache warmed successfully"
    } else {
        Write-Log "ERROR: Cache warmup failed"
        exit 1
    }
    
    # Step 3: Verify cache status (optional)
    Write-Log "Step 3: Checking cache statistics..."
    try {
        $statsResponse = Invoke-RestMethod -Uri "$API_BASE_URL/cache/stats" -Method GET -UserAgent "Azure-WebJob-Cache-Refresh/1.0" -TimeoutSec 30
        Write-Log "Cache Statistics: $($statsResponse | ConvertTo-Json -Compress)"
    }
    catch {
        Write-Log "WARNING: Could not retrieve cache statistics - $($_.Exception.Message)"
    }
    
    Write-Log "=== Cache Refresh Process Completed ==="
    Write-Log "Process finished at: $(Get-Date)"
}

# Error handling
$ErrorActionPreference = "Stop"
trap {
    Write-Log "ERROR: Script failed at line $($_.InvocationInfo.ScriptLineNumber) - $($_.Exception.Message)"
    exit 1
}

# Run main function
Main
