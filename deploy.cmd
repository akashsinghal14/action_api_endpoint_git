@if "%SCM_TRACE_LEVEL%" NEQ "4" @echo off

echo "Starting deployment script..."

REM Try different Python paths
if exist "D:\home\Python311\python.exe" (
    echo "Using D:\home\Python311\python.exe"
    "D:\home\Python311\python.exe" app.py
) else if exist "D:\home\Python39\python.exe" (
    echo "Using D:\home\Python39\python.exe"
    "D:\home\Python39\python.exe" app.py
) else (
    echo "Using default python"
    python app.py
)

echo "Deployment script completed."
