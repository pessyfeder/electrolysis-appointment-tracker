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


def _apply_no_show_transitions(conn):
    """A client left 'scheduled' on an appointment whose block has already
    ended without ever being started missed it - promote them to no_show so
    the calendar reflects reality without Admin having to notice and flip it
    by hand. Run on every read path below rather than on a timer, so the
    status is always correct by the time it's displayed.

    A no-show is billed the same as a completed session - they owe the full
    price of the slot they booked, since it was held for them whether or not
    they showed up (see client_balance). Also backfills price for any
    already-no_show row still missing one (e.g. promoted before this
    billing behavior existed), so a pre-existing no-show doesn't silently
    stay uncharged."""
    from app.billing import calculate_price
    rows = conn.execute(
        "SELECT ac.id, a.start_datetime, a.end_datetime FROM appointment_clients ac "
        "JOIN appointments a ON a.id = ac.appointment_id "
        "WHERE (ac.status='scheduled' AND a.end_datetime < ?) "
        "OR (ac.status='no_show' AND ac.price IS NULL)",
        (now_iso(),),
    ).fetchall()
    with conn:
        for r in rows:
            price = calculate_price(
                datetime.fromisoformat(r["start_datetime"]), datetime.fromisoformat(r["end_datetime"])
            )
            conn.execute(
                "UPDATE appointment_clients SET status='no_show', price=? WHERE id=?",
                (price, r["id"]),
            )


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


def mark_no_show(appt_client_id, price):
    """A client who never showed up owes the full price of the slot they
    booked, same as if they'd come in and completed it."""
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE appointment_clients SET status='no_show', price=? WHERE id=?",
            (price, appt_client_id),
        )


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
    _apply_no_show_transitions(conn)
    row = conn.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()
    if row is None:
        return None
    return _bundle(row, _clients_for_appointments(conn, [appt_id]).get(appt_id, []))


def list_appointments_between(start_dt, end_dt, exclude_id=None):
    conn = get_connection()
    _apply_no_show_transitions(conn)
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
    _apply_no_show_transitions(conn)
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


def search_appointments(query="", on_date=None, limit=200):
    """Find appointments by client name/phone substring and/or an exact
    date, most recent first. Either filter may be omitted; with neither, no
    rows are returned (searching is meaningless with nothing to match)."""
    if not query and on_date is None:
        return []
    conn = get_connection()
    _apply_no_show_transitions(conn)
    sql = (
        "SELECT DISTINCT a.* FROM appointments a "
        "JOIN appointment_clients ac ON ac.appointment_id = a.id "
        "JOIN clients c ON c.id = ac.client_id WHERE 1=1"
    )
    params = []
    if query:
        like = f"%{query}%"
        sql += (
            " AND (c.first_name LIKE ? OR c.last_name LIKE ? OR c.phone LIKE ? "
            "OR (c.first_name || ' ' || c.last_name) LIKE ?)"
        )
        params += [like, like, like, like]
    if on_date is not None:
        day_start = on_date.isoformat()
        next_day = (on_date + timedelta(days=1)).isoformat()
        sql += " AND a.start_datetime >= ? AND a.start_datetime < ?"
        params += [day_start, next_day]
    sql += " ORDER BY a.start_datetime DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return _bundle_rows(conn, rows)


def list_appointments_for_client(client_id):
    """Each row is this client's own sub-session (status/price/session
    timing) on a shared appointment slot, joined with that slot's timing."""
    conn = get_connection()
    _apply_no_show_transitions(conn)
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


