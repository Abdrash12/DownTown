#!/usr/bin/env bash
set -e

echo "Upgrading yt-dlp to latest release..."
pip install --upgrade --no-cache-dir yt-dlp

echo "Starting Celery Background Worker with strict Memory & CPU Limits..."
# --concurrency=2: Maximum 2 downloads at a time so RAM stays under 512MB
# --max-tasks-per-child=5: Restarts worker process after 5 downloads to clear any FFmpeg memory leaks
celery -A app.celery_app worker --concurrency=2 --max-tasks-per-child=5 --loglevel=info &

echo "Starting Flask Web Server..."
exec gunicorn --bind 0.0.0.0:5000 --workers=2 --threads=2 app:app
