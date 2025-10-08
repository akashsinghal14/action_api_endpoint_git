#!/bin/bash
cd /home/site/wwwroot

# Try different Python commands
if command -v python3 &> /dev/null; then
    echo "Using python3"
    python3 app.py
elif command -v python &> /dev/null; then
    echo "Using python"
    python app.py
elif [ -f /usr/bin/python3 ]; then
    echo "Using /usr/bin/python3"
    /usr/bin/python3 app.py
elif [ -f /usr/bin/python ]; then
    echo "Using /usr/bin/python"
    /usr/bin/python app.py
else
    echo "Python not found, trying to find it..."
    find /usr -name "python*" -type f -executable 2>/dev/null | head -1 | xargs -I {} {} app.py
fi