def _client_unpaid_charges(conn, client_id):
    """Every billed charge (completed or no-show) for this client, in date
    order, with how much of each is still unpaid - payments aren't tied to
    a specific appointment (the Record a Payment form just pays down the
    client's balance generally), so there's no stored link from a payment
    back to "the" charge it settled. This applies the client's total
    payments to their charges oldest-first (a standard AR aging/FIFO
    assumption) to recover a specific unpaid amount per charge; the unpaid
    amounts always sum to exactly client_balance() when positive."""
    charges = conn.execute(
        "SELECT ac.price AS amount, a.start_datetime, c.first_name, c.last_name, ac.status "
        "FROM appointment_clients ac "
        "JOIN appointments a ON a.id = ac.appointment_id "
        "JOIN clients c ON c.id = ac.client_id "
        "WHERE ac.client_id=? AND ac.status IN ('completed', 'no_show') AND ac.price IS NOT NULL "
        "ORDER BY a.start_datetime",
        (client_id,),
    ).fetchall()
    pool = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM payments WHERE client_id=?", (client_id,)
    ).fetchone()["total"]
    result = []
    for ch in charges:
        amount = ch["amount"]
        unpaid = amount - pool if pool < amount else 0.0
        pool = max(0.0, pool - amount)
        result.append({
            "amount": round(unpaid, 2), "start_datetime": ch["start_datetime"],
            "first_name": ch["first_name"], "last_name": ch["last_name"], "status": ch["status"],
        })
    return result


def list_unpaid_charges_between(start_dt, end_dt):
    """Unpaid portion of every charge (completed or no-show) whose
    appointment fell in this range. Unlike payments (filtered by when they
    were paid), a charge that's never been paid has no payment date to
    filter by - so this filters by the charge's own appointment date
    instead."""
    conn = get_connection()
    client_ids = [
        r["client_id"] for r in conn.execute(
            "SELECT DISTINCT ac.client_id FROM appointment_clients ac "
            "JOIN appointments a ON a.id = ac.appointment_id "
            "WHERE ac.status IN ('completed', 'no_show') AND ac.price IS NOT NULL "
            "AND a.start_datetime >= ? AND a.start_datetime <= ?",
            (start_dt.isoformat(), end_dt.isoformat()),
        ).fetchall()
    ]
    charges = []
    for client_id in client_ids:
        for ch in _client_unpaid_charges(conn, client_id):
            if start_dt.isoformat() <= ch["start_datetime"] <= end_dt.isoformat() and ch["amount"] > 0:
                charges.append(ch)
    charges.sort(key=lambda ch: ch["start_datetime"])
    return charges


def client_balance(client_id):
    """Positive = client owes money. Negative = client has a credit.
    A no-show is charged the same as a completed session (see
    _apply_no_show_transitions/mark_no_show), so it counts toward what's
    owed exactly like a completed one does."""
    conn = get_connection()
    charged = conn.execute(
        "SELECT COALESCE(SUM(price), 0) AS total FROM appointment_clients "
        "WHERE client_id=? AND status IN ('completed', 'no_show')",
        (client_id,),
    ).fetchone()["total"]
    paid = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM payments WHERE client_id=?", (client_id,)
    ).fetchone()["total"]
    return round(charged - paid, 2)


def client_has_no_show(client_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM appointment_clients WHERE client_id=? AND status='no_show' LIMIT 1",
        (client_id,),
    ).fetchone()
    return row is not None


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


# ---------------- Business Hours Overrides (per-date) ----------------

def get_business_hours_override(date_iso):
    """None if `date_iso` has no override (the weekday's normal recurring
    hours apply); otherwise the list of (start_time, end_time) open blocks
    for that date specifically - an empty list means the date is
    overridden to be fully closed."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT start_time, end_time FROM business_hours_overrides WHERE date=? ORDER BY start_time",
        (date_iso,),
    ).fetchall()
    if not rows:
        return None
    return [(r["start_time"], r["end_time"]) for r in rows if r["start_time"] is not None]


def set_business_hours_override(date_iso, blocks):
    """blocks: list of (start_time 'HH:MM', end_time 'HH:MM') for this one
    date only - every other date keeps its normal weekly schedule. An empty
    list overrides the date to be fully closed (recorded as a single NULL/
    NULL row, distinct from no override at all)."""
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM business_hours_overrides WHERE date=?", (date_iso,))
        if blocks:
            conn.executemany(
                "INSERT INTO business_hours_overrides (date, start_time, end_time) VALUES (?, ?, ?)",
                [(date_iso, s, e) for s, e in blocks],
            )
        else:
            conn.execute(
                "INSERT INTO business_hours_overrides (date, start_time, end_time) VALUES (?, NULL, NULL)",
                (date_iso,),
            )


def clear_business_hours_override(date_iso):
    """Removes the override for `date_iso` entirely, reverting it back to
    its normal weekday hours."""
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM business_hours_overrides WHERE date=?", (date_iso,))
