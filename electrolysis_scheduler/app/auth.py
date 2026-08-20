"""Admin password gate. Only a bcrypt hash of the password is ever stored."""
import bcrypt

from app.db import get_connection

SETTING_KEY = "admin_password_hash"


def has_password_set() -> bool:
    conn = get_connection()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (SETTING_KEY,)).fetchone()
    return row is not None and row["value"]


def set_password(plaintext: str):
    if not plaintext:
        raise ValueError("Password cannot be empty")
    hashed = bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    conn = get_connection()
    with conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (SETTING_KEY, hashed),
        )


def verify_password(plaintext: str) -> bool:
    conn = get_connection()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (SETTING_KEY,)).fetchone()
    if row is None or not row["value"]:
        return False
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), row["value"].encode("utf-8"))
    except ValueError:
        return False
