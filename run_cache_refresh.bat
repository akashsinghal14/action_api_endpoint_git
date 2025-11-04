@echo off
REM Cache Refresh Batch File for Azure WebJob
REM This calls the PowerShell script for cache refresh

echo Starting Cache Refresh Process...
echo Current time: %date% %time%

REM Run the PowerShell script
powershell.exe -ExecutionPolicy Bypass -File "cache_refresh.ps1"

echo Cache Refresh Process Completed
echo Finished at: %date% %time%
