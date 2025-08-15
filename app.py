# app.py
import os
import sqlite3
import secrets
import time
from datetime import datetime
from io import BytesIO
from functools import wraps

from flask import (
    Flask, request, redirect, url_for, send_file, render_template, flash,
    jsonify, session, abort
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

import qrcode

# import project config (expected in same folder)
from config import (
    BASE_DIR, UPLOAD_FOLDER, DB_PATH, DEBUG, TOKEN_EXPIRY,
    CAMERA_DEVICE_INDEX, PRINTER_NAME, ALLOWED_EXTENSIONS, MAX_FILE_SIZE, SIMULATE_PAYMENT
)

# ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)

@app.context_processor
def inject_template_globals():
    # value in MB, integer
    max_mb = app.config.get('MAX_CONTENT_LENGTH', 0) // (1024 * 1024)
    return {
        "max_file_mb": max_mb,
        "registration_enabled": 'register' in app.view_functions
    }

# session secret - use env var in production
app.secret_key = os.environ.get("SMARTQR_SECRET") or secrets.token_hex(24)
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# ---------------------
# Database helpers
# ---------------------
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Create jobs and users tables if they do not exist. Add owner_username if missing."""
    conn = get_db_connection()
    cur = conn.cursor()
    # jobs table (base schema)
    cur.execute('''
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token TEXT UNIQUE,
        filename TEXT,
        filepath TEXT,
        uploaded_at INTEGER,
        paid INTEGER DEFAULT 0,
        printed INTEGER DEFAULT 0,
        expires_at INTEGER
    )
    ''')
    # users table
    cur.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0
    )
    ''')
    conn.commit()

    # Safe migration: add owner_username column if not present
    cur.execute("PRAGMA table_info(jobs)")
    existing_cols = [row[1] for row in cur.fetchall()]
    if 'owner_username' not in existing_cols:
        try:
            cur.execute("ALTER TABLE jobs ADD COLUMN owner_username TEXT")
            conn.commit()
            app.logger.info("DB migration: added owner_username column to jobs table")
        except Exception as e:
            app.logger.exception("Failed to add owner_username column: %s", e)

    conn.close()


# initialize DB at import/run time
init_db()

# ---------------------
# Utility functions
# ---------------------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def create_job_entry(filename, filepath, owner=None):
    token = secrets.token_urlsafe(16)
    uploaded_at = int(time.time())
    expires_at = uploaded_at + TOKEN_EXPIRY
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO jobs (token, filename, filepath, uploaded_at, expires_at, owner_username) VALUES (?,?,?,?,?,?)',
        (token, filename, filepath, uploaded_at, expires_at, owner)
    )
    conn.commit()
    conn.close()
    return token


def mark_paid(token):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('UPDATE jobs SET paid=1 WHERE token=?', (token,))
    conn.commit()
    conn.close()

def mark_printed_db(token):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('UPDATE jobs SET printed=1 WHERE token=?', (token,))
    conn.commit()
    conn.close()

# ---------------------
# Auth utilities
# ---------------------
# ---------------------
# Auth utilities
# ---------------------
def login_required(admin_only=False):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            username = session.get("user")
            if not username:
                # send admin-protected pages to admin login, others to user login
                if admin_only:
                    return redirect(url_for("admin_login", next=request.path))
                return redirect(url_for("user_login", next=request.path))

            # if admin_only, prefer session flag but fallback to DB check
            if admin_only:
                if session.get('is_admin') is None:
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute("SELECT is_admin FROM users WHERE username=?", (username,))
                    row = cur.fetchone()
                    conn.close()
                    session['is_admin'] = bool(row[0]) if row else False

                if not session.get('is_admin'):
                    abort(403)

            return f(*args, **kwargs)
        return wrapped
    return decorator

# ---------------------
# Routes
# ---------------------
@app.route('/', methods=['GET', 'POST'])
def index():
    # POST: handle upload (requires logged-in user)
    if request.method == 'POST':
        username = session.get('user')
        if not username:
            flash("Please log in to upload files.", "error")
            return redirect(url_for('user_login', next=request.path))

        if 'file' not in request.files:
            flash("No file selected.", "error")
            return redirect(request.url)

        uploaded_file = request.files['file']
        if uploaded_file.filename == '':
            flash("No file selected.", "error")
            return redirect(request.url)

        if not allowed_file(uploaded_file.filename):
            flash("Invalid file type. Allowed: " + ", ".join(sorted(ALLOWED_EXTENSIONS)), "error")
            return redirect(request.url)

        # prepare storage path
        filename = secure_filename(uploaded_file.filename)
        ts = int(time.time())
        stored_name = f"{ts}_{secrets.token_hex(8)}_{filename}"
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        path = os.path.join(UPLOAD_FOLDER, stored_name)

        try:
            uploaded_file.save(path)
            app.logger.info("Saved upload to %s by user %s", path, username)
        except Exception as e:
            app.logger.exception("Failed to save uploaded file")
            flash("Server error saving file.", "error")
            return redirect(request.url)

        # create DB entry and attach owner
        try:
            token = create_job_entry(filename, path, owner=username)
            app.logger.info("Created job token %s (owner=%s)", token, username)
        except Exception as e:
            app.logger.exception("Failed to create job record")
            try:
                os.remove(path)
            except Exception:
                pass
            flash("Server error creating job.", "error")
            return redirect(request.url)

        # optional: mark paid automatically for testing
        if SIMULATE_PAYMENT:
            try:
                mark_paid(token)
            except Exception:
                app.logger.exception("Failed to auto-mark paid")

        # generate QR and return it (with token header for convenience)
        qr = qrcode.QRCode(box_size=6, border=2)
        qr.add_data(token)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        resp = send_file(buf, mimetype='image/png', as_attachment=False, download_name=f"{token}.png")
        resp.headers['X-Job-Token'] = token
        return resp

    # GET: render upload page and tell template if registration route exists
    registration_enabled = 'register' in app.view_functions
    return render_template('index.html', registration_enabled=registration_enabled)

@app.route('/admin')
@login_required(admin_only=True)
def admin():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT id, token, filename, uploaded_at, paid, printed, expires_at FROM jobs ORDER BY uploaded_at DESC')
    rows = cur.fetchall()
    conn.close()
    formatted = []
    for r in rows:
        formatted.append({
            'id': r[0],
            'token': r[1],
            'filename': r[2],
            'uploaded_at': datetime.fromtimestamp(r[3]).strftime("%Y-%m-%d %H:%M:%S"),
            'paid': bool(r[4]),
            'printed': bool(r[5]),
            'expires_at': datetime.fromtimestamp(r[6]).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return render_template('admin.html', jobs=formatted)

@app.route('/admin/add_user', methods=['GET', 'POST'])
@login_required(admin_only=True)
def admin_add_user():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        is_admin = 1 if request.form.get('is_admin') == 'on' else 0
        if not username or not password:
            flash("Username and password required", "error")
            return redirect(url_for('admin_add_user'))
        hashed = generate_password_hash(password)
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO users (username, password, is_admin) VALUES (?, ?, ?)",
                        (username, hashed, is_admin))
            conn.commit()
            conn.close()
            flash("User created: " + username, "success")
            return redirect(url_for('admin'))
        except sqlite3.IntegrityError:
            flash("Username already exists", "error")
            return redirect(url_for('admin_add_user'))
        except Exception as e:
            flash("Error creating user: " + str(e), "error")
            return redirect(url_for('admin_add_user'))
    return render_template('add_user.html')

@app.route('/login', methods=['GET', 'POST'])
def user_login():
    """
    Regular user login page. Defaults to redirect to /myjobs after login.
    """
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        next_param = request.form.get('next') or request.args.get('next') or ''

        if not username or not password:
            flash("Missing username or password", "error")
            return redirect(url_for('user_login', next=next_param))

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT password, is_admin FROM users WHERE username=?", (username,))
        row = cur.fetchone()
        conn.close()

        if not row:
            flash("Invalid username or password", "error")
            return redirect(url_for('user_login', next=next_param))

        stored_hash, is_admin_flag = row[0], bool(row[1])

        if check_password_hash(stored_hash, password):
            session['user'] = username
            session['is_admin'] = is_admin_flag

            # Don't send regular users to /admin even if next_param was set
            if next_param and (not next_param.startswith('/admin') or is_admin_flag):
                return redirect(next_param)
            # default landing for regular login: myjobs (admins will land on admin)
            return redirect(url_for('admin' if is_admin_flag else 'myjobs'))
        else:
            flash("Invalid username or password", "error")
            return redirect(url_for('user_login', next=next_param))

    # GET
    return render_template('login.html')  # user login template


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """
    Admin-only login page. Only accounts with is_admin == 1 may log in here.
    """
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        next_param = request.form.get('next') or request.args.get('next') or ''

        if not username or not password:
            flash("Missing username or password", "error")
            return redirect(url_for('admin_login', next=next_param))

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT password, is_admin FROM users WHERE username=?", (username,))
        row = cur.fetchone()
        conn.close()

        if not row:
            flash("Invalid username or password", "error")
            return redirect(url_for('admin_login', next=next_param))

        stored_hash, is_admin_flag = row[0], bool(row[1])

        if not is_admin_flag:
            flash("This account does not have admin access.", "error")
            return redirect(url_for('admin_login'))

        if check_password_hash(stored_hash, password):
            session['user'] = username
            session['is_admin'] = True
            # If next_param provided and it's inside /admin, redirect there, else default admin dashboard
            if next_param and next_param.startswith('/admin'):
                return redirect(next_param)
            return redirect(url_for('admin'))
        else:
            flash("Invalid username or password", "error")
            return redirect(url_for('admin_login', next=next_param))

    # GET
    return render_template('admin_login.html')  # separate admin template


@app.route('/logout')
def logout():
    session.pop('user', None)
    session.pop('is_admin', None)
    return redirect(url_for('index'))


# API endpoints for scanner/worker
@app.route('/file_by_token/<token>', methods=['GET'])
def file_by_token(token):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT filepath, paid, printed, expires_at FROM jobs WHERE token=?', (token,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "token_not_found"}), 404
    filepath, paid, printed, expires_at = row
    now = int(time.time())
    if now > expires_at:
        return jsonify({"error": "token_expired"}), 403
    if not paid:
        return jsonify({"error": "not_paid"}), 402
    if printed:
        return jsonify({"error": "already_printed"}), 409
    return jsonify({"filepath": filepath})

@app.route('/mark_printed/<token>', methods=['POST'])
def mark_printed(token):
    try:
        mark_printed_db(token)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/simulate_pay/<token>', methods=['POST'])
def simulate_pay(token):
    # use for testing payment webhooks or manual mark paid
    try:
        mark_paid(token)
        return jsonify({"status": "ok", "token": token})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# health check
@app.route('/health')
def health():
    return "ok"

# My jobs page for logged-in users
@app.route('/myjobs')
@login_required(admin_only=False)
def myjobs():
    username = session.get('user')
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        'SELECT id, token, filename, uploaded_at, paid, printed, expires_at FROM jobs WHERE owner_username=? ORDER BY uploaded_at DESC',
        (username,)
    )
    rows = cur.fetchall()
    conn.close()
    formatted = []
    for r in rows:
        formatted.append({
            'id': r[0],
            'token': r[1],
            'filename': r[2],
            'uploaded_at': datetime.fromtimestamp(r[3]).strftime("%Y-%m-%d %H:%M:%S"),
            'paid': bool(r[4]),
            'printed': bool(r[5]),
            'expires_at': datetime.fromtimestamp(r[6]).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return render_template('myjobs.html', jobs=formatted)

# Registration route for new users

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        if not username or not password:
            flash("Username and password required", "error")
            return redirect(url_for('register'))
        hashed = generate_password_hash(password)
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO users (username, password, is_admin) VALUES (?, ?, ?)",
                        (username, hashed, 0))
            conn.commit()
            conn.close()
            flash("Account created. Please log in.", "success")
            return redirect(url_for('user_login'))

        except sqlite3.IntegrityError:
            flash("Username already exists", "error")
            return redirect(url_for('register'))
    return render_template('register.html')

# ---------------------
# Run app
# ---------------------
if __name__ == '__main__':
    # ensure upload dir exists (already made above but double-check)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    init_db()
    # run without reloader to avoid double-process DB confusion
    app.run(host='0.0.0.0', port=5000, debug=DEBUG, use_reloader=False)
