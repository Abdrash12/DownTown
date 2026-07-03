#!/usr/bin/env bash
set -e

echo "[1/4] Installing Deno JS runtime (required for YouTube signature solving)..."
curl -fsSL https://deno.land/install.sh | sh -s -- -y
export PATH="$HOME/.deno/bin:$PATH"

echo "[2/4] Upgrading yt-dlp and EJS challenge solver..."
pip install --upgrade --no-cache-dir yt-dlp yt-dlp-ejs

echo "[3/4] Starting Celery Background Worker..."
celery -A app.celery_app worker --concurrency=2 --max-tasks-per-child=5 --loglevel=info &

echo "[4/4] Starting Flask Web Server..."
exec gunicorn --bind 0.0.0.0:5000 --workers=2 --threads=2 app:app
