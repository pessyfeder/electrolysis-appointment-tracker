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

-- An "appointment" is a booked calendar slot (a time block). One or more
-- clients can be attached to it (see appointment_clients) so, e.g., a
-- parent and child can share one slot on the calendar while still being
-- treated - and billed - one at a time, sequentially.
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_datetime TEXT NOT NULL,
    end_datetime TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS appointment_clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    appointment_id INTEGER NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    order_index INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'scheduled',
    session_started_at TEXT,
    price REAL
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
CREATE INDEX IF NOT EXISTS idx_appt_clients_appt ON appointment_clients(appointment_id);
CREATE INDEX IF NOT EXISTS idx_appt_clients_client ON appointment_clients(client_id);
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


def _migrate_to_multi_client_appointments(conn):
    """Older DBs have a single client_id/status/price/session_started_at
    directly on appointments. Move that data into the new appointment_clients
    join table (one row per client, order_index 0) so multiple clients can
    share a slot, then drop those columns from appointments."""
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(appointments)")]
    if "client_id" not in cols:
        return

    # appointment_clients was just created fresh by the SCHEMA script above,
    # with its foreign key pointing at the not-yet-migrated appointments
    # table. SQLite auto-rewrites that FK to follow the upcoming RENAME, and
    # then DROP TABLE appointments_old would cascade-delete these rows right
    # back out - so drop and recreate it after the rename instead, once its
    # FK can point at the real, final appointments table.
    conn.execute("DROP TABLE IF EXISTS appointment_clients")
    conn.execute("ALTER TABLE appointments RENAME TO appointments_old")
    conn.execute(
        "CREATE TABLE appointments ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "start_datetime TEXT NOT NULL, "
        "end_datetime TEXT NOT NULL, "
        "notes TEXT, "
        "created_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE appointment_clients ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "appointment_id INTEGER NOT NULL REFERENCES appointments(id) ON DELETE CASCADE, "
        "client_id INTEGER NOT NULL REFERENCES clients(id), "
        "order_index INTEGER NOT NULL DEFAULT 0, "
        "status TEXT NOT NULL DEFAULT 'scheduled', "
        "session_started_at TEXT, "
        "price REAL)"
    )
    conn.execute(
        "INSERT INTO appointments (id, start_datetime, end_datetime, notes, created_at) "
        "SELECT id, start_datetime, end_datetime, notes, created_at FROM appointments_old"
    )
    old_cols = set(cols)
    has_session_col = "session_started_at" in old_cols
    conn.execute(
        "INSERT INTO appointment_clients "
        "(appointment_id, client_id, order_index, status, session_started_at, price) "
        "SELECT id, client_id, 0, status, "
        + ("session_started_at" if has_session_col else "NULL") +
        ", price FROM appointments_old"
    )
    conn.execute("DROP TABLE appointments_old")


def init_db():
    conn = get_connection()
    with conn:
        conn.executescript(SCHEMA)
        _migrate_to_multi_client_appointments(conn)

        count = conn.execute("SELECT COUNT(*) AS c FROM business_hours").fetchone()["c"]
        if count == 0:
            conn.executemany(
                "INSERT INTO business_hours (day_of_week, start_time, end_time) VALUES (?, ?, ?)",
                DEFAULT_BUSINESS_HOURS,
            )
    return conn


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
