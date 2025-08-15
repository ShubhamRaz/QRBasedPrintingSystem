# app.py
import os
import sqlite3
import secrets
import time
from datetime import datetime
from io import BytesIO
from flask import Flask, request, redirect, url_for, send_file, render_template, flash, jsonify
import qrcode
from werkzeug.utils import secure_filename
from config import UPLOAD_FOLDER, DB_PATH, ALLOWED_EXTENSIONS, MAX_FILE_SIZE, TOKEN_EXPIRY, SIMULATE_PAYMENT, DEBUG

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
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
    conn.commit()
    conn.close()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def create_job_entry(filename, filepath):
    token = secrets.token_urlsafe(16)
    uploaded_at = int(time.time())
    expires_at = uploaded_at + TOKEN_EXPIRY
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('INSERT INTO jobs (token, filename, filepath, uploaded_at, expires_at) VALUES (?,?,?,?,?)',
                (token, filename, filepath, uploaded_at, expires_at))
    conn.commit()
    conn.close()
    return token

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        f = request.files['file']
        if f.filename == '':
            flash('No selected file')
            return redirect(request.url)
        if f and allowed_file(f.filename):
            filename = secure_filename(f.filename)
            ts = int(time.time())
            stored_name = f"{ts}_{secrets.token_hex(8)}_{filename}"
            path = os.path.join(UPLOAD_FOLDER, stored_name)
            f.save(path)
            token = create_job_entry(filename, path)
            # If SIMULATE_PAYMENT: mark paid immediately (for testing)
            if SIMULATE_PAYMENT:
                mark_paid(token)
            # Generate QR linking to token
            qr = qrcode.QRCode(box_size=6, border=2)
            qr.add_data(token)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = BytesIO()
            img.save(buf, format='PNG')
            buf.seek(0)
            return send_file(buf, mimetype='image/png', as_attachment=False, download_name=f"{token}.png")
        else:
            flash('Invalid file type')
            return redirect(request.url)
    return render_template('index.html')

def mark_paid(token):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('UPDATE jobs SET paid=1 WHERE token=?', (token,))
    conn.commit()
    conn.close()

@app.route('/simulate_pay/<token>', methods=['POST'])
def simulate_pay(token):
    # This endpoint simulates a payment gateway callback
    # In production, you would verify webhook signatures and wallet status
    mark_paid(token)
    return jsonify({"status": "ok", "token": token})

@app.route('/admin')
def admin():
    conn = sqlite3.connect(DB_PATH)
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

@app.route('/file_by_token/<token>', methods=['GET'])
def file_by_token(token):
    # Return file path if token exists, paid and not expired
    conn = sqlite3.connect(DB_PATH)
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
    # send path only (scanner/worker will print)
    return jsonify({"filepath": filepath})

@app.route('/mark_printed/<token>', methods=['POST'])
def mark_printed(token):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('UPDATE jobs SET printed=1 WHERE token=?', (token,))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=DEBUG, use_reloader=False)
