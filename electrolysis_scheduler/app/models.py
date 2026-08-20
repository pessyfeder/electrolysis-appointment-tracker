"""Data access layer: plain CRUD functions over the SQLite tables."""
from app.db import get_connection, now_iso

ACTIVE_STATUSES = ("scheduled", "in_process", "completed")
ALL_STATUSES = ("scheduled", "in_process", "completed", "cancelled", "no_show")


# ---------------- Clients ----------------

def create_client(first_name, last_name, phone, notes=""):
    conn = get_connection()
    with conn:
        cur = conn.execute(
            "INSERT INTO clients (first_name, last_name, phone, notes, created_at, archived) "
            "VALUES (?, ?, ?, ?, ?, 0)",
            (first_name.strip(), last_name.strip(), phone.strip(), notes.strip(), now_iso()),
        )
    return cur.lastrowid


def update_client(client_id, first_name, last_name, phone, notes):
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE clients SET first_name=?, last_name=?, phone=?, notes=? WHERE id=?",
            (first_name.strip(), last_name.strip(), phone.strip(), notes.strip(), client_id),
        )


def archive_client(client_id, archived=True):
    conn = get_connection()
    with conn:
        conn.execute("UPDATE clients SET archived=? WHERE id=?", (1 if archived else 0, client_id))


def get_client(client_id):
    conn = get_connection()
    return conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()


def list_clients(search="", include_archived=False):
    conn = get_connection()
    query = "SELECT * FROM clients WHERE 1=1"
    params = []
    if not include_archived:
        query += " AND archived=0"
    if search:
        query += " AND (first_name LIKE ? OR last_name LIKE ? OR phone LIKE ?)"
        like = f"%{search}%"
        params += [like, like, like]
    query += " ORDER BY last_name, first_name"
    return conn.execute(query, params).fetchall()


# ---------------- Appointments ----------------

def create_appointment(client_id, start_dt, end_dt, notes="", status="scheduled"):
    conn = get_connection()
    with conn:
        cur = conn.execute(
            "INSERT INTO appointments (client_id, start_datetime, end_datetime, status, notes, price, created_at) "
            "VALUES (?, ?, ?, ?, ?, NULL, ?)",
            (client_id, start_dt.isoformat(timespec="minutes"), end_dt.isoformat(timespec="minutes"),
             status, notes.strip(), now_iso()),
        )
    return cur.lastrowid


def update_appointment(appt_id, client_id, start_dt, end_dt, notes):
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE appointments SET client_id=?, start_datetime=?, end_datetime=?, notes=? WHERE id=?",
            (client_id, start_dt.isoformat(timespec="minutes"), end_dt.isoformat(timespec="minutes"),
             notes.strip(), appt_id),
        )


def set_appointment_status(appt_id, status):
    conn = get_connection()
    with conn:
        conn.execute("UPDATE appointments SET status=? WHERE id=?", (status, appt_id))


def start_session(appt_id, started_at_iso):
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE appointments SET status='in_process', session_started_at=? WHERE id=?",
            (started_at_iso, appt_id),
        )


def end_session(appt_id, price):
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE appointments SET status='completed', price=? WHERE id=?",
            (price, appt_id),
        )


def get_appointment(appt_id):
    conn = get_connection()
    return conn.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()


def list_appointments_between(start_dt, end_dt, exclude_id=None):
    conn = get_connection()
    query = (
        "SELECT a.*, c.first_name, c.last_name FROM appointments a "
        "JOIN clients c ON c.id = a.client_id "
        "WHERE a.start_datetime < ? AND a.end_datetime > ?"
    )
    params = [end_dt.isoformat(timespec="minutes"), start_dt.isoformat(timespec="minutes")]
    if exclude_id is not None:
        query += " AND a.id != ?"
        params.append(exclude_id)
    query += " ORDER BY a.start_datetime"
    return conn.execute(query, params).fetchall()


def list_appointments_for_day(date_, exclude_id=None):
    conn = get_connection()
    day_start = date_.isoformat()
    from datetime import timedelta
    next_day = (date_ + timedelta(days=1)).isoformat()
    query = (
        "SELECT a.*, c.first_name, c.last_name FROM appointments a "
        "JOIN clients c ON c.id = a.client_id "
        "WHERE a.start_datetime >= ? AND a.start_datetime < ?"
    )
    params = [day_start, next_day]
    if exclude_id is not None:
        query += " AND a.id != ?"
        params.append(exclude_id)
    query += " ORDER BY a.start_datetime"
    return conn.execute(query, params).fetchall()


