"""SQLite connection setup, schema creation, and default data seeding."""
import sqlite3
from datetime import datetime

from app.paths import db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    start_datetime TEXT NOT NULL,
    end_datetime TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled',
    notes TEXT,
    price REAL,
    session_started_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    appointment_id INTEGER REFERENCES appointments(id),
    amount REAL NOT NULL,
    method TEXT NOT NULL,
    paid_at TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS blocked_times (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_datetime TEXT NOT NULL,
    end_datetime TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS business_hours (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_of_week TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_appt_start ON appointments(start_datetime);
CREATE INDEX IF NOT EXISTS idx_appt_client ON appointments(client_id);
CREATE INDEX IF NOT EXISTS idx_payment_client ON payments(client_id);
CREATE INDEX IF NOT EXISTS idx_blocked_start ON blocked_times(start_datetime);
"""

# (day_of_week, start_time "HH:MM", end_time "HH:MM")
DEFAULT_BUSINESS_HOURS = [
    ("Sun", "11:30", "13:30"),
    ("Sun", "19:30", "22:30"),
    ("Mon", "10:30", "13:30"),
    ("Mon", "19:30", "22:30"),
    ("Tue", "19:30", "22:30"),
    ("Wed", "10:30", "13:30"),
    ("Wed", "19:30", "22:30"),
    ("Thu", "10:30", "13:30"),
    ("Thu", "19:30", "22:30"),
    # Fri, Sat: closed - no rows
]

_connection = None


def get_connection() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        _connection = sqlite3.connect(db_path())
        _connection.row_factory = sqlite3.Row
        _connection.execute("PRAGMA foreign_keys = ON")
    return _connection


def init_db():
    conn = get_connection()
    with conn:
        conn.executescript(SCHEMA)
        # Migration: older DBs may not have session_started_at
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(appointments)")]
        if "session_started_at" not in cols:
            conn.execute("ALTER TABLE appointments ADD COLUMN session_started_at TEXT")

        count = conn.execute("SELECT COUNT(*) AS c FROM business_hours").fetchone()["c"]
        if count == 0:
            conn.executemany(
                "INSERT INTO business_hours (day_of_week, start_time, end_time) VALUES (?, ?, ?)",
                DEFAULT_BUSINESS_HOURS,
            )
    return conn


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
