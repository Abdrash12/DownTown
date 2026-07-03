import os
from flask import Flask, render_template, request, jsonify, send_file
from celery import Celery
import yt_dlp

app = Flask(__name__)
@app.route('/')
def index():
    return render_template('index.html')
# ==========================================
# 1. CONFIGURATION
# ==========================================
# Ensure REDIS_URL starts with 'rediss://' in your Render dashboard
REDIS_URL = os.environ.get('REDIS_URL')
PROXY_URL = os.environ.get('PROXY_URL') # Your Webshare http:// string

app.config['broker_url'] = REDIS_URL
app.config['result_backend'] = REDIS_URL

celery_app = Celery(app.name, broker=app.config['broker_url'])
celery_app.conf.update(app.config)

DOWNLOAD_DIR = os.path.join(os.getcwd(), 'downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ==========================================
# 2. BACKGROUND TASK
# ==========================================
@celery_app.task(bind=True)
def process_download(self, url, format_id, title):
    safe_title = "".join(x for x in title if x.isalnum() or x in " _-").strip()
    output_template = os.path.join(DOWNLOAD_DIR, f"{safe_title}.%(ext)s")

    ydl_opts = {
        'format': f"{format_id}+bestaudio/{format_id}/bestvideo+bestaudio/best",
        'outtmpl': output_template,
        'merge_output_format': 'mp4',
        'quiet': True,
        'proxy': PROXY_URL,
        'js_runtimes': {'node': {}},
        'extractor_args': {'youtube': {'player_client': ['default', 'web', 'android', 'ios']}}
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return {'status': 'Completed', 'filename': os.path.basename(ydl.prepare_filename(info))}
    except Exception as e:
        raise Exception(str(e))

# ==========================================
# 3. HTTP ENDPOINTS (WITH FALLBACK)
# ==========================================
@app.route('/trigger_download', methods=['POST'])
def trigger_download():
    data = request.json
    # Defensive check to prevent KeyError
    if not data or 'url' not in data:
        return jsonify({'error': 'Missing URL'}), 400

    try:
        # ATTEMPT QUEUE
        task = process_download.apply_async(args=[data['url'], data.get('format_id', 'best'), data.get('title', 'Video')])
        return jsonify({'task_id': task.id, 'fallback': False})
    
    except Exception as e:
        # FALLBACK MECHANISM: If Redis/Celery is dead, stream directly
        print(f"Queue failed: {e}. Switching to direct stream.")
        ydl_opts = {
            'format': f"{data.get('format_id', 'best')}+bestaudio/best",
            'skip_download': True,
            'quiet': True,
            'proxy': PROXY_URL,
            'extractor_args': {'youtube': {'player_client': ['default', 'web']}}
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(data['url'], download=False)
                return jsonify({'fallback': True, 'direct_url': info.get('url')})
        except Exception as yt_err:
            return jsonify({'error': str(yt_err)}), 500

@app.route('/fetch', methods=['POST'])
def fetch_metadata():
    url = request.json.get('url')
    if not url: return jsonify({'error': 'No URL'}), 400
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'proxy': PROXY_URL}) as ydl:
            info = ydl.extract_info(url, download=False)
            return jsonify({'title': info.get('title'), 'formats': [{'format_id': f['format_id'], 'note': f.get('resolution', 'Audio')} for f in info.get('formats', []) if f.get('vcodec') != 'none']})
    except Exception as e: return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
