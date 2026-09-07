"""Business-hour enforcement, appointment-length limits, and the
1-14 minute unbookable-gap rule (see spec sections 2 and 7.1)."""
from datetime import datetime, timedelta, time

from app import models
from app.util import format_client_name

MIN_APPOINTMENT_MINUTES = 15
DURATION_STEP_MINUTES = 5
# Kept as its own constant (rather than reusing DURATION_STEP_MINUTES)
# since duration and start-time granularity are picked independently in
# the booking form and don't need to move together.
START_TIME_STEP_MINUTES = 15
_WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class SchedulingError(Exception):
    pass


def day_name(date_) -> str:
    return _WEEKDAY_NAMES[date_.weekday()]


def business_blocks_for_date(date_):
    """Returns list of (start_datetime, end_datetime) business-hour blocks
    for a date - a per-date override if one has been set for it (see
    BusinessHoursEditor: edits apply to one specific date, never a whole
    recurring weekday), otherwise that weekday's normal schedule."""
    override = models.get_business_hours_override(date_.isoformat())
    if override is not None:
        pairs = override
    else:
        pairs = [(r["start_time"], r["end_time"]) for r in models.business_hours_for_day(day_name(date_))]
    blocks = []
    for start_str, end_str in pairs:
        sh, sm = map(int, start_str.split(":"))
        eh, em = map(int, end_str.split(":"))
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

    now = datetime.now()
    if start_dt.date() < now.date():
        raise SchedulingError("That date is in the past.")
    if start_dt < now:
        raise SchedulingError("That time has already passed today.")

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

    # Deliberately no gap-rule check here. The 1-14 minute dead-time rule
    # (see _leaves_bad_gap below) is enforced entirely by keeping such times
    # out of the Available Times/Duration dropdowns in the first place
    # (bookable_start_candidates) - never by rejecting a
    # time after it's already been offered and picked. Someone who reaches
    # here has, by construction, always chosen from an already-valid list.


def is_bookable(start_dt, end_dt, exclude_id=None) -> bool:
    try:
        validate_appointment(start_dt, end_dt, exclude_id=exclude_id)
        return True
    except SchedulingError:
        return False


def _gap_neighbors(start_dt, end_dt, block, exclude_id=None):
    """(prev_end, next_start): the closest appointment boundary before
    start_dt and after end_dt on the same day, defaulting to the containing
    business-hours block's own open/close time when there's no closer
    appointment - block open/close counts as a neighbor too, since starting
    a few minutes after opening (or ending a few minutes before closing)
    leaves the same kind of dead time as a too-short gap between two
    appointments."""
    block_start, block_end = block
    day_appts = [
        a for a in models.list_appointments_for_day(start_dt.date(), exclude_id=exclude_id)
        if a["status"] in models.ACTIVE_STATUSES
    ]
    prev_end = block_start
    next_start = block_end
    for a in day_appts:
        a_start = datetime.fromisoformat(a["start_datetime"])
        a_end = datetime.fromisoformat(a["end_datetime"])
        if a_end <= start_dt and a_end > prev_end:
            prev_end = a_end
        if a_start >= end_dt and a_start < next_start:
            next_start = a_start
    return prev_end, next_start


def _leaves_bad_gap(start_dt, end_dt, block, exclude_id=None) -> bool:
    """True if booking [start_dt, end_dt) would leave a 1-14 minute
    unbookable idle gap before or after it (against the nearest appointment,
    or the business-hours block's own boundary - see _gap_neighbors)."""
    prev_end, next_start = _gap_neighbors(start_dt, end_dt, block, exclude_id=exclude_id)
    gap = (start_dt - prev_end).total_seconds() / 60
    if 0 < gap < MIN_APPOINTMENT_MINUTES:
        return True
    gap = (next_start - end_dt).total_seconds() / 60
    if 0 < gap < MIN_APPOINTMENT_MINUTES:
        return True
    return False


def _round_up(dt, step=DURATION_STEP_MINUTES):
    remainder = dt.minute % step
    if remainder == 0 and dt.second == 0 and dt.microsecond == 0:
        return dt.replace(second=0, microsecond=0)
    dt = dt.replace(second=0, microsecond=0) - timedelta(minutes=remainder)
    return dt + timedelta(minutes=step)


