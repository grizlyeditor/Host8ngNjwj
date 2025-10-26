from flask import Flask, request, jsonify, send_from_directory, render_template
import os, subprocess, json, firebase_admin
from firebase_admin import credentials, auth
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

# Load environment variables
SERVICE_ACCOUNT = os.getenv('SERVICE_ACCOUNT')
DB_PATH = os.getenv('DB_PATH', 'db.json')

# ✅ Safe upload folder (cross-platform)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, 'uploads')

# Make sure upload & DB folders exist
os.makedirs(UPLOAD_DIR, exist_ok=True)
if not os.path.exists(DB_PATH):
    with open(DB_PATH, 'w') as f:
        f.write('{}')

# ✅ Initialize Firebase Admin
if not firebase_admin._apps:
    cred = credentials.Certificate(SERVICE_ACCOUNT)
    firebase_admin.initialize_app(cred)

app = Flask(__name__, static_folder='static', template_folder='templates')

# Load / Save local DB
def load_db():
    with open(DB_PATH, 'r') as f:
        return json.load(f)

def save_db(data):
    with open(DB_PATH, 'w') as f:
        json.dump(data, f, indent=4)

# ✅ Decorator to verify Firebase token
def firebase_auth_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        id_token = None
        auth_header = request.headers.get('Authorization', None)
        if auth_header and auth_header.startswith('Bearer '):
            id_token = auth_header.split('Bearer ')[1]
        else:
            id_token = request.form.get('idToken') or request.args.get('idToken')

        if not id_token:
            return jsonify({'error': 'no id token provided'}), 401
        try:
            decoded = auth.verify_id_token(id_token)
            request.user = decoded
        except Exception as e:
            return jsonify({'error': 'invalid token', 'detail': str(e)}), 401
        return f(*args, **kwargs)
    return decorated

@app.route('/')
def index():
    return render_template('index.html')

# ✅ Upload user bot file
@app.route('/api/upload', methods=['POST'])
@firebase_auth_required
def upload_bot():
    uid = request.user['uid']
    file = request.files.get('file')
    if not file or not file.filename.endswith('.py'):
        return jsonify({'error': 'invalid file'}), 400
    user_dir = os.path.join(UPLOAD_DIR, uid)
    os.makedirs(user_dir, exist_ok=True)
    save_path = os.path.join(user_dir, file.filename)
    file.save(save_path)
    return jsonify({'status': 'uploaded', 'path': save_path})

# ✅ List uploaded files
@app.route('/api/files', methods=['GET'])
@firebase_auth_required
def list_files():
    uid = request.user['uid']
    user_dir = os.path.join(UPLOAD_DIR, uid)
    files = []
    if os.path.exists(user_dir):
        for fname in os.listdir(user_dir):
            p = os.path.join(user_dir, fname)
            files.append({
                'name': fname,
                'path': f'/userfiles/{uid}/{fname}',
                'size': os.path.getsize(p),
                'mtime': os.path.getmtime(p)
            })
    return jsonify({'files': files})

# ✅ Serve user file (owner only)
@app.route('/userfiles/<uid>/<filename>')
@firebase_auth_required
def serve_user_file(uid, filename):
    if request.user['uid'] != uid:
        return jsonify({'error': 'forbidden'}), 403
    user_dir = os.path.join(UPLOAD_DIR, uid)
    return send_from_directory(user_dir, filename, as_attachment=False)

# ✅ Start bot
@app.route('/api/start', methods=['POST'])
@firebase_auth_required
def start_bot():
    uid = request.user['uid']
    filename = request.form.get('filename')
    if not filename:
        return jsonify({'error': 'filename required'}), 400
    file_path = os.path.join(UPLOAD_DIR, uid, filename)
    if not os.path.exists(file_path):
        return jsonify({'error': 'file not found'}), 404

    db = load_db()
    if db.get('running', {}).get(uid):
        return jsonify({'error': 'already running'}), 400

    proc = subprocess.Popen(['python', file_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    running = db.get('running', {})
    running[uid] = {'pid': proc.pid, 'filename': filename}
    db['running'] = running
    save_db(db)
    return jsonify({'status': 'started', 'pid': proc.pid})

# ✅ Stop bot
@app.route('/api/stop', methods=['POST'])
@firebase_auth_required
def stop_bot():
    uid = request.user['uid']
    db = load_db()
    running = db.get('running', {})
    info = running.get(uid)
    if not info:
        return jsonify({'error': 'not running'}), 400
    pid = info.get('pid')
    try:
        os.kill(pid, 9)
    except Exception:
        pass
    running.pop(uid, None)
    db['running'] = running
    save_db(db)
    return jsonify({'status': 'stopped'})

# ✅ Bot status
@app.route('/api/status', methods=['GET'])
@firebase_auth_required
def status_bot():
    uid = request.user['uid']
    db = load_db()
    running = db.get('running', {})
    info = running.get(uid)
    if info:
        return jsonify({'status': 'running', 'pid': info.get('pid'), 'filename': info.get('filename')})
    return jsonify({'status': 'stopped'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
