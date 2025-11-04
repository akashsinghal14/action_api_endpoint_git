#!/bin/bash

# Cache Refresh Script for Azure WebJob
# This script clears and warms the cache automatically
# Deploy this as an Azure WebJob with scheduled trigger

# Configuration
API_BASE_URL="https://psl-dev-ai-uksouth-b5a3e4d8g3frdugq.uksouth-01.azurewebsites.net"
CLEAR_ENDPOINT="/cache/clear"
WARMUP_ENDPOINT="/warmup"
LOG_FILE="/tmp/cache_refresh.log"

# Function to log with timestamp
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S UTC')] $1" | tee -a "$LOG_FILE"
}

# Function to make HTTP request with retry
make_request() {
    local endpoint="$1"
    local description="$2"
    local max_retries=3
    local retry_count=0
    
    while [ $retry_count -lt $max_retries ]; do
        log_message "Attempting $description (Attempt $((retry_count + 1))/$max_retries)"
        
        response=$(curl -s -w "\n%{http_code}" -X POST "${API_BASE_URL}${endpoint}" \
            -H "Content-Type: application/json" \
            -H "User-Agent: Azure-WebJob-Cache-Refresh/1.0" \
            --connect-timeout 30 \
            --max-time 300)
        
        http_code=$(echo "$response" | tail -n1)
        response_body=$(echo "$response" | head -n -1)
        
        if [ "$http_code" -eq 200 ]; then
            log_message "SUCCESS: $description completed (HTTP $http_code)"
            return 0
        else
            log_message "ERROR: $description failed (HTTP $http_code) - Response: $response_body"
            retry_count=$((retry_count + 1))
            
            if [ $retry_count -lt $max_retries ]; then
                wait_time=$((retry_count * 30))
                log_message "Retrying in ${wait_time} seconds..."
                sleep $wait_time
            fi
        fi
    done
    
    log_message "FAILED: $description failed after $max_retries attempts"
    return 1
}

# Main execution
main() {
    log_message "=== Starting Cache Refresh Process ==="
    log_message "API Base URL: $API_BASE_URL"
    log_message "Current time: $(date)"
    log_message "Timezone: $(date +%Z)"
    
    # Step 1: Clear cache
    log_message "Step 1: Clearing existing cache..."
    if make_request "$CLEAR_ENDPOINT" "Cache Clear"; then
        log_message "Cache cleared successfully"
    else
        log_message "WARNING: Cache clear failed, but continuing with warmup..."
    fi
    
    # Wait a moment between operations
    log_message "Waiting 5 seconds before warmup..."
    sleep 5
    
    # Step 2: Warm cache
    log_message "Step 2: Warming cache with common combinations..."
    if make_request "$WARMUP_ENDPOINT" "Cache Warmup"; then
        log_message "Cache warmed successfully"
    else
        log_message "ERROR: Cache warmup failed"
        exit 1
    fi
    
    # Step 3: Verify cache status (optional)
    log_message "Step 3: Checking cache statistics..."
    stats_response=$(curl -s -w "\n%{http_code}" "${API_BASE_URL}/cache/stats" \
        -H "User-Agent: Azure-WebJob-Cache-Refresh/1.0" \
        --connect-timeout 10 \
        --max-time 30)
    
    stats_http_code=$(echo "$stats_response" | tail -n1)
    stats_body=$(echo "$stats_response" | head -n -1)
    
    if [ "$stats_http_code" -eq 200 ]; then
        log_message "Cache Statistics: $stats_body"
    else
        log_message "WARNING: Could not retrieve cache statistics (HTTP $stats_http_code)"
    fi
    
    log_message "=== Cache Refresh Process Completed ==="
    log_message "Process finished at: $(date)"
}

# Error handling
set -e
trap 'log_message "ERROR: Script failed at line $LINENO"' ERR

# Run main function
main "$@"