def bookable_start_candidates(date_, min_duration=MIN_APPOINTMENT_MINUTES, exclude_id=None,
                               step=DURATION_STEP_MINUTES):
    """Every start time on the given date where a `min_duration`-minute
    appointment could be booked, without overlapping an existing
    appointment/blocked time or leaving an unbookable 1-14 minute gap.

    Sampled at `step`-minute intervals from each business-hours block's
    open time, to keep the dropdown a manageable length to browse. But a
    `step` coarser than a couple of minutes can land nowhere near an
    existing appointment's boundary and so skip straight over a perfectly
    legal back-to-back continuation (spec: a 0-minute gap is always fine,
    same as against the block's own open/close) - so every existing
    appointment's own end time (start right after it), the start it would
    need to butt up against the *next* appointment, and the last instant
    that still fits before the block closes are always tested too,
    regardless of whether they fall on the `step` grid. Used to populate
    the start-time dropdown (spec 8: clients may only schedule by picking a
    listed, permissible time, never by typing one in)."""
    now = datetime.now()
    if date_ < now.date():
        return []
    day_appts = [
        a for a in models.list_appointments_for_day(date_, exclude_id=exclude_id)
        if a["status"] in models.ACTIVE_STATUSES
    ]
    found = []
    for block_start, block_end in business_blocks_for_date(date_):
        block = (block_start, block_end)
        grid_start = block_start
        if date_ == now.date():
            grid_start = max(grid_start, _round_up(now, step))

        anchors = set()
        cand = grid_start
        while cand + timedelta(minutes=min_duration) <= block_end:
            anchors.add(cand)
            cand += timedelta(minutes=step)
        for a in day_appts:
            anchors.add(datetime.fromisoformat(a["end_datetime"]))
            anchors.add(datetime.fromisoformat(a["start_datetime"]) - timedelta(minutes=min_duration))
        anchors.add(block_end - timedelta(minutes=min_duration))

        for cand in sorted(anchors):
            if cand < grid_start:
                continue
            cand_end = cand + timedelta(minutes=min_duration)
            if cand_end > block_end:
                continue
            if is_bookable(cand, cand_end, exclude_id=exclude_id) \
                    and not _leaves_bad_gap(cand, cand_end, block, exclude_id=exclude_id):
                found.append(cand)
    return found


def earliest_bookable_start(date_, min_duration=MIN_APPOINTMENT_MINUTES, exclude_id=None):
    """Earliest start datetime on the given date where a `min_duration`-minute
    appointment could be booked, respecting business hours and the gap rule.
    Returns None if no such slot exists that day."""
    candidates = bookable_start_candidates(date_, min_duration, exclude_id=exclude_id)
    return candidates[0] if candidates else None


def _longest_default_block_minutes():
    """Longest single business-hours block, in minutes, across the default
    weekly schedule - ignoring per-date overrides, since those aren't
    knowable yet at the point duration is being picked (before any date has
    been chosen). Used to cap default_duration_options()."""
    longest = 0
    for day in _WEEKDAY_NAMES:
        for r in models.business_hours_for_day(day):
            sh, sm = map(int, r["start_time"].split(":"))
            eh, em = map(int, r["end_time"].split(":"))
            longest = max(longest, (eh * 60 + em) - (sh * 60 + sm))
    return longest


def default_duration_options(step=DURATION_STEP_MINUTES):
    """Generic duration choices, in `step`-minute increments starting at
    MIN_APPOINTMENT_MINUTES, for the Duration dropdown - offered before any
    date/start time has been chosen (booking now asks for duration first),
    so unlike bookable_start_candidates()'s start-time list this can't be
    bounded by a specific day's business hours or existing appointments.
    Capped instead at the longest block in the default weekly schedule, so
    it doesn't offer a length that could never fit any day. Once a date is
    actually picked, bookable_start_candidates(date_, min_duration=...)
    filters Start time down to whichever times that duration really fits
    into on that specific day."""
    cap = max(_longest_default_block_minutes(), MIN_APPOINTMENT_MINUTES)
    options = []
    d = MIN_APPOINTMENT_MINUTES
    while d <= cap:
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
