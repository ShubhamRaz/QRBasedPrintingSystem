# config.py
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
DB_PATH = os.path.join(BASE_DIR, "jobs.db")

# For production, set to False. For initial testing we keep True to see more logs.
DEBUG = True

# QR token expiry (seconds). e.g., 24 hours = 86400
TOKEN_EXPIRY = 24 * 3600

# Camera device (0 for /dev/video0 or 0 for first camera)
CAMERA_DEVICE_INDEX = 0

# Printer name as known to CUPS (lpstat -p to list). Use None to use default.
PRINTER_NAME = None

# Allowed upload types
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

# Payment simulation (set to False to require "real" payment)
SIMULATE_PAYMENT = True
