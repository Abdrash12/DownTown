import os
import json
from flask import Flask, render_template, request, jsonify, send_file
from celery import Celery
import yt_dlp

app = Flask(__name__)

# ==========================================
# 1. DATABASE & CONFIGURATION
# ==========================================
# Ensure you are using the 'rediss' protocol for Upstash
REDIS_URL = os.environ.get('REDIS_URL', 'redis://default:gQAAAAAAAWV9AAIgcDE5YTlkZTI5NzJhODA0ZmE0YTVhYWRmNjRkYWY2NjQ1OQ@daring-gopher-91517.upstash.io:6379?ssl_cert_reqs=CERT_NONE')
celery_app = Celery(app.name, broker=REDIS_URL, backend=REDIS_URL)

app.config['broker_url'] = REDIS_URL
app.config['result_backend'] = REDIS_URL

celery_app = Celery(app.name, broker=app.config['broker_url'])
celery_app.conf.update(app.config)

DOWNLOAD_DIR = os.path.join(os.getcwd(), 'downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

FFMPEG_PATH = 'ffmpeg'
PROXY_URL = os.environ.get('PROXY_URL')

# ==========================================
# 2. BACKGROUND CONCURRENT TASK WORKER
# ==========================================
@celery_app.task(bind=True)
def process_download(self, url, format_id, title):
    safe_title = "".join(x for x in title if x.isalnum() or x in " _-").strip()
    output_template = os.path.join(DOWNLOAD_DIR, f"{safe_title}.%(ext)s")

    def progress_hook(d):
        if d['status'] == 'downloading':
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded_bytes = d.get('downloaded_bytes', 0)
            percentage = int((downloaded_bytes / total_bytes) * 100) if total_bytes > 0 else 0
            self.update_state(state='PROGRESS', meta={'percent': percentage, 'status': f"DOWNLOADING: {percentage}%"})

    ydl_opts = {
        'format': f"{format_id}+bestaudio/{format_id}/bestvideo+bestaudio/best",
        'outtmpl': output_template,
        'merge_output_format': 'mp4',
        'quiet': True,
        'ffmpeg_location': FFMPEG_PATH,
        'proxy': PROXY_URL,
        'js_runtimes': {'node': {}},
        'progress_hooks': [progress_hook],
        'extractor_args': {
            'youtube': {
                # This configuration balances bot bypass with DRM avoidance
                'player_client': ['default', 'web', 'android', 'ios']
            }
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if not filename.endswith('.mp4'):
                filename = filename.rsplit('.', 1)[0] + '.mp4'
            return {'status': 'Completed', 'filename': os.path.basename(filename), 'percent': 100}
    except Exception as e:
        self.update_state(state='FAILURE', meta={'exc_message': str(e)})
        raise Exception(str(e))

# ==========================================
# 3. HTTP CONTROLLERS & ENDPOINTS
# ==========================================
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/fetch', methods=['POST'])
def fetch_metadata():
    url = request.json.get('url')
    if not url: return jsonify({'error': 'No URL provided'}), 400

    ydl_opts = {
        'skip_download': True,
        'quiet': True,
        'proxy': PROXY_URL,
        'js_runtimes': {'node': {}},
        'extractor_args': {'youtube': {'player_client': ['default', 'web', 'android', 'ios']}}
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = [{'format_id': f.get('format_id'), 'note': f"{f.get('ext', 'mp4').upper()} - {f.get('resolution', 'Audio')}"} 
                       for f in info.get('formats', []) if f.get('vcodec') != 'none']
            return jsonify({'title': info.get('title'), 'thumbnail': info.get('thumbnail'), 'formats': formats})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/trigger_download', methods=['POST'])
def trigger_download():
    data = request.json
    task = process_download.apply_async(args=[data['url'], data['format_id'], data['title']])
    return jsonify({'task_id': task.id})

@app.route('/status/<task_id>')
def task_status(task_id):
    task = process_download.AsyncResult(task_id)
    return jsonify({'state': task.state, 'percent': task.info.get('percent') if isinstance(task.info, dict) else 0})

@app.route('/download_file/<filename>')
def download_file(filename):
    return send_file(os.path.join(DOWNLOAD_DIR, filename), as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
