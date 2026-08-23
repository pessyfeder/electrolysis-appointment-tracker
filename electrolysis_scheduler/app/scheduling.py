"""Business-hour enforcement, appointment-length limits, and the
1-14 minute unbookable-gap rule (see spec sections 2 and 7.1)."""
from datetime import datetime, timedelta, time

from app import models
from app.util import format_client_name

MIN_APPOINTMENT_MINUTES = 15
DURATION_STEP_MINUTES = 5
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


def _block_containing_point(dt):
    """Find the business-hours block that dt falls inside (start inclusive)."""
    for block_start, block_end in business_blocks_for_date(dt.date()):
        if block_start <= dt < block_end:
            return block_start, block_end
    return None


def validate_appointment(start_dt, end_dt, exclude_id=None):
    """Raises SchedulingError with a human-readable message if the appointment
    is not bookable. Returns silently if it is valid."""
    if end_dt <= start_dt:
        raise SchedulingError("End time must be after the start time.")

    length_minutes = (end_dt - start_dt).total_seconds() / 60
    if length_minutes < MIN_APPOINTMENT_MINUTES:
        raise SchedulingError(f"Appointments must be at least {MIN_APPOINTMENT_MINUTES} minutes long.")

    if start_dt.date() < datetime.now().date():
        raise SchedulingError("That date is in the past.")

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
        names = ", ".join(format_client_name(c["first_name"], c["last_name"]) for c in o["clients"])
        raise SchedulingError(f"That time overlaps an existing appointment for {names}.")

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


def is_bookable(start_dt, end_dt, exclude_id=None) -> bool:
    try:
        validate_appointment(start_dt, end_dt, exclude_id=exclude_id)
        return True
    except SchedulingError:
        return False


def _round_up(dt, step=DURATION_STEP_MINUTES):
    remainder = dt.minute % step
    if remainder == 0 and dt.second == 0 and dt.microsecond == 0:
        return dt.replace(second=0, microsecond=0)
    dt = dt.replace(second=0, microsecond=0) - timedelta(minutes=remainder)
    return dt + timedelta(minutes=step)


def earliest_bookable_start(date_, min_duration=MIN_APPOINTMENT_MINUTES, exclude_id=None):
    """Earliest start datetime on the given date where a `min_duration`-minute
    appointment could be booked, respecting business hours and the gap rule.
    Returns None if no such slot exists that day."""
    now = datetime.now()
    if date_ < now.date():
        return None
    day_appts = sorted(
        [a for a in models.list_appointments_for_day(date_, exclude_id=exclude_id)
         if a["status"] in models.ACTIVE_STATUSES],
        key=lambda a: a["start_datetime"],
    )
    for block_start, block_end in business_blocks_for_date(date_):
        candidates = [block_start]
        for a in day_appts:
            a_end = datetime.fromisoformat(a["end_datetime"])
            if block_start <= a_end <= block_end:
                candidates.append(a_end)
        for cand_start in sorted(set(candidates)):
            if date_ == now.date():
                cand_start = max(cand_start, _round_up(now))
            cand_end = cand_start + timedelta(minutes=min_duration)
            if cand_end > block_end:
                continue
            if is_bookable(cand_start, cand_end, exclude_id=exclude_id):
                return cand_start
    return None


def valid_durations(start_dt, exclude_id=None, step=DURATION_STEP_MINUTES):
    """Bookable durations (in minutes) for an appointment starting at start_dt:
    5-minute increments from 15 up to the end of the business-hours block,
    excluding any duration that would leave a 1-14 minute unbookable gap
    before the next appointment or overlap it (spec 7.1)."""
    block = _block_containing_point(start_dt)
    if block is None:
        return []
    _, block_end = block

    day_appts = [
        a for a in models.list_appointments_for_day(start_dt.date(), exclude_id=exclude_id)
        if a["status"] in models.ACTIVE_STATUSES
    ]
    next_start = None
    for a in day_appts:
        a_start = datetime.fromisoformat(a["start_datetime"])
        if a_start >= start_dt and (next_start is None or a_start < next_start):
            next_start = a_start

    upper_bound = int((block_end - start_dt).total_seconds() // 60)
    options = []
    d = MIN_APPOINTMENT_MINUTES
    while d <= upper_bound:
        end_dt = start_dt + timedelta(minutes=d)
        if next_start is not None:
            if end_dt > next_start:
                break
            gap = (next_start - end_dt).total_seconds() / 60
            if 0 < gap < MIN_APPOINTMENT_MINUTES:
                d += step
                continue
        options.append(d)
        d += step
    return options


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
                if is_bookable(cand_start, cand_end):
                    return cand_start, cand_end
        date_ = date_ + timedelta(days=1)
        after_dt = datetime.combine(date_, time(0, 0))
    return None
