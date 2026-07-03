import os
import sys
from flask import Flask, render_template, request, jsonify, send_file
from celery import Celery
import yt_dlp

app = Flask(__name__)

# ==========================================
# 1. DATABASE & WORKER CONFIGURATION
# ==========================================
# REPLACE THIS URL with your Upstash Redis URL!
# (Keep the ?ssl_cert_reqs=CERT_NONE at the very end to prevent cloud SSL handshake crashes)# Grabs the REDIS_URL from Render's environment variables, or falls back to local if missing
REDIS_URL = os.environ.get('REDIS_URL', 'rediss://default:YOUR_PASSWORD@YOUR_REGION.upstash.io:6379?ssl_cert_reqs=CERT_NONE')

app.config['CELERY_BROKER_URL'] = REDIS_URL
app.config['CELERY_RESULT_BACKEND'] = REDIS_URL

# Initialize Celery Worker Queue
celery_app = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery_app.conf.update(app.config)

# Ensure a safe local directory exists to store the stitched MP4 files
DOWNLOAD_DIR = os.path.join(os.getcwd(), 'downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Helper: Detect if we are running locally on Windows or on a Linux Cloud Container (Render)
local_exe = os.path.join(os.getcwd(), 'ffmpeg.exe')
FFMPEG_PATH = local_exe if os.path.exists(local_exe) else 'ffmpeg'


# ==========================================
# 2. CELERY BACKGROUND WORKER TASK
# ==========================================
@celery_app.task(bind=True)
def process_download(self, url, format_id, title):
    # Sanitize title to prevent OS filesystem crashes from emojis or weird punctuation
    safe_title = "".join(x for x in title if x.isalnum() or x in " _-").strip()
    output_template = os.path.join(DOWNLOAD_DIR, f"{safe_title}.%(ext)s")

    # Real-time sensor: Pushes percentage and speed metrics into Redis during download
    def progress_hook(d):
        if d['status'] == 'downloading':
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded_bytes = d.get('downloaded_bytes', 0)
            
            percentage = int((downloaded_bytes / total_bytes) * 100) if total_bytes > 0 else 0
            speed = d.get('_speed_str', 'N/A')
            eta = d.get('_eta_str', '0s')
            
            # Broadcast state to Redis so Flask's status route can read it live
            self.update_state(
                state='PROGRESS',
                meta={
                    'percent': percentage,
                    'speed': speed,
                    'eta': eta,
                    'status': f"DOWNLOADING: {percentage}% ({speed})"
                }
            )
        elif d['status'] == 'finished':
            self.update_state(
                state='PROGRESS',
                meta={'percent': 99, 'status': 'MERGING VIDEO & AUDIO STREAMS...'}
            )

    ydl_opts = {
        'format': format_id,
        'outtmpl': output_template,
        'merge_output_format': 'mp4',
        'quiet': True,
        'ffmpeg_location': FFMPEG_PATH,
        # Allow yt-dlp to natively scan for external JS engines (Deno/Node/QuickJS) to bypass YouTube signature locks
        'js_runtimes': {'deno': {}, 'node': {}, 'quickjs': {}},
        'progress_hooks': [progress_hook]
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            # Determine final filename after FFmpeg stitching
            filename = ydl.prepare_filename(info)
            if not filename.endswith('.mp4'):
                filename = filename.rsplit('.', 1)[0] + '.mp4'
            
            base_name = os.path.basename(filename)
            return {'status': 'Completed', 'filename': base_name, 'percent': 100}
            
    except Exception as e:
        self.update_state(state='FAILURE', meta={'exc_message': str(e)})
        raise Exception(str(e))


# ==========================================
# 3. FLASK WEB ROUTES
# ==========================================
@app.route('/')
def home():
    # Renders the comic-style interface
    return render_template('index.html')


@app.route('/fetch', methods=['POST'])
def fetch_metadata():
    # Extracts title, thumbnail, and format options without downloading the file
    url = request.json.get('url')
    if not url:
        return jsonify({'error': 'Please provide a valid URL!'}), 400

    ydl_opts = {
        'skip_download': True,
        'quiet': True,
        'ffmpeg_location': FFMPEG_PATH,
        'js_runtimes': {'deno': {}, 'node': {}, 'quickjs': {}}
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            formats = []
            for f in info.get('formats', []):
                if f.get('url'):
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
    # Attempts asynchronous background queueing; drops to high-speed CDN fallback if Redis is full
    data = request.json
    
    try:
        # PRIMARY PATH: Push download task to Upstash Redis & Celery
        task = process_download.apply_async(args=[data['url'], data['format_id'], data['title']])
        return jsonify({'task_id': task.id, 'fallback': False})
        
    except Exception as redis_error:
        # AUTOMATIC FALLBACK PATH: Triggers if Upstash daily read/write limits or storage caps are hit
        print(f"[WARNING] Redis queue unavailable ({redis_error}). Shifting to direct CDN hand-off fallback.")
        
        ydl_opts = {
            'format': data['format_id'],
            'skip_download': True,
            'quiet': True,
            'js_runtimes': {'deno': {}, 'node': {}, 'quickjs': {}}
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(data['url'], download=False)
                direct_url = info.get('url')
                return jsonify({
                    'fallback': True,
                    'direct_url': direct_url,
                    'status': 'Redis capacity reached. Redirecting to direct browser stream.'
                })
        except Exception as yt_err:
            return jsonify({'error': f"Fallback extraction failed: {str(yt_err)}"}), 500


@app.route('/status/<task_id>')
def task_status(task_id):
    # Single, unified telemetry route polled by the frontend progress bar
    task = process_download.AsyncResult(task_id)
    
    if task.state == 'PENDING':
        return jsonify({'state': task.state, 'percent': 0, 'status': 'IN QUEUE...'})
    elif task.state == 'PROGRESS':
        return jsonify({
            'state': task.state,
            'percent': task.info.get('percent', 0),
            'status': task.info.get('status', 'PROCESSING...'),
            'speed': task.info.get('speed', ''),
            'eta': task.info.get('eta', '')
        })
    elif task.state == 'SUCCESS':
        return jsonify({'state': task.state, 'percent': 100, 'filename': task.info.get('filename')})
    elif task.state == 'FAILURE':
        return jsonify({'state': task.state, 'error': str(task.info)})
        
    return jsonify({'state': task.state})


@app.route('/download_file/<filename>')
def download_file(filename):
    # Safely serves the finished MP4 video file from the server's downloads folder to the browser
    file_path = os.path.join(DOWNLOAD_DIR, filename)
    return send_file(file_path, as_attachment=True)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
