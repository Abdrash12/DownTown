#!/bin/bash
set -e

echo "[WARP] Registering fresh anonymous Cloudflare WARP identity..."
wgcf register --accept-tos
wgcf generate

echo "[WARP] Configuring internal SOCKS5 proxy on port 40000..."
echo "" >> wgcf-profile.conf
echo "[Socks5]" >> wgcf-profile.conf
echo "BindAddress = 127.0.0.1:40000" >> wgcf-profile.conf

echo "[WARP] Launching WireProxy background tunnel..."
wireproxy -c wgcf-profile.conf &

echo "[WARP] Waiting 4 seconds for WireGuard handshake..."
sleep 4

echo "[SERVER] Booting Gunicorn Production Server..."
exec gunicorn --bind 0.0.0.0:5000 app:app --timeout 120 --workers 2
