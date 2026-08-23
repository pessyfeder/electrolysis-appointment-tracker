"""Data access layer: plain CRUD functions over the SQLite tables.

An appointment is a booked calendar slot (a time block). One or more
clients can be attached to it via appointment_clients, each with their own
status/session/price - so a shared slot can still be billed one client at a
time, sequentially (see AppointmentDialog)."""
from datetime import datetime, timedelta

from app.db import get_connection, now_iso

ACTIVE_STATUSES = ("scheduled", "in_process", "completed")
ALL_STATUSES = ("scheduled", "in_process", "completed", "cancelled", "no_show")

# Priority order used to pick one overall status/color for an appointment
# block that may have clients in different states (spec: color-code by
# status). Earliest-listed status "wins" when present on any client.
_STATUS_PRIORITY = ("in_process", "scheduled", "completed", "no_show", "cancelled")


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

def _derive_status(client_rows):
    statuses = {r["status"] for r in client_rows}
    for s in _STATUS_PRIORITY:
        if s in statuses:
            return s
    return "cancelled"


def _clients_for_appointments(conn, appt_ids):
    if not appt_ids:
        return {}
    placeholders = ",".join("?" * len(appt_ids))
    rows = conn.execute(
        f"SELECT ac.*, c.first_name, c.last_name, c.phone FROM appointment_clients ac "
        f"JOIN clients c ON c.id = ac.client_id WHERE ac.appointment_id IN ({placeholders}) "
        f"ORDER BY ac.appointment_id, ac.order_index",
        appt_ids,
    ).fetchall()
    by_appt = {}
    for r in rows:
        by_appt.setdefault(r["appointment_id"], []).append(r)
    return by_appt


def _bundle(appt_row, client_rows):
    d = dict(appt_row)
    d["clients"] = client_rows
    d["status"] = _derive_status(client_rows)
    d["first_name"] = client_rows[0]["first_name"] if client_rows else ""
    d["last_name"] = client_rows[0]["last_name"] if client_rows else "(no client)"
    return d


def _bundle_rows(conn, appt_rows):
    appt_ids = [r["id"] for r in appt_rows]
    by_appt = _clients_for_appointments(conn, appt_ids)
    return [_bundle(r, by_appt.get(r["id"], [])) for r in appt_rows]


def is_appointment_active(appt_bundle) -> bool:
    return any(c["status"] in ACTIVE_STATUSES for c in appt_bundle["clients"])


def create_appointment(client_ids, start_dt, end_dt, notes=""):
    if not client_ids:
        raise ValueError("An appointment needs at least one client")
    conn = get_connection()
    with conn:
        cur = conn.execute(
            "INSERT INTO appointments (start_datetime, end_datetime, notes, created_at) "
            "VALUES (?, ?, ?, ?)",
            (start_dt.isoformat(timespec="minutes"), end_dt.isoformat(timespec="minutes"),
             notes.strip(), now_iso()),
        )
        appt_id = cur.lastrowid
        for idx, client_id in enumerate(client_ids):
            conn.execute(
                "INSERT INTO appointment_clients (appointment_id, client_id, order_index, status) "
                "VALUES (?, ?, ?, 'scheduled')",
                (appt_id, client_id, idx),
            )
    return appt_id


def add_client_to_appointment(appt_id, client_id):
    conn = get_connection()
    with conn:
        max_idx = conn.execute(
            "SELECT COALESCE(MAX(order_index), -1) AS m FROM appointment_clients WHERE appointment_id=?",
            (appt_id,),
        ).fetchone()["m"]
        cur = conn.execute(
            "INSERT INTO appointment_clients (appointment_id, client_id, order_index, status) "
            "VALUES (?, ?, ?, 'scheduled')",
            (appt_id, client_id, max_idx + 1),
        )
    return cur.lastrowid


def remove_appointment_client(appt_client_id):
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM appointment_clients WHERE id=?", (appt_client_id,))


def update_appointment(appt_id, start_dt, end_dt, notes):
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE appointments SET start_datetime=?, end_datetime=?, notes=? WHERE id=?",
            (start_dt.isoformat(timespec="minutes"), end_dt.isoformat(timespec="minutes"),
             notes.strip(), appt_id),
        )


def set_client_status(appt_client_id, status):
    conn = get_connection()
    with conn:
        conn.execute("UPDATE appointment_clients SET status=? WHERE id=?", (status, appt_client_id))


def start_client_session(appt_client_id, started_at_iso):
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE appointment_clients SET status='in_process', session_started_at=? WHERE id=?",
            (started_at_iso, appt_client_id),
        )


def end_client_session(appt_client_id, price):
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE appointment_clients SET status='completed', price=? WHERE id=?",
            (price, appt_client_id),
        )


def get_appointment(appt_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()
    if row is None:
        return None
    return _bundle(row, _clients_for_appointments(conn, [appt_id]).get(appt_id, []))


def list_appointments_between(start_dt, end_dt, exclude_id=None):
    conn = get_connection()
    query = "SELECT * FROM appointments WHERE start_datetime < ? AND end_datetime > ?"
    params = [end_dt.isoformat(timespec="minutes"), start_dt.isoformat(timespec="minutes")]
    if exclude_id is not None:
        query += " AND id != ?"
        params.append(exclude_id)
    query += " ORDER BY start_datetime"
    rows = conn.execute(query, params).fetchall()
    return _bundle_rows(conn, rows)


def list_appointments_for_day(date_, exclude_id=None):
    conn = get_connection()
    day_start = date_.isoformat()
    next_day = (date_ + timedelta(days=1)).isoformat()
    query = "SELECT * FROM appointments WHERE start_datetime >= ? AND start_datetime < ?"
    params = [day_start, next_day]
    if exclude_id is not None:
        query += " AND id != ?"
        params.append(exclude_id)
    query += " ORDER BY start_datetime"
    rows = conn.execute(query, params).fetchall()
    return _bundle_rows(conn, rows)


def list_appointments_for_client(client_id):
    """Each row is this client's own sub-session (status/price/session
    timing) on a shared appointment slot, joined with that slot's timing."""
    conn = get_connection()
    return conn.execute(
        "SELECT ac.*, a.start_datetime, a.end_datetime, a.notes AS appointment_notes "
        "FROM appointment_clients ac JOIN appointments a ON a.id = ac.appointment_id "
        "WHERE ac.client_id=? ORDER BY a.start_datetime DESC",
        (client_id,),
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
        "SELECT COALESCE(SUM(price), 0) AS total FROM appointment_clients "
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
