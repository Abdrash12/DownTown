import os
import time
from flask import Flask, render_template, request, jsonify, send_file
from celery import Celery
import yt_dlp

app = Flask(__name__, template_folder='templates', static_folder='static')

# ==========================================
# 1. HARDENED CONFIGURATION & REDIS OPTIMIZATION
# ==========================================
REDIS_URL = os.environ.get('REDIS_URL')
PROXY_URL = os.environ.get('PROXY_URL') # Webshare HTTP Proxy

if PROXY_URL:
    print(f"[BOOT] HTTP Proxy active: {PROXY_URL[:15]}****")
else:
    print("[BOOT] WARNING: Running without proxy on datacenter IP!")

app.config['broker_url'] = REDIS_URL
app.config['result_backend'] = REDIS_URL

# --- REDIS MEMORY & I/O OPTIMIZATIONS ---
app.config['result_expires'] = 900  # Auto-delete task results from Redis after 15 mins
app.config['worker_send_task_events'] = False  # Disable heartbeat spam to save Upstash commands
app.config['task_ignore_result'] = False  # Keep enabled only for progress tracking
app.config['broker_connection_retry_on_startup'] = True

celery_app = Celery(app.name, broker=app.config['broker_url'])
celery_app.conf.update(app.config)

DOWNLOAD_DIR = os.path.join(os.getcwd(), 'downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

local_exe = os.path.join(os.getcwd(), 'ffmpeg.exe')
FFMPEG_PATH = local_exe if os.path.exists(local_exe) else 'ffmpeg'


# ==========================================
# 2. CELERY TASK (WITH THROTTLED REDIS WRITES)
# ==========================================
@celery_app.task(bind=True)
def process_download(self, url, format_id, title):
    safe_title = "".join(x for x in title if x.isalnum() or x in " _-").strip()
    output_template = os.path.join(DOWNLOAD_DIR, f"{safe_title}.%(ext)s")

    # Track last update time and percentage to throttle Redis writes
    last_update_time = [0]
    last_reported_percent = [-1]

    def progress_hook(d):
        if d['status'] == 'downloading':
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            percent = int((downloaded / total_bytes) * 100) if total_bytes > 0 else 0
            
            current_time = time.time()
            # THROTTLE RULE: Only write to Redis if percent increased by >= 5% OR 2 seconds passed
            if (percent - last_reported_percent[0] >= 5) or (current_time - last_update_time[0] >= 2.0):
                last_reported_percent[0] = percent
                last_update_time[0] = current_time
                self.update_state(
                    state='PROGRESS', 
                    meta={'percent': percent, 'status': f"DOWNLOADING: {percent}%"}
                )
        elif d['status'] == 'finished':
            self.update_state(state='PROGRESS', meta={'percent': 99, 'status': 'STITCHING STREAMS...'})

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
                'player_client': ['web_embedded', 'android_vr', 'default', 'web']
            }
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = os.path.basename(ydl.prepare_filename(info))
            return {'status': 'Completed', 'filename': filename, 'percent': 100}
    except Exception as e:
        self.update_state(state='FAILURE', meta={'exc_message': str(e)})
        raise Exception(str(e))


# ==========================================
# 3. HTTP ENDPOINTS & TRUE CLIENT DIRECT FALLBACK
# ==========================================
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/fetch', methods=['POST'])
def fetch_metadata():
    data = request.json
    if not data or 'url' not in data:
        return jsonify({'error': 'Please provide a valid YouTube URL!'}), 400

    url = data['url']
    ydl_opts = {
        'skip_download': True,
        'quiet': True,
        'proxy': PROXY_URL,
        'js_runtimes': {'node': {}},
        'extractor_args': {'youtube': {'player_client': ['web_embedded', 'android_vr', 'default', 'web']}}
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = []
            
            for f in info.get('formats', []):
                if f.get('vcodec') == 'none' and f.get('acodec') == 'none':
                    continue
                if 'storyboard' in str(f.get('format_note', '')).lower():
                    continue

                if f.get('url') or f.get('format_id'):
                    ext = f.get('ext', 'mp4')
                    res = f.get('resolution') or f.get('format_note', 'Audio')
                    formats.append({
                        'format_id': f.get('format_id'),
                        'note': f"{ext.upper()} - {res}"
                    })

            return jsonify({
                'title': info.get('title', 'Unknown Title'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': f"{int(info.get('duration', 0)) // 60}m {int(info.get('duration', 0)) % 60}s",
                'formats': formats,
                'original_url': url
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/trigger_download', methods=['POST'])
def trigger_download():
    data = request.json
    if not data or 'url' not in data:
        return jsonify({'error': 'Missing URL parameter!'}), 400

    url = data['url']
    format_id = data.get('format_id', 'best')
    title = data.get('title', 'Video')

    try:
        # ATTEMPT 1: Background Queue via Upstash Redis
        task = process_download.apply_async(args=[url, format_id, title])
        return jsonify({'task_id': task.id, 'fallback': False})
    
    except Exception as e:
        # ATTEMPT 2: TRUE DIRECT CLIENT-SIDE FALLBACK (0% Server Load)
        print(f"[QUEUE OFFLINE] Redis unreachable ({e}). Switching to Direct Client CDN Download.")
        
        # We explicitly request 'best[ext=mp4]' or progressive formats so Google provides a 
        # single URL containing BOTH video and audio that the browser can download directly.
        ydl_opts = {
            'format': 'best[ext=mp4]/bestprogressive/best',
            'skip_download': True,
            'quiet': True,
            'proxy': PROXY_URL,
            'js_runtimes': {'node': {}},
            'extractor_args': {'youtube': {'player_client': ['web_embedded', 'android_vr', 'default']}}
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                direct_cdn_url = info.get('url')
                
                return jsonify({
                    'fallback': True,
                    'direct_url': direct_cdn_url,
                    'status': 'Queue offline. Download initiated directly from YouTube CDN to your PC.'
                })
        except Exception as yt_err:
            return jsonify({'error': f"Queue and Direct Fallback failed: {str(yt_err)}"}), 500


@app.route('/status/<task_id>')
def task_status(task_id):
    task = process_download.AsyncResult(task_id)
    if task.state == 'PENDING':
        return jsonify({'state': task.state, 'percent': 0, 'status': 'IN QUEUE...'})
    elif task.state == 'PROGRESS':
        return jsonify({
            'state': task.state,
            'percent': task.info.get('percent', 0),
            'status': task.info.get('status', 'PROCESSING...')
        })
    elif task.state == 'SUCCESS':
        return jsonify({'state': task.state, 'percent': 100, 'filename': task.info.get('filename')})
    elif task.state == 'FAILURE':
        return jsonify({'state': task.state, 'error': str(task.info)})
    return jsonify({'state': task.state})


@app.route('/download_file/<filename>')
def download_file(filename):
    file_path = os.path.join(DOWNLOAD_DIR, filename)
    return send_file(file_path, as_attachment=True)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
