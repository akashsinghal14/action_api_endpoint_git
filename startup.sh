#!/bin/bash
export PYTHONPATH="${PYTHONPATH}:."
exec gunicorn application:app --bind=0.0.0.0:8000 --workers=4 --timeout=300 --graceful-timeout=300
