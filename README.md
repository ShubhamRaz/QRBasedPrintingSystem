# Smart QR-Based Printing System

A **Raspberry Pi Zero 2 W–powered** document printing system where users can upload documents via a web interface, pay, and receive a QR code.  
Later, they scan the QR code at the printer station to automatically print their document.  

Includes a secure **admin panel with login authentication** for job monitoring.

---

## Features

- 📤 **Document Upload** — Users can upload PDF/images from phone or PC.
- 💳 **Payment Integration (optional)** — Only paid jobs can be printed.
- 📱 **QR Code Generation** — Each uploaded file gets a unique QR token.
- 📷 **QR Code Scanner** — Camera at print station detects token and fetches the file.
- 🖨 **Automatic Printing** — Sends the file to the printer via CUPS (`lp` command).
- 🔒 **Secure Admin Panel** — Requires login to view/manage jobs.
- 📊 **Admin Dashboard** — View uploaded, pending, and printed jobs.

---

## Tech Stack

- **Backend**: Python + Flask
- **Database**: SQLite (`jobs.db`)
- **Frontend**: HTML/CSS (mobile-friendly)
- **QR Handling**: `qrcode` + `opencv-python` + `pyzbar`
- **Printing**: CUPS (`lp` command)
- **Auth**: Session-based login with hashed passwords

---

## Hardware Requirements

- Raspberry Pi Zero 2 W (or any Raspberry Pi model with Wi-Fi)
- MicroSD card (16GB+ recommended)
- USB OTG cable + printer connection
- USB camera or Pi Camera Module
- Installed printer via CUPS

---

## Software Requirements

- Python 3.9+
- Virtualenv
- CUPS (for printing)
- Flask and required Python packages

---

## Installation

### 1. Clone repository
```bash
git clone https://github.com/yourusername/SmartQRPrint.git
cd SmartQRPrint
