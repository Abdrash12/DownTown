#!/usr/bin/env bash
# Exit immediately if a command exits with a non-zero status
set -e

echo "Starting Celery Background Worker..."
# The '&' at the end pushes Celery into the background so the script keeps running
celery -A app.celery_app worker --loglevel=info &

echo "Starting Flask Web Server..."
# 'exec' replaces the shell with Gunicorn in the foreground (so Render can monitor it)
exec gunicorn --bind 0.0.0.0:5000 app:app
