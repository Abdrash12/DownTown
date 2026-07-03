#!/usr/bin/env bash
set -e

echo "[1/4] Installing Deno JS runtime (using Python to bypass missing unzip)..."
mkdir -p ~/.deno/bin
curl -L https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip -o /tmp/deno.zip
python3 -m zipfile -e /tmp/deno.zip ~/.deno/bin
chmod +x ~/.deno/bin/deno
rm /tmp/deno.zip
export PATH="$HOME/.deno/bin:$PATH"

echo "[2/4] Upgrading yt-dlp and EJS challenge solver..."
pip install --upgrade --no-cache-dir yt-dlp yt-dlp-ejs

echo "[3/4] Starting Celery Background Worker..."
celery -A app.celery_app worker --concurrency=2 --max-tasks-per-child=5 --loglevel=info &

echo "[4/4] Starting Flask Web Server..."
exec gunicorn --bind 0.0.0.0:5000 --workers=2 --threads=2 app:app
