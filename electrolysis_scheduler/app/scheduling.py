"""Business-hour enforcement, appointment-length limits, and the
1-14 minute unbookable-gap rule (see spec sections 2 and 7.1)."""
from datetime import datetime, timedelta, time

from app import models

MIN_APPOINTMENT_MINUTES = 15
_WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class SchedulingError(Exception):
    pass


def day_name(date_) -> str:
    return _WEEKDAY_NAMES[date_.weekday()]


def business_blocks_for_date(date_):
    """Returns list of (start_datetime, end_datetime) business-hour blocks for a date."""
    rows = models.business_hours_for_day(day_name(date_))
    blocks = []
    for r in rows:
        sh, sm = map(int, r["start_time"].split(":"))
        eh, em = map(int, r["end_time"].split(":"))
        start = datetime.combine(date_, time(sh, sm))
        end = datetime.combine(date_, time(eh, em))
        blocks.append((start, end))
    return blocks


def _containing_block(start_dt, end_dt):
    """Find the single business-hours block that fully contains [start_dt, end_dt)."""
    for block_start, block_end in business_blocks_for_date(start_dt.date()):
        if block_start <= start_dt and end_dt <= block_end:
            return block_start, block_end
    return None


def validate_appointment(client_id, start_dt, end_dt, exclude_id=None):
    """Raises SchedulingError with a human-readable message if the appointment
    is not bookable. Returns silently if it is valid."""
    if end_dt <= start_dt:
        raise SchedulingError("End time must be after the start time.")

    length_minutes = (end_dt - start_dt).total_seconds() / 60
    if length_minutes < MIN_APPOINTMENT_MINUTES:
        raise SchedulingError(f"Appointments must be at least {MIN_APPOINTMENT_MINUTES} minutes long.")

    block = _containing_block(start_dt, end_dt)
    if block is None:
        raise SchedulingError(
            "That time falls outside business hours (or spans across two separate "
            "business-hour blocks)."
        )

    # Blocked time conflicts
    blocked = models.list_blocked_between(start_dt, end_dt)
    if blocked:
        b = blocked[0]
        raise SchedulingError(f"That time overlaps a blocked-off period: {b['reason']}")

    # Overlap with other active appointments
    others = [
        a for a in models.list_appointments_between(start_dt, end_dt, exclude_id=exclude_id)
        if a["status"] in models.ACTIVE_STATUSES
    ]
    if others:
        o = others[0]
        raise SchedulingError(
            f"That time overlaps an existing appointment for {o['first_name']} {o['last_name']}."
        )

    # Gap rule: neighbors on the same day must be 0 min (back-to-back) or >=15 min away
    day_appts = [
        a for a in models.list_appointments_for_day(start_dt.date(), exclude_id=exclude_id)
        if a["status"] in models.ACTIVE_STATUSES
    ]
    prev_end = None
    next_start = None
    for a in day_appts:
        a_start = datetime.fromisoformat(a["start_datetime"])
        a_end = datetime.fromisoformat(a["end_datetime"])
        if a_end <= start_dt:
            if prev_end is None or a_end > prev_end:
                prev_end = a_end
        if a_start >= end_dt:
            if next_start is None or a_start < next_start:
                next_start = a_start

    if prev_end is not None:
        gap = (start_dt - prev_end).total_seconds() / 60
        if 0 < gap < MIN_APPOINTMENT_MINUTES:
            raise SchedulingError(
                f"That would leave an unbookable {int(gap)}-minute gap before this appointment. "
                f"Gaps must be 0 minutes (back-to-back) or at least {MIN_APPOINTMENT_MINUTES} minutes."
            )
    if next_start is not None:
        gap = (next_start - end_dt).total_seconds() / 60
        if 0 < gap < MIN_APPOINTMENT_MINUTES:
            raise SchedulingError(
                f"That would leave an unbookable {int(gap)}-minute gap after this appointment. "
                f"Gaps must be 0 minutes (back-to-back) or at least {MIN_APPOINTMENT_MINUTES} minutes."
            )


def is_bookable(client_id, start_dt, end_dt, exclude_id=None) -> bool:
    try:
        validate_appointment(client_id, start_dt, end_dt, exclude_id=exclude_id)
        return True
    except SchedulingError:
        return False


def find_next_open_slot(after_dt, duration_minutes=30, search_days=60):
    """Scan forward from after_dt for the next open slot of the given duration
    that satisfies business hours and the gap rule. Returns (start, end) or None."""
    date_ = after_dt.date()
    for _ in range(search_days):
        for block_start, block_end in business_blocks_for_date(date_):
            day_appts = sorted(
                [a for a in models.list_appointments_for_day(date_) if a["status"] in models.ACTIVE_STATUSES],
                key=lambda a: a["start_datetime"],
            )
            candidates = [block_start]
            for a in day_appts:
                a_end = datetime.fromisoformat(a["end_datetime"])
                if block_start <= a_end <= block_end:
                    candidates.append(a_end)
            for cand_start in candidates:
                cand_start = max(cand_start, after_dt) if date_ == after_dt.date() else cand_start
                cand_end = cand_start + timedelta(minutes=duration_minutes)
                if cand_end > block_end:
                    continue
                if is_bookable(None, cand_start, cand_end):
                    return cand_start, cand_end
        date_ = date_ + timedelta(days=1)
        after_dt = datetime.combine(date_, time(0, 0))
    return None
