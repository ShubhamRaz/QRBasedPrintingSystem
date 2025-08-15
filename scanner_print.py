# scanner_print.py
import time
import requests
import cv2
from pyzbar import pyzbar
from config import CAMERA_DEVICE_INDEX, PRINTER_NAME
import subprocess

# URL of the Flask server running on the same machine
FLASK_BASE = "http://localhost:5000"

# keep track of last seen token to avoid duplicate processing
last_seen = None
last_seen_time = 0

def fetch_job_and_print(token):
    """
    Ask Flask for the job filepath (by token), then print it using lp.
    Returns True on success, False otherwise.
    """
    try:
        r = requests.get(f"{FLASK_BASE}/file_by_token/{token}", timeout=5)
    except Exception as e:
        print("[ERROR] Could not contact server:", e)
        return False

    if r.status_code != 200:
        print(f"[INFO] Server rejected token {token}: {r.status_code} {r.text}")
        return False

    data = r.json()
    filepath = data.get("filepath")
    if not filepath:
        print("[ERROR] No filepath returned by server")
        return False

    # Print via CUPS (lp). If PRINTER_NAME is set, use it.
    try:
        if PRINTER_NAME:
            cmd = ["lp", "-d", PRINTER_NAME, filepath]
        else:
            cmd = ["lp", filepath]
        print("[INFO] Printing:", " ".join(cmd))
        subprocess.run(cmd, check=True)
        # inform server that job was printed
        try:
            requests.post(f"{FLASK_BASE}/mark_printed/{token}", timeout=3)
        except Exception as e:
            print("[WARN] Mark printed request failed:", e)
        print("[OK] Printed and marked:", token)
        return True
    except subprocess.CalledProcessError as e:
        print("[ERROR] Print command failed:", e)
        return False
    except FileNotFoundError:
        print("[ERROR] 'lp' command not found. Install CUPS or adjust printing command.")
        return False

def scan_loop():
    global last_seen, last_seen_time
    print("[INFO] Starting camera scan on device index:", CAMERA_DEVICE_INDEX)
    cap = cv2.VideoCapture(CAMERA_DEVICE_INDEX)
    if not cap.isOpened():
        print("[ERROR] Cannot open camera. Check camera index or permissions.")
        return

    cooldown = 3.0  # seconds to ignore the same token after successful processing
    while True:
        ret, frame = cap.read()
        if not ret:
            # short sleep to avoid busy loop when camera frames are not ready
            time.sleep(0.1)
            continue

        barcodes = pyzbar.decode(frame)
        for b in barcodes:
            try:
                token = b.data.decode('utf-8').strip()
            except Exception:
                continue

            now = time.time()
            # skip if same token processed recently
            if last_seen is not None and token == last_seen and (now - last_seen_time) < cooldown:
                # already processed recently
                continue

            print("[DETECTED] token:", token)
            ok = fetch_job_and_print(token)
            if ok:
                last_seen = token
                last_seen_time = now
            else:
                print("[INFO] Token processing failed or was rejected by server:", token)

        # small delay to reduce CPU usage
        time.sleep(0.1)

if __name__ == "__main__":
    try:
        last_seen = None
        last_seen_time = 0
        scan_loop()
    except KeyboardInterrupt:
        print("\n[INFO] Scanner stopped by user")
