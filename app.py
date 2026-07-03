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
PROXY_URL = os.environ.get('PROXY_URL')  # Format: http://username:password@ip:port

if PROXY_URL:
    print(f"[BOOT] HTTP Proxy active: {PROXY_URL[:15]}****")
else:
    print("[BOOT] WARNING: Running without proxy on datacenter IP!")

app.config['broker_url'] = REDIS_URL
app.config['result_backend'] = REDIS_URL

# --- REDIS OPTIMIZATIONS TO MINIMIZE OVERHEAD & COMMAND LIMITS ---
app.config['result_expires'] = 900  # Automatically delete task results from Redis after 15 mins
app.config['worker_send_task_events'] = False  # Disable heartbeat monitoring spam to save Upstash commands
app.config['task_ignore_result'] = False  # Maintained for explicit state checks
app.config['broker_connection_retry_on_startup'] = True

celery_app = Celery(app.name, broker=app.config['broker_url'])
celery_app.conf.update(app.config)

DOWNLOAD_DIR = os.path.join(os.getcwd(), 'downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Detect FFmpeg location (Local Windows sandbox vs Render Linux environment)
local_exe = os.path.join(os.getcwd(), 'ffmpeg.exe')
FFMPEG_PATH = local_exe if os.path.exists(local_exe) else 'ffmpeg'


# ==========================================
# 2. CELERY BACKGROUND TASK WORKER
# ==========================================
@celery_app.task(bind=True)
def process_download(self, url, format_id, title):
    safe_title = "".join(x for x in title if x.isalnum() or x in " _-").strip()
    output_template = os.path.join(DOWNLOAD_DIR, f"{safe_title}.%(ext)s")

    # Tracking states internally to throttle Redis write frequencies
    last_update_time = [0]
    last_reported_percent = [-1]

    def progress_hook(d):
        if d['status'] == 'downloading':
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            
            # Calculate MB downloaded for chunked streams where total size is hidden by CDN
            mb_downloaded = round(downloaded / (1024 * 1024), 1)
            
            if total_bytes > 0:
                percent = int((downloaded / total_bytes) * 100)
                status_text = f"DOWNLOADING: {percent}% ({mb_downloaded} MB)"
            else:
                # If YouTube hides total bytes, report progressive MB instead of stalling at 0%
                percent = -1  # Special flag for frontend to show an indeterminate spinner
                status_text = f"DOWNLOADING: {mb_downloaded} MB received..."
            
            current_time = time.time()
            # THROTTLING PROTOCOL: Limits database I/O to every 3.0 seconds minimum or on completion
            if (current_time - last_update_time[0] >= 3.0) or (percent == 100):
                last_reported_percent[0] = percent
                last_update_time[0] = current_time
                self.update_state(
                    state='PROGRESS', 
                    meta={'percent': percent, 'status': status_text}
                )
        elif d['status'] == 'finished':
            self.update_state(state='PROGRESS', meta={'percent': 99, 'status': 'STITCHING AUDIO/VIDEO...'})

    ydl_opts = {
        'format': f"{format_id}+bestaudio/{format_id}/bestvideo+bestaudio/best",
        'outtmpl': output_template,
        'merge_output_format': 'mp4',
        'quiet': True,
        'ffmpeg_location': FFMPEG_PATH,
        'proxy': PROXY_URL,
        'socket_timeout': 15,  # Drops hanging proxy connections after 15 seconds
        'js_runtimes': {'deno': {}, 'node': {}},  # Uses Deno/Node to solve signature challenges
        'progress_hooks': [progress_hook],
        'extractor_args': {
            'youtube': {
                # GitHub official recommended client cascade to circumvent datacenter bot detection blocks
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
# 3. HTTP ENDPOINTS & FAILSAFE ROUTING
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
        'socket_timeout': 15,
        'js_runtimes': {'deno': {}, 'node': {}},
        'extractor_args': {
            'youtube': {
                'player_client': ['web_embedded', 'android_vr', 'default', 'web']
            }
        }
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
        # ATTEMPT 1: Primary Task Delegation via Upstash Redis Instance
        task = process_download.apply_async(args=[url, format_id, title])
        return jsonify({'task_id': task.id, 'fallback': False})
    
    except Exception as e:
        # ATTEMPT 2: EFFICIENT CLIENT-SIDE CDN FALLBACK (0% Server Storage, 0% Server Bandwidth)
        print(f"[QUEUE OFFLINE] Redis unreachable ({e}). Switching to Direct Browser CDN Streaming.")
        
        # Requests pre-merged progressive streams (audio+video together) so the client's PC 
        # downloads straight from Google's delivery nodes without using server disk or memory.
        ydl_opts = {
            'format': 'best[ext=mp4]/bestprogressive/best',
            'skip_download': True,
            'quiet': True,
            'proxy': PROXY_URL,
            'socket_timeout': 15,
            'js_runtimes': {'deno': {}, 'node': {}},
            'extractor_args': {
                'youtube': {
                    'player_client': ['web_embedded', 'android_vr', 'default']
                }
            }
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                direct_cdn_url = info.get('url')
                
                return jsonify({
                    'fallback': True,
                    'direct_url': direct_cdn_url,
                    'status': 'Queue down. Redirecting connection straight to global CDN.'
                })
        except Exception as yt_err:
            return jsonify({'error': f"Queue and Client CDN Fallback both failed: {str(yt_err)}"}), 500


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
