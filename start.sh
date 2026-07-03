#!/usr/bin/env bash
set -e

echo "[WARP] Registering free Cloudflare WARP account..."
# Generate account and profile (silently ignores if already generated)
wgcf register --accept-tos || true
wgcf generate || true

echo "[WARP] Creating wireproxy SOCKS5 configuration..."
# Create a config that tells wireproxy to take the WARP profile and expose a SOCKS5 proxy on port 4000
cat <<EOF > wireproxy.conf
[Interface]
WGConfig = wgcf-profile.conf

[Socks5]
BindAddress = 127.0.0.1:4000
EOF

echo "[WARP] Starting Cloudflare WARP SOCKS5 tunnel in background..."
wireproxy -c wireproxy.conf &

# Give the tunnel 3 seconds to connect to Cloudflare's edge network
sleep 3
echo "[WARP] Tunnel established on socks5://127.0.0.1:4000!"

echo "Upgrading yt-dlp to latest release to bypass anti-bot patches..."
pip install --upgrade --no-cache-dir yt-dlp

echo "Starting Celery Background Worker..."
celery -A app.celery_app worker --loglevel=info &

echo "Starting Flask Web Server..."
exec gunicorn --bind 0.0.0.0:5000 app:app
