import os
import sys
import subprocess
from flask import Flask, render_template, request, jsonify, Response

app = Flask(__name__, template_folder='templates', static_folder='static')

# 1. TUNNEL CONFIG: We pass --cookies and use ONLY cookie-compatible clients.
# This completely bypasses Render's HTTP 429 datacenter rate limits!
YTDL_BASE_ARGS = [
    sys.executable, '-m', 'yt_dlp',
    '--quiet',
    '--no-warnings',
    '--no-playlist',
    '--socket-timeout', '15',
    '--remote-components', 'ejs:github',
    '--cookies', 'cookies.txt',  # <-- MANDATORY FOR RENDER CLOUD IPs
    '--concurrent-fragments', '8',
    '--extractor-args', 'youtube:player_client=web_creator,web_safari,web_embedded,default;player_skip=android,ios,mweb,tv'
]

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/fetch', methods=['POST'])
def fetch_metadata():
    data = request.json
    if not data or 'url' not in data:
        return jsonify({'error': 'Please provide a valid URL!'}), 400

    url = data['url']
    
    try:
        import yt_dlp
        # 2. METADATA CONFIG: Passes cookiefile and uses cookie-friendly client APIs
        opts = {
            'quiet': True,
            'skip_download': True,
            'cookiefile': 'cookies.txt',  # <-- AUTHORIZES SCRAPING TO BYPASS 429 ERRORS
            'remote_components': ['ejs:github'],
            'extractor_args': {
                'youtube': {
                    'player_client': ['web_creator', 'web_safari', 'web_embedded', 'default'],
                    'player_skip': ['android', 'ios', 'mweb', 'tv']
                }
            }
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = []
            
            for f in info.get('formats', []):
                if 'storyboard' in str(f.get('format_note', '')).lower() or not f.get('format_id'):
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
                    'note': note
                })

            if not formats:
                formats.append({'format_id': 'best', 'note': 'Best Available Quality'})

            return jsonify({
                'title': info.get('title', 'Media Stream'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': str(info.get('duration', 'Unknown')),
                'formats': formats,
                'original_url': url
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/tunnel_download')
def tunnel_download():
    """
    Spawns yt-dlp with 8 concurrent threads using your cookies.txt to bypass datacenter blocks,
    piping the high-speed MP4 stream directly to the user's browser.
    """
    url = request.args.get('url')
    format_id = request.args.get('format_id', 'best')
    title = request.args.get('title', 'video').replace(' ', '_')

    if not url:
        return "Missing URL", 400

    cmd = YTDL_BASE_ARGS + [
        '-f', format_id,
        '-o', '-', 
        url
    ]

    def generate():
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=10**7  # 10MB memory buffer for maximum transfer throughput
        )
        try:
            while True:
                chunk = process.stdout.read(1048576)
                if not chunk:
                    break
                yield chunk
        finally:
            process.kill()

    headers = {
        'Content-Disposition': f'attachment; filename="{title}.mp4"',
        'Content-Type': 'video/mp4'
    }
    return Response(generate(), headers=headers)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