def list_appointments_for_client(client_id):
    conn = get_connection()
    return conn.execute(
        "SELECT * FROM appointments WHERE client_id=? ORDER BY start_datetime DESC", (client_id,)
    ).fetchall()


# ---------------- Payments ----------------

def create_payment(client_id, amount, method, notes="", appointment_id=None, paid_at=None):
    conn = get_connection()
    with conn:
        cur = conn.execute(
            "INSERT INTO payments (client_id, appointment_id, amount, method, paid_at, notes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (client_id, appointment_id, amount, method, paid_at or now_iso(), notes.strip()),
        )
    return cur.lastrowid


def list_payments_for_client(client_id):
    conn = get_connection()
    return conn.execute(
        "SELECT * FROM payments WHERE client_id=? ORDER BY paid_at DESC", (client_id,)
    ).fetchall()


def list_payments_between(start_dt, end_dt):
    conn = get_connection()
    return conn.execute(
        "SELECT p.*, c.first_name, c.last_name FROM payments p "
        "JOIN clients c ON c.id = p.client_id "
        "WHERE p.paid_at >= ? AND p.paid_at <= ? ORDER BY p.paid_at",
        (start_dt.isoformat(), end_dt.isoformat()),
    ).fetchall()


def client_balance(client_id):
    """Positive = client owes money. Negative = client has a credit."""
    conn = get_connection()
    charged = conn.execute(
        "SELECT COALESCE(SUM(price), 0) AS total FROM appointments "
        "WHERE client_id=? AND status='completed'",
        (client_id,),
    ).fetchone()["total"]
    paid = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM payments WHERE client_id=?", (client_id,)
    ).fetchone()["total"]
    return round(charged - paid, 2)


# ---------------- Blocked Times ----------------

def create_blocked_time(start_dt, end_dt, reason):
    if not reason or not reason.strip():
        raise ValueError("A reason is required to block off time")
    conn = get_connection()
    with conn:
        cur = conn.execute(
            "INSERT INTO blocked_times (start_datetime, end_datetime, reason, created_at) "
            "VALUES (?, ?, ?, ?)",
            (start_dt.isoformat(timespec="minutes"), end_dt.isoformat(timespec="minutes"),
             reason.strip(), now_iso()),
        )
    return cur.lastrowid


def delete_blocked_time(block_id):
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM blocked_times WHERE id=?", (block_id,))


def list_blocked_between(start_dt, end_dt):
    conn = get_connection()
    return conn.execute(
        "SELECT * FROM blocked_times WHERE start_datetime < ? AND end_datetime > ? "
        "ORDER BY start_datetime",
        (end_dt.isoformat(timespec="minutes"), start_dt.isoformat(timespec="minutes")),
    ).fetchall()


# ---------------- Business Hours ----------------

def list_business_hours():
    conn = get_connection()
    return conn.execute(
        "SELECT * FROM business_hours ORDER BY "
        "CASE day_of_week WHEN 'Sun' THEN 0 WHEN 'Mon' THEN 1 WHEN 'Tue' THEN 2 "
        "WHEN 'Wed' THEN 3 WHEN 'Thu' THEN 4 WHEN 'Fri' THEN 5 WHEN 'Sat' THEN 6 END, start_time"
    ).fetchall()


def business_hours_for_day(day_of_week):
    conn = get_connection()
    return conn.execute(
        "SELECT * FROM business_hours WHERE day_of_week=? ORDER BY start_time", (day_of_week,)
    ).fetchall()


def replace_business_hours_for_day(day_of_week, blocks):
    """blocks: list of (start_time 'HH:MM', end_time 'HH:MM')"""
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM business_hours WHERE day_of_week=?", (day_of_week,))
        conn.executemany(
            "INSERT INTO business_hours (day_of_week, start_time, end_time) VALUES (?, ?, ?)",
            [(day_of_week, s, e) for s, e in blocks],
        )
