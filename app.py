import os
import sys
import json
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SECRET_KEY'] = 'downtown_secret_relay_key'

# Initialize SocketIO with CORS allowed for all origins so mobile/desktop browsers connect cleanly
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

@app.route('/')
def index():
    return render_template('index.html')


@socketio.on('connect')
def handle_connect():
    print(f"[RELAY] Client connected as distributed node: {request.sid}")
    emit('relay_status', {'status': 'Connected to C2 Signaling Broker'})


@socketio.on('request_extraction')
def handle_extraction_request(data):
    """
    1. Receives the YouTube URL from the client browser via WebSocket.
    2. Runs a lightweight metadata & signature calculation locally without downloading.
    3. Pushes the decrypted, direct CDN stream URLs back to the client browser to fetch natively.
    """
    url = data.get('url')
    if not url:
        emit('relay_error', {'error': 'No URL provided'})
        return

    print(f"[RELAY] Computing stream signatures for: {url}")
    emit('relay_progress', {'percent': 10, 'message': 'Resolving CDN signatures on C2 node...'})

    try:
        import yt_dlp
        
        # We use android_vr and web_embedded because their URLs are structured for CORS fetching
        opts = {
            'quiet': True,
            'skip_download': True,
            'remote_components': ['ejs:github'],
            'extractor_args': {
                'youtube': {
                    'player_client': ['android_vr', 'web_embedded', 'default'],
                    'player_skip': ['web', 'ios', 'mweb', 'tv']
                }
            }
        }
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = []
            
            for f in info.get('formats', []):
                # We strictly extract formats that contain a valid, direct CDN URL
                direct_url = f.get('url')
                if not direct_url or 'storyboard' in str(f.get('format_note', '')).lower():
                    continue
                
                ext = f.get('ext', 'mp4')
                res = f.get('resolution') or f.get('format_note') or f.get('height', 'Unknown')
                note = f"{ext.upper()} - {res}"
                
                if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                    note += " (Video + Audio)"
                elif f.get('vcodec') == 'none':
                    note += " (Audio Only)"

                formats.append({
                    'format_id': f.get('format_id'),
                    'note': note,
                    'cdn_url': direct_url,
                    'filesize': f.get('filesize') or f.get('filesize_approx') or 0
                })

            if not formats:
                emit('relay_error', {'error': 'Could not extract direct client-playable CDN nodes.'})
                return

            payload = {
                'title': info.get('title', 'Media Stream').replace(' ', '_'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': str(info.get('duration', 'Unknown')),
                'formats': formats
            }

            # PUSH TO CLIENT: Send decrypted links down the WebSocket to the browser's residential IP
            emit('relay_success', payload)
            print(f"[RELAY] Pushed {len(formats)} CDN nodes to client {request.sid}")

    except Exception as e:
        print(f"[RELAY ERROR] {str(e)}")
        emit('relay_error', {'error': f"Signaling failure: {str(e)}"})


if __name__ == '__main__':
    # Use SocketIO's eventlet web server instead of basic app.run
    socketio.run(app, host='0.0.0.0', port=5000)
