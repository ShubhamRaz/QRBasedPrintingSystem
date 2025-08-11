# scanner_print.py
import time
import requests
import cv2
from pyzbar import pyzbar
from config import CAMERA_DEVICE_INDEX, DB_PATH, PRINTER_NAME
import subprocess
import sqlite3

# URL of Flask server on the Pi itself
FLASK_BASE = "http://localhost:5000"

def fetch_job_and_print(token):
    try:
        r = requests.get(f"{FLASK_BASE}/file_by_token/{token}", timeout=5)
    except Exception as e:
        print("Error contacting server:", e)
        return False
    if r.status_code != 200:
        print("Server rejected token:", r.status_code, r.text)
        return False
    j = r.json()
    filepath = j.get("filepath")
    if not filepath:
        print("Invalid response, no filepath")
        return False
    # Print via CUPS (lp)
    try:
        if PRINTER_NAME:
            cmd = ["lp", "-d", PRINTER_NAME, filepath]
        else:
            cmd = ["lp", filepath]
        print("Running:", " ".join(cmd))
        subprocess.run(cmd, check=True)
        # mark printed
        requests.post(f"{FLASK_BASE}/mark_printed/{token}", timeout=2)
        print("Printed and marked")
        return True
    except subprocess.CalledProcessError as e:
        print("Print failed:", e)
        return False

def scan_loop():
    print("Starting camera scan on device", CAMERA_DEVICE_INDEX)
    cap = cv2.VideoCapture(CAMERA_DEVICE_INDEX)
    if not cap.isOpened():
        print("Cannot open camera. Check camera index or permissions.")
        return
    last_seen = None
    cooldown = 3  # seconds between processing same token
    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.1)
            continue
        barcodes = pyzbar.decode(frame)
        for b in barcodes:
            token = b.data.decode('utf-8').strip()
            now = time.time()
            if token == last_seen and (now - last_seen_time) < cooldown:
                continue
            print("Detected token:", token)
            ok = fetch_job_and_print(token)
            if ok:
                last_seen = token
                last_seen_time = now
            else:
                print("Job not printed (reason logged)")
        # small delay
        time.sleep(0.1)

if __name__ == '__main__':
    last_seen = None
    last_seen_time = 0
    scan_loop()
