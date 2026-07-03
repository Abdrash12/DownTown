#!/usr/bin/env bash
set -e

echo "Upgrading yt-dlp to latest release to bypass anti-bot patches..."
pip install --upgrade --no-cache-dir yt-dlp

echo "Starting Celery Background Worker..."
# We use the -D (detach) flag if needed, but & is fine here
celery -A app.celery_app worker --loglevel=info &

echo "Starting Flask Web Server..."
# 'exec' replaces the shell with the gunicorn process
exec gunicorn --bind 0.0.0.0:5000 app:app
