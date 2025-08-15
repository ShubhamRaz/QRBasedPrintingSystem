# create_admin.py
import sqlite3
import getpass
from werkzeug.security import generate_password_hash
from config import DB_PATH

def create_admin():
    print("Create first admin user")
    username = input("Admin username: ").strip()
    if not username:
        print("Username required")
        return

    password = getpass.getpass("Admin password: ")
    if not password:
        print("Password required")
        return
    password2 = getpass.getpass("Confirm password: ")
    if password != password2:
        print("Passwords do not match")
        return

    hashed = generate_password_hash(password)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # ensure users table exists (safe to run even if app init_db also creates it)
    cur.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0
    )
    ''')
    try:
        cur.execute("INSERT INTO users (username, password, is_admin) VALUES (?, ?, ?)",
                    (username, hashed, 1))
        conn.commit()
        print("Admin user created:", username)
    except Exception as e:
        print("Error creating user (maybe username exists):", e)
    finally:
        conn.close()

if __name__ == "__main__":
    create_admin()
