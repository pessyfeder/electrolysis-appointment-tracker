from datetime import datetime, date, time, timedelta

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QScrollArea,
    QButtonGroup, QMessageBox, QFrame, QListWidget, QListWidgetItem,
    QSizePolicy, QMenu, QCalendarWidget, QWidgetAction
)
from PySide6.QtCore import Qt, QRectF, QTimer, Signal, QEvent
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QFont, QFontMetrics

from app import models, scheduling
from app.util import format_12h, format_client_name
from ui.month_view import MonthGridWidget

DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def _never_shrink(widget):
    """A QHBoxLayout is allowed to compress a widget below its sizeHint down
    to its minimumSizeHint when the layout is tight on space - for a
    QPushButton/QLabel that gap is real (Qt lets button/label text run a
    few pixels narrower than its natural width before truly refusing to
    shrink further), and it reads as clipped text. Locking the horizontal
    policy to Minimum makes sizeHint the hard floor instead."""
    policy = widget.sizePolicy()
    policy.setHorizontalPolicy(QSizePolicy.Minimum)
    widget.setSizePolicy(policy)

# (background, border, text) per status - a soft tint instead of a solid
# fill reads calmer at the small sizes an appointment card is drawn at, and
# matches the same tint/text pairing already used for the per-client status
# rows in the appointment dialog.
STATUS_STYLES = {
    "scheduled": ("#eff6ff", "#bfdbfe", "#1d4ed8"),
    "in_process": ("#fffbeb", "#fde68a", "#b45309"),
    "completed": ("#f0fdf4", "#bbf7d0", "#15803d"),
    "cancelled": ("#f8fafc", "#e2e8f0", "#64748b"),
    "no_show": ("#fef2f2", "#fecaca", "#b91c1c"),
}
STATUS_LABELS = {
    "scheduled": "Scheduled", "in_process": "In Progress", "completed": "Completed",
    "cancelled": "Cancelled", "no_show": "No-Show",
}

PX_PER_MIN = 1.4
SLOT_MIN = 15
CARD_HEADER_HEIGHT = 26
CARD_TOP_MARGIN = 10
CARD_GAP = 14
CARD_RADIUS = 10

# Appointments in these statuses still need to happen, so one that ends up
# overlapping blocked-off time (spec: Admin can choose to block over an
# existing appointment, but must then reschedule/cancel it) needs Admin's
# attention. A completed/cancelled/no-show appointment doesn't.
_NEEDS_RESCHEDULE_STATUSES = ("scheduled", "in_process")


def week_start(d: date) -> date:
    # Weeks start on Sunday to match the business_hours table (spec 7.1).
    offset = (d.weekday() + 1) % 7  # Monday=0..Sunday=6 -> Sunday=0
    return d - timedelta(days=offset)


class ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class DayHeaderWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.columns = [date.today()]
        self.setFixedHeight(40)

    def set_columns(self, columns):
        self.columns = columns
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#f8fafc"))
        col_width = self.width() / max(1, len(self.columns))
        font = QFont()
        font.setBold(True)
        p.setFont(font)
        today = date.today()
        # Each day gets its own separated, bordered box (matching the ~4px
        # gap the time-grid cards below already use between columns) instead
        # of a continuous strip divided only by thin lines - much easier to
        # tell columns apart at a glance.
        gap = 4
        for i, d in enumerate(self.columns):
            x = i * col_width
            box = QRectF(x + gap / 2, 3, col_width - gap, self.height() - 6)
            if d == today:
                bg, border = QColor("#dbeafe"), QColor("#93c5fd")
            elif d < today:
                bg, border = QColor("#e2e8f0"), QColor("#cbd5e1")
            else:
                bg, border = QColor("#ffffff"), QColor("#cbd5e1")
            p.setBrush(QBrush(bg))
            p.setPen(QPen(border, 1))
            p.drawRoundedRect(box, 6, 6)
            p.setPen(QPen(QColor("#94a3b8") if d < today else QColor("#1e293b")))
            p.drawText(box, Qt.AlignCenter, f"{DAY_NAMES[(d.weekday() + 1) % 7]} {d.month}/{d.day}")
        p.end()


class TimeGridWidget(QWidget):
    """Shows only the actual open-for-business windows, each as its own
    self-contained bordered card. Closed time is never drawn. Past-day
    columns are grayed out and their empty space is not clickable for
    booking - existing appointments on them stay clickable so Admin can
    still view who was booked."""

    slot_clicked = Signal(object)          # datetime
    appt_clicked = Signal(object)          # appt row
    block_clicked = Signal(object)         # blocked_time row
    block_time_requested = Signal(object)  # datetime (right-click -> block this)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.columns = [date.today()]
        self.appointments = []
        self.blocked = []
        self._columns_cards = []   # per column: list of card dicts
        self._appt_layout = []
        self._block_layout = []
        self._conflicting_ids = set()
        self._conflict_flash_on = True
        self.setMinimumHeight(200)
        self.setMouseTracking(True)
        # Recomputed each _relayout() to whatever value makes the full
        # business-hours grid exactly fill the scroll area's viewport - see
        # _relayout() - so the calendar never needs vertical scrolling to
        # see the whole day. Starts at the constant as a fallback for the
        # first, pre-layout pass before a real viewport height is known.
        self._px_per_min = PX_PER_MIN

        self._conflict_timer = QTimer(self)
        self._conflict_timer.timeout.connect(self._toggle_conflict_flash)

    def set_data(self, columns, appointments, blocked):
        self.columns = columns
        self.appointments = appointments
        self.blocked = blocked
        self._conflicting_ids = self._compute_conflicting_ids()
        if self._conflicting_ids:
            if not self._conflict_timer.isActive():
                self._conflict_flash_on = True
                self._conflict_timer.start(500)
        else:
            self._conflict_timer.stop()
            self._conflict_flash_on = True
        self._relayout()
        self.update()

    def _compute_conflicting_ids(self):
        conflicts = set()
        for a in self.appointments:
            if a["status"] not in _NEEDS_RESCHEDULE_STATUSES:
                continue
            a_start = datetime.fromisoformat(a["start_datetime"])
            a_end = datetime.fromisoformat(a["end_datetime"])
            for b in self.blocked:
                b_start = datetime.fromisoformat(b["start_datetime"])
                b_end = datetime.fromisoformat(b["end_datetime"])
                if a_start < b_end and a_end > b_start:
                    conflicts.add(a["id"])
                    break
        return conflicts

    def _toggle_conflict_flash(self):
        self._conflict_flash_on = not self._conflict_flash_on
        self.update()

    def resizeEvent(self, event):
        # Card positions/widths are cached in pixels by _relayout() (last
        # computed for whatever width the widget had at set_data() time), so
        # without recomputing here a window resize repaints the old, now
        # wrong-sized cards instead of ones that fill the new width.
        super().resizeEvent(event)
        self._relayout()

    def _col_width(self):
        return self.width() / max(1, len(self.columns))

    def _full_height(self, block):
        block_start, block_end = block
        duration_min = (block_end - block_start).total_seconds() / 60
        body_h = max(20, duration_min * self._px_per_min)
        return CARD_HEADER_HEIGHT + body_h

    def _stacked_height(self, blocks):
        if not blocks:
            return 0
        return sum(self._full_height(b) for b in blocks) + CARD_GAP * (len(blocks) - 1)

    @staticmethod
    def _stacked_parts(blocks):
        """(fixed_px, total_minutes) for one AM/PM stack - fixed_px is the
        part of _stacked_height that doesn't scale with pixels-per-minute
        (card headers + gaps), total_minutes is the part that does. Lets
        _relayout() solve for the exact scale that fits a target height
        instead of using a constant."""
        if not blocks:
            return 0, 0
        fixed = CARD_HEADER_HEIGHT * len(blocks) + CARD_GAP * (len(blocks) - 1)
        minutes = sum((b_end - b_start).total_seconds() / 60 for b_start, b_end in blocks)
        return fixed, minutes

    def _relayout(self):
        col_width = self._col_width()
        today = date.today()
        now = datetime.now()

        # Business hours split into an AM period (before noon) and a PM/
        # evening period. Every column gets the SAME y for its AM row and
        # the SAME y for its PM row, so appointments line up across days
        # even when one day is missing a period (e.g. Tue has no AM block)
        # or its block runs a different length than its neighbors'.
        per_col_periods = []
        for d in self.columns:
            blocks = scheduling.business_blocks_for_date(d)
            am = [b for b in blocks if b[0].hour < 12]
            pm = [b for b in blocks if b[0].hour >= 12]
            per_col_periods.append((am, pm))

        # Whichever column's AM/PM stack is tallest (at the reference scale)
        # is what determines the grid's overall height, same as before -
        # decomposed into fixed/minutes so the scale needed to make that
        # height exactly match the available viewport (no scrolling) can be
        # solved for directly.
        am_fixed, am_minutes = max(
            (self._stacked_parts(am) for am, _ in per_col_periods),
            key=lambda parts: parts[0] + parts[1] * PX_PER_MIN, default=(0, 0),
        )
        pm_fixed, pm_minutes = max(
            (self._stacked_parts(pm) for _, pm in per_col_periods),
            key=lambda parts: parts[0] + parts[1] * PX_PER_MIN, default=(0, 0),
        )
        fixed_overhead = (
            2 * CARD_TOP_MARGIN
            + (am_fixed + CARD_GAP if am_minutes else 0)
            + (pm_fixed if pm_minutes else 0)
        )
        total_minutes = am_minutes + pm_minutes
        available = self.height()
        if total_minutes > 0 and available > 0:
            self._px_per_min = max(0.5, min(4.0, (available - fixed_overhead) / total_minutes))
        else:
            self._px_per_min = PX_PER_MIN

        am_height = max((self._stacked_height(am) for am, _ in per_col_periods), default=0)
        pm_height = max((self._stacked_height(pm) for _, pm in per_col_periods), default=0)

        am_row_y = CARD_TOP_MARGIN
        pm_row_y = am_row_y + (am_height + CARD_GAP if am_height else 0)
        max_height = max(am_row_y + am_height, pm_row_y + pm_height) + CARD_TOP_MARGIN

        self._columns_cards = []
        for i, d in enumerate(self.columns):
            x = i * col_width
            am, pm = per_col_periods[i]
            cards = []
            for row_y, blocks in ((am_row_y, am), (pm_row_y, pm)):
                y = row_y
                for block_start, block_end in blocks:
                    full_h = self._full_height((block_start, block_end))
                    body_h = full_h - CARD_HEADER_HEIGHT
                    # A whole past day is always grayed out; today, each
                    # block grays out individually once ITS end time has
                    # passed, rather than waiting for the whole day to end -
                    # a 10:30-1:30 block should look done-for-the-day by
                    # 9pm even though a 7:30-10:30 block on the same day
                    # hasn't. This only affects the visual cue and new
                    # booking (already blocked separately in
                    # _datetime_at) - existing appointment cards stay fully
                    # clickable regardless, so Admin can still start/end
                    # sessions on a today appointment whose time has passed.
                    is_past = d < today or (d == today and now >= block_end)
                    cards.append({
                        "block_start": block_start,
                        "block_end": block_end,
                        "is_past": is_past,
                        "full": QRectF(x + 2, y, col_width - 4, full_h),
                        "header": QRectF(x + 2, y, col_width - 4, CARD_HEADER_HEIGHT),
                        "body": QRectF(x + 2, y + CARD_HEADER_HEIGHT, col_width - 4, body_h),
                    })
                    y += full_h + CARD_GAP
            self._columns_cards.append(cards)

        # Deliberately NOT calling setMinimumHeight(max_height) here. This
        # widget's on-screen height is meant to be driven purely by the
        # scroll area's viewport (which resizes it to match on every window
        # resize, growing AND shrinking, as long as nothing here constrains
        # it away from that) - self._px_per_min above is solved so max_
        # height lands on whatever that current height already is. Pinning
        # minimumHeight to a computed value used to ratchet upward: once set
        # from a large window, the scroll area would refuse to shrink the
        # widget below it on a later resize-down, so this never got a
        # resize event to rescale from. There's no scrollbar to fall back on
        # for the extreme case where even the 0.5 floor still overflows a
        # very short window either (see the scroll area's setup below) - the
        # grid just renders as tightly as the floor allows and, rarely,
        # slightly clipped, rather than the whole point of this scaling
        # (always fitting, no scrolling) quietly growing an exception.
        self.setMinimumHeight(200)

        self._appt_layout = []
        self._block_layout = []
        for i, d in enumerate(self.columns):
            for card in self._columns_cards[i]:
                block_start, block_end = card["block_start"], card["block_end"]
                body = card["body"]

                card_appts = sorted(
                    [a for a in self.appointments
                     if block_start <= datetime.fromisoformat(a["start_datetime"]) < block_end],
                    key=lambda a: a["start_datetime"],
                )
                clusters = self._cluster(card_appts)

                # Each cluster's own real time span (earliest start .. latest
                # end among its members) is one flexible vertical "slot" in
                # the card; the gaps before/between/after clusters stay
                # exactly time-proportional (SLOT_MIN's own gap rule already
                # keeps those either 0 or a real, deliberate gap - nothing
                # here needs a floor). Giving short slots a minimum height -
                # borrowed from taller neighbors, see _flex_slot_heights -
                # is what keeps a lone 15-minute appointment between two
                # long ones from rendering too short to read.
                cluster_spans = []
                for cluster in clusters:
                    c_start = min(datetime.fromisoformat(a["start_datetime"]) for a in cluster)
                    c_end = max(datetime.fromisoformat(a["end_datetime"]) for a in cluster)
                    cluster_spans.append((c_start, c_end))

                gap_min = 0.0
                prev_end = block_start
                for c_start, c_end in cluster_spans:
                    gap_min += max(0.0, (c_start - prev_end).total_seconds() / 60)
                    prev_end = c_end
                available_for_slots = body.height() - gap_min * self._px_per_min
                slot_heights = self._flex_slot_heights(
                    [(ce - cs).total_seconds() / 60 for cs, ce in cluster_spans],
                    available_for_slots, self._min_chip_height(),
                )

                y_cursor = body.top()
                prev_end = block_start
                for cluster, (c_start, c_end), h_flexed in zip(clusters, cluster_spans, slot_heights):
                    y_cursor += max(0.0, (c_start - prev_end).total_seconds() / 60) * self._px_per_min
                    n = len(cluster)
                    span_min = max(1e-6, (c_end - c_start).total_seconds() / 60)
                    for idx, a in enumerate(cluster):
                        s = datetime.fromisoformat(a["start_datetime"])
                        e = datetime.fromisoformat(a["end_datetime"])
                        if len(self.columns) == 1 and n > 1:
                            # Day view: the single column is wide, so
                            # dividing it evenly by n squeezes every
                            # overlapping appointment into an unreadably
                            # thin strip. Cascade them instead - each stays
                            # wide and readable, offset just enough to show
                            # that they overlap (topmost/last one drawn wins
                            # clicks in the shared region, see _event_at).
                            step = max(24, min(80, body.width() / (n + 1)))
                            cell_w = body.width() - step * (n - 1)
                            x = body.left() + idx * step
                        else:
                            cell_w = body.width() / n
                            x = body.left() + idx * cell_w
                        # Positioned within the cluster's flexed slot,
                        # proportional to this appointment's own offset/
                        # duration within the cluster's real (unflexed) time
                        # span - for the common single-appointment-per-slot
                        # case this simplifies to exactly [y_cursor, y_cursor
                        # + h_flexed].
                        rel_offset = (s - c_start).total_seconds() / 60
                        rel_dur = (e - s).total_seconds() / 60
                        y = y_cursor + (rel_offset / span_min) * h_flexed
                        h = max(6.0, (rel_dur / span_min) * h_flexed)
                        rect = QRectF(x + 1, y + 1, cell_w - 2, h - 2)
                        self._appt_layout.append((rect, a))
                    y_cursor += h_flexed
                    prev_end = c_end

                for b in self.blocked:
                    b_start = datetime.fromisoformat(b["start_datetime"])
                    b_end = datetime.fromisoformat(b["end_datetime"])
                    seg_start = max(b_start, block_start)
                    seg_end = min(b_end, block_end)
                    if seg_end <= seg_start:
                        continue
                    off_start = (seg_start - block_start).total_seconds() / 60
                    off_end = (seg_end - block_start).total_seconds() / 60
                    y1 = body.top() + off_start * self._px_per_min
                    y2 = body.top() + off_end * self._px_per_min
                    rect = QRectF(body.left() + 1, y1 + 1, body.width() - 2, y2 - y1 - 2)
                    self._block_layout.append((rect, b))

    @staticmethod
    def _cluster(day_appts):
        clusters = []
        current = []
        current_end = None
        for a in day_appts:
            s = datetime.fromisoformat(a["start_datetime"])
            e = datetime.fromisoformat(a["end_datetime"])
            if current and s < current_end:
                current.append(a)
                current_end = max(current_end, e)
            else:
                if current:
                    clusters.append(current)
                current = [a]
                current_end = e
        if current:
            clusters.append(current)
        return clusters

    @staticmethod
    def _appt_names(a):
        clients = a.get("clients") if isinstance(a, dict) else a["clients"]
        if clients:
            return ", ".join(format_client_name(c["first_name"], c["last_name"]) for c in clients)
        return format_client_name(a["first_name"], a["last_name"])

    @staticmethod
    def _appt_contact(a):
        clients = a.get("clients") if isinstance(a, dict) else a["clients"]
        if not clients:
            return format_client_name(a["first_name"], a["last_name"])
        return ", ".join(f"{c['first_name']} {c['last_name']}".strip() for c in clients)

    _CARD_FONT_SIZE = 9

    @classmethod
    def _card_font(cls):
        font = QFont()
        font.setBold(True)
        font.setPointSize(cls._CARD_FONT_SIZE)
        return font

    @classmethod
    def _fit_text_to_rect(cls, rect, text):
        """Truncates text (each "\\n"-separated line elided to one line, and
        whole lines dropped from the bottom if there still isn't room) to
        fit rect at the fixed _card_font() size, rather than shrinking the
        font to whatever size happens to fit. A card shrunk short/narrow by
        _px_per_min or overlap-cascading (see _relayout()) then still reads
        at one consistent, easily-spotted size across the whole calendar -
        only the amount of text shown adapts, never how big it looks."""
        fm = QFontMetrics(cls._card_font())
        available = rect.adjusted(4, 2, -4, -2)
        max_lines = max(1, int(available.height() // fm.lineSpacing()))
        lines = text.split("\n")[:max_lines]
        width = max(1, int(available.width()))
        return "\n".join(fm.elidedText(line, Qt.ElideRight, width) for line in lines)

    @classmethod
    def _min_chip_height(cls):
        """Tall enough for the single "Name: time" line a chip normally
        shows, at _card_font()'s fixed size, plus _fit_text_to_rect's own
        top/bottom margins and the 2px the chip's rect always loses to its
        own border inset (see the "h - 2" below) - the floor
        _flex_slot_heights() enforces so a short appointment doesn't render
        squeezed down to less than that."""
        fm = QFontMetrics(cls._card_font())
        return fm.lineSpacing() + 8 + 2

    @staticmethod
    def _flex_slot_heights(durations_min, total_height, min_h):
        """Proportional-to-duration heights for each slot (an appointment,
        or an overlapping cluster of them) within total_height - except no
        slot goes below min_h if that can be avoided. Slots with room to
        spare shrink, proportional to how much slack each has, to make room
        for the ones that would otherwise render unreadably short - so a
        single 15-minute appointment sandwiched between long ones still
        gets enough height to show its time, borrowed evenly from its
        neighbors rather than left squished to whatever its real duration
        alone would draw. Falls back to an even split if honoring the floor
        for every slot isn't possible even after shrinking everything else
        as far as it'll go."""
        n = len(durations_min)
        if n == 0:
            return []
        total_duration = sum(durations_min)
        if total_duration <= 0 or total_height <= 0:
            return [max(0.0, total_height) / n] * n
        scale = total_height / total_duration
        heights = [max(d * scale, min_h) for d in durations_min]
        over = sum(heights) - total_height
        if over <= 0:
            return heights
        shrinkable = [i for i in range(n) if heights[i] > min_h]
        total_excess = sum(heights[i] - min_h for i in shrinkable)
        if not shrinkable or total_excess <= over:
            return [total_height / n] * n
        for i in shrinkable:
            excess = heights[i] - min_h
            heights[i] -= over * (excess / total_excess)
        return heights

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))

        today = date.today()
        now = datetime.now()

        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(9)

        for i, d in enumerate(self.columns):
            cards = self._columns_cards[i]
            if not cards:
                col_width = self._col_width()
                x = i * col_width
                p.setPen(QPen(QColor("#94a3b8")))
                p.drawText(QRectF(x, CARD_TOP_MARGIN, col_width, 30), Qt.AlignCenter, "Closed")
                continue

            for card in cards:
                is_past = card["is_past"]
                # Neutral gray, not blue - blue is reserved for scheduled
                # appointment cards, and this header (an empty bookable
                # slot) looking the same color read as a scheduled booking.
                header_color = QColor("#f1f5f9")
                text_color = QColor("#94a3b8") if is_past else QColor("#64748b")

                # Header fill first (rounded top corners only, via the half-rect trick)...
                p.setBrush(QBrush(header_color))
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(card["header"], CARD_RADIUS, CARD_RADIUS)
                p.drawRect(QRectF(card["header"].left(), card["header"].center().y(),
                                   card["header"].width(), card["header"].height() / 2))

                # ...then the card border stroke on top, so it stays crisp over the header too.
                p.setPen(QPen(QColor("#cbd5e1"), 1))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(card["full"], CARD_RADIUS, CARD_RADIUS)

                p.setPen(QPen(text_color))
                p.setFont(header_font)
                label = f"{format_12h(card['block_start'])} – {format_12h(card['block_end'])}"
                p.drawText(card["header"], Qt.AlignCenter, label)

                # Soft gridlines every 30 min, no labels
                p.setPen(QPen(QColor("#f1f5f9")))
                minutes = 30
                total_minutes = (card["block_end"] - card["block_start"]).total_seconds() / 60
                while minutes < total_minutes:
                    y = card["body"].top() + minutes * self._px_per_min
                    p.drawLine(int(card["body"].left()), int(y), int(card["body"].right()), int(y))
                    minutes += 30

                # Gray wash over whatever part of this card is already
                # unbookable, under any appointments/blocks drawn later so
                # those stay legible. A fully past day washes the whole
                # body; today washes only the elapsed portion (block_start
                # up to now) - without this, a block that straddles "now"
                # (is_past is False as long as any of it is still ahead)
                # showed no wash at all, so its already-elapsed minutes
                # looked exactly as bookable as the time still ahead, even
                # though clicking there silently did nothing (see
                # _datetime_at's own "today's already-passed hours aren't
                # clickable either" check).
                if d < today:
                    p.fillRect(card["body"], QColor(203, 213, 225, 90))
                elif d == today:
                    elapsed_end = min(now, card["block_end"])
                    if elapsed_end > card["block_start"]:
                        elapsed_min = (elapsed_end - card["block_start"]).total_seconds() / 60
                        elapsed_h = elapsed_min * self._px_per_min
                        elapsed_rect = QRectF(
                            card["body"].left(), card["body"].top(),
                            card["body"].width(), elapsed_h,
                        )
                        p.fillRect(elapsed_rect, QColor(203, 213, 225, 90))

        # Blocked times - a plain bordered card exactly bounding the blocked
        # range (previously a diagonal hatch pattern that, on a short/wide
        # slot, packed into a dense, messy-looking stripe).
        for rect, b in self._block_layout:
            p.setBrush(QBrush(QColor("#e2e8f0")))
            p.setPen(QPen(QColor("#94a3b8"), 1))
            p.drawRoundedRect(rect, 4, 4)
            if rect.height() >= 18:
                text = f"Blocked: {b['reason']}"
                p.setPen(QPen(QColor("#475569")))
                p.setFont(self._card_font())
                p.drawText(rect.adjusted(4, 2, -4, -2), Qt.AlignLeft | Qt.AlignTop,
                           self._fit_text_to_rect(rect, text))

        # Appointments - a soft tint card (bg/border/text triple) rather than
        # a solid saturated block, except during the "alert" half of a
        # conflict flash, which stays solid red for visibility.
        for rect, a in self._appt_layout:
            conflicted = a["id"] in self._conflicting_ids
            flash_alert = conflicted and not self._conflict_flash_on
            if flash_alert:
                fill, text_color = QColor("#ef4444"), QColor("#ffffff")
            else:
                bg_hex, _, text_hex = STATUS_STYLES.get(a["status"], ("#f8fafc", "#e2e8f0", "#1e293b"))
                fill, text_color = QColor(bg_hex), QColor(text_hex)
            border = QColor("#b91c1c") if conflicted else fill.darker(115)
            p.setBrush(QBrush(fill))
            p.setPen(QPen(border, 3 if conflicted else 1))
            p.drawRoundedRect(rect, 6, 6)
            p.setPen(QPen(text_color))
            s = datetime.fromisoformat(a["start_datetime"])
            # Day view has a full-width column to itself, so the chip can
            # afford to spell out the whole start-end range instead of just
            # the start time - week view's 7-way-split columns stay with
            # just the start, where a full range would crowd out the name.
            if len(self.columns) == 1:
                e = datetime.fromisoformat(a["end_datetime"])
                when = f"{format_12h(s)} – {format_12h(e)}"
            else:
                when = format_12h(s)
            # "Name: time" on one line rather than two - saves enough
            # vertical room per chip that more appointments fit without
            # needing to shrink _min_chip_height()'s floor, or scroll (this
            # grid never scrolls - see the scroll area's setup). A freshly-
            # scheduled appointment just needs who + when - the blue color
            # already says "Scheduled"; the other statuses are less
            # visually self-evident so keep the explicit label for them.
            if a["status"] == "scheduled":
                text = f"{self._appt_contact(a)}: {when}"
            else:
                text = f"{self._appt_contact(a)}: {when} · {STATUS_LABELS.get(a['status'], a['status'])}"
            if conflicted:
                text += "\n⚠ Reschedule - conflicts with blocked time"
            p.setFont(self._card_font())
            p.drawText(rect.adjusted(4, 2, -4, -2), Qt.AlignLeft | Qt.AlignTop,
                       self._fit_text_to_rect(rect, text))

        p.end()

    def _event_at(self, pos):
        # Reversed so a cascaded/overlapping card drawn on top (later in the
        # list) wins the click over the one it partially covers.
        for rect, a in reversed(self._appt_layout):
            if rect.contains(pos):
                return "appt", a
        for rect, b in self._block_layout:
            if rect.contains(pos):
                return "block", b
        return None, None

    def mousePressEvent(self, event):
        pos = event.position() if hasattr(event, "position") else event.localPos()
        kind, obj = self._event_at(pos)
        if event.button() == Qt.LeftButton:
            if kind == "appt":
                self.appt_clicked.emit(obj)
                return
            if kind == "block":
                self.block_clicked.emit(obj)
                return
            dt = self._datetime_at(pos)
            if dt:
                self.slot_clicked.emit(dt)
        elif event.button() == Qt.RightButton:
            if kind is None:
                dt = self._datetime_at(pos)
                if dt:
                    self.block_time_requested.emit(dt)

    def _datetime_at(self, pos):
        col_width = self._col_width()
        i = int(pos.x() / col_width)
        if i < 0 or i >= len(self.columns):
            return None
        if self.columns[i] < date.today():
            return None  # past days are not clickable for booking
        for card in self._columns_cards[i]:
            if card["body"].contains(pos):
                offset_min = (pos.y() - card["body"].top()) / self._px_per_min
                snapped = round(offset_min / SLOT_MIN) * SLOT_MIN
                snapped = max(0, snapped)
                candidate = card["block_start"] + timedelta(minutes=snapped)
                if self.columns[i] == date.today() and candidate < datetime.now():
                    return None  # today's already-passed hours aren't clickable either
                return candidate
        return None


class CalendarView(QWidget):
    def __init__(self, parent=None, require_admin=None, require_session_admin=None):
        super().__init__(parent)
        self.require_admin = require_admin or (lambda: True)
        self.require_session_admin = require_session_admin or self.require_admin
        self.mode = "week"
        self.anchor_date = date.today()
        self._next_available = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(10)

        toolbar_card = QFrame()
        toolbar_card.setObjectName("toolbarCard")
        toolbar_card.setStyleSheet(
            "#toolbarCard { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 12px; }"
        )
        toolbar = QHBoxLayout(toolbar_card)
        toolbar.setContentsMargins(14, 11, 14, 11)
        toolbar.setSpacing(8)

        # Segmented Month/Week toggle, in place of a two-item dropdown - the
        # current mode is always visible at a glance instead of hidden
        # behind a closed combo box.
        segmented = QFrame()
        segmented.setObjectName("modeSegmented")
        segmented.setStyleSheet(
            "#modeSegmented { background: #f1f5f9; border-radius: 8px; }"
            "#modeSegmented QPushButton { background: transparent; border: 1px solid transparent; "
            "padding: 5px 13px; border-radius: 6px; color: #64748b; font-size: 12px; }"
            "#modeSegmented QPushButton:checked { background: #ffffff; color: #1e293b; "
            "font-weight: 600; border: 1px solid #e2e8f0; }"
        )
        seg_layout = QHBoxLayout(segmented)
        seg_layout.setContentsMargins(3, 3, 3, 3)
        seg_layout.setSpacing(2)
        self.day_btn = QPushButton("Day")
        self.week_btn = QPushButton("Week")
        self.month_btn = QPushButton("Month")
        self._mode_group = QButtonGroup(segmented)
        self._mode_group.setExclusive(True)
        for btn in (self.day_btn, self.week_btn, self.month_btn):
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            _never_shrink(btn)
            self._mode_group.addButton(btn)
            seg_layout.addWidget(btn)
        # Set the initial checked state before wiring up toggled - connecting
        # first would fire _set_mode()/refresh() immediately, before the rest
        # of this view (next_available_label, scroll, month_view, etc.) has
        # been constructed yet.
        self.week_btn.setChecked(True)
        self.day_btn.toggled.connect(lambda checked: checked and self._set_mode("Day"))
        self.month_btn.toggled.connect(lambda checked: checked and self._set_mode("Month"))
        self.week_btn.toggled.connect(lambda checked: checked and self._set_mode("Week"))
        toolbar.addWidget(segmented)

        prev_btn = QPushButton("‹")
        prev_btn.setFixedWidth(34)
        prev_btn.setStyleSheet("font-size: 16px; font-weight: 600;")
        prev_btn.clicked.connect(self._go_prev)
        toolbar.addWidget(prev_btn)

        # Today / Go to Date - the same segmented-toggle look as Day/Week/
        # Month above, so it reads as one consistent pattern rather than a
        # plain button next to a fancier control. "Today" jumps straight
        # there; "Go to Date" opens a calendar dropdown to jump to any other
        # date. Whichever matches the calendar's current anchor date shows
        # as active - see _sync_today_toggle(), called from refresh() so
        # this stays correct no matter how the anchor date got there
        # (prev/next, a month click, search, ...), not just clicks here.
        today_segmented = QFrame()
        today_segmented.setObjectName("modeSegmented")
        today_segmented.setStyleSheet(segmented.styleSheet())
        today_seg_layout = QHBoxLayout(today_segmented)
        today_seg_layout.setContentsMargins(3, 3, 3, 3)
        today_seg_layout.setSpacing(2)
        self.today_seg_btn = QPushButton("Today")
        self.goto_seg_btn = QPushButton("Go to Date")
        self._today_group = QButtonGroup(today_segmented)
        self._today_group.setExclusive(True)
        for btn in (self.today_seg_btn, self.goto_seg_btn):
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            _never_shrink(btn)
            self._today_group.addButton(btn)
            today_seg_layout.addWidget(btn)
        self.today_seg_btn.setChecked(True)
        self.today_seg_btn.clicked.connect(self._go_today)
        self.goto_seg_btn.clicked.connect(self._show_goto_calendar)
        self._goto_menu = None
        toolbar.addWidget(today_segmented)

        next_btn = QPushButton("›")
        next_btn.setFixedWidth(34)
        next_btn.setStyleSheet("font-size: 16px; font-weight: 600;")
        next_btn.clicked.connect(self._go_next)
        toolbar.addWidget(next_btn)

        self.range_label = QLabel("")
        self.range_label.setStyleSheet(
            "font-weight: 700; font-size: 14px; color: #1e293b; "
            "background: #f1f5f9; border-radius: 8px; padding: 7px 16px; margin-left: 8px;"
        )
        _never_shrink(self.range_label)
        toolbar.addWidget(self.range_label)
        toolbar.addStretch()

        search_btn = QPushButton("🔍 Search Appointment")
        search_btn.clicked.connect(self._open_search)
        _never_shrink(search_btn)
        toolbar.addWidget(search_btn)

        add_btn = QPushButton("📅 Schedule Appointment")
        add_btn.setObjectName("primaryButton")
        add_btn.clicked.connect(lambda: self._open_appointment(None))
        _never_shrink(add_btn)
        toolbar.addWidget(add_btn)

        outer.addWidget(toolbar_card)

        self.next_available_label = ClickableLabel("")
        self.next_available_label.setCursor(Qt.PointingHandCursor)
        self.next_available_label.setStyleSheet(
            "background: #eff6ff; color: #1d4ed8; font-weight: 600; "
            "padding: 9px 14px; border-radius: 10px; border: 1px solid #dbeafe;"
        )
        self.next_available_label.clicked.connect(self._jump_to_next_available)
        outer.addWidget(self.next_available_label)

        split_row = QHBoxLayout()
        split_row.setContentsMargins(0, 0, 0, 0)
        split_row.setSpacing(10)

        grid_container = QWidget()
        grid_col = QVBoxLayout(grid_container)
        grid_col.setContentsMargins(0, 0, 0, 0)
        grid_col.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        self.header = DayHeaderWidget()
        header_row.addWidget(self.header)
        grid_col.addLayout(header_row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        # No vertical scrollbar, ever - TimeGridWidget._relayout() solves
        # for whatever pixels-per-minute scale makes the whole business-
        # hours grid fit the viewport exactly, so there's nothing to scroll
        # to. (A scrollbar reserved via AlwaysOn used to be needed here to
        # keep the header row - outside the scroll area, always full width -
        # aligned with the grid's viewport width, back when the grid could
        # still end up taller than the viewport and need one; now that it
        # never does, there's no width to compensate for either.)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid = TimeGridWidget()
        self.scroll.setWidget(self.grid)
        grid_col.addWidget(self.scroll)

        self.grid.slot_clicked.connect(self._on_slot_clicked)
        self.grid.appt_clicked.connect(self._open_appointment)
        self.grid.block_clicked.connect(self._on_block_clicked)
        self.grid.block_time_requested.connect(self._open_block_dialog)

        split_row.addWidget(grid_container, 3)

        # Day-mode-only panel: a plain, readable list of the day's
        # appointments (time, client, status) alongside the time grid - the
        # grid's small cards are fine for a week-at-a-glance but too cramped
        # to read a single day's schedule at a glance.
        self.day_list_panel = QFrame()
        self.day_list_panel.setObjectName("dayListPanel")
        self.day_list_panel.setMinimumWidth(380)
        self.day_list_panel.setStyleSheet(
            "#dayListPanel { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 12px; }"
        )
        day_list_col = QVBoxLayout(self.day_list_panel)
        day_list_col.setContentsMargins(14, 12, 14, 12)
        day_list_col.setSpacing(8)
        self.day_list_title = QLabel("Today's Appointments")
        self.day_list_title.setStyleSheet("font-weight: 700; font-size: 12pt; color: #1e293b;")
        day_list_col.addWidget(self.day_list_title)
        self.day_list = QListWidget()
        self.day_list.setStyleSheet(
            "QListWidget { border: none; } "
            "QListWidget::item { border-bottom: 1px solid #f1f5f9; } "
            "QListWidget::item:selected { background: #eff6ff; }"
        )
        self.day_list.itemClicked.connect(self._on_day_list_item_clicked)
        day_list_col.addWidget(self.day_list)
        split_row.addWidget(self.day_list_panel, 2)
        self.day_list_panel.hide()

        # Each row's client-name text is elided to fit whatever room is left
        # after the time and status pill reserve their own real (measured,
        # never-shrunk) widths - see _build_day_row() - so it needs to be
        # recomputed whenever the list's actual width changes, not just on
        # the next data refresh.
        self._last_day_list_args = None
        self._populating_day_list = False
        self.day_list.viewport().installEventFilter(self)

        # Wrapped in its own widget (rather than adding split_row to outer
        # directly) so the whole week/day area can be hidden as one unit in
        # Month mode - hiding only its individual children left this row's
        # own margins/spacing still reserved, pushing the month grid down
        # with a big blank gap above it.
        self.week_day_container = QWidget()
        self.week_day_container.setLayout(split_row)
        outer.addWidget(self.week_day_container, 1)

        # The month grid reads as a clean, centered card - rounded corners,
        # a visible border, and breathing room on both sides - rather than
        # a flat rectangle stretched edge-to-edge across the whole window.
        # Capped at a max width so it stays a comfortable reading size even
        # on a very wide window, instead of stretching absurdly wide.
        month_card = QFrame()
        month_card.setObjectName("monthCard")
        month_card.setStyleSheet(
            "#monthCard { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 14px; }"
        )
        month_card.setMinimumWidth(920)
        month_card.setMaximumWidth(1220)
        # Expanding (not the QFrame default of Preferred) so this card - and
        # so month_view, the one thing inside it given a stretch factor
        # below - actually grows to fill whatever vertical room outer/
        # month_container hands it, instead of settling for its children's
        # bare minimum height and leaving the grid's bottom rows cut off
        # against the bottom of a shorter (non-maximized) window.
        month_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        month_card_layout = QVBoxLayout(month_card)
        month_card_layout.setContentsMargins(14, 14, 14, 14)
        month_card_layout.setSpacing(10)

        self.month_header_label = QLabel("")
        self.month_header_label.setAlignment(Qt.AlignCenter)
        self.month_header_label.setStyleSheet("font-size: 19px; font-weight: 700; color: #1e293b;")
        month_card_layout.addWidget(self.month_header_label)

        self.month_view = MonthGridWidget()
        self.month_view.day_clicked.connect(self._on_month_day_clicked)
        month_card_layout.addWidget(self.month_view, 1)

        month_row = QHBoxLayout()
        month_row.addStretch()
        month_row.addWidget(month_card)
        month_row.addStretch()
        self.month_container = QWidget()
        self.month_container.setLayout(month_row)
        outer.addWidget(self.month_container, 1)

        # Deliberately NOT calling self.refresh() here. This widget is
        # constructed while the main window is still off-screen, before
        # it's been laid out to its real on-screen size (its width is a
        # transitional, too-small placeholder at this point - verified
        # directly: ~640px here vs. the ~1176px it actually ends up at).
        # month_view/grid paint themselves using their live width, so
        # populating them now would produce one visibly squished/misaligned
        # frame that lingers until something later forces a repaint at the
        # correct size. MainWindow.showEvent() does the first refresh()
        # once this view is actually on-screen at its true size instead.

    # ---- navigation ----
    def _set_mode(self, word):
        self.mode = word.lower()
        self.refresh()

    def _go_prev(self):
        if self.mode == "day":
            self.anchor_date -= timedelta(days=1)
        elif self.mode == "week":
            self.anchor_date -= timedelta(days=7)
        else:
            self.anchor_date = self._add_months(self.anchor_date, -1)
        self.refresh()

    def _go_next(self):
        if self.mode == "day":
            self.anchor_date += timedelta(days=1)
        elif self.mode == "week":
            self.anchor_date += timedelta(days=7)
        else:
            self.anchor_date = self._add_months(self.anchor_date, 1)
        self.refresh()

    def _go_today(self):
        self.anchor_date = date.today()
        self.refresh()

    def _show_goto_calendar(self):
        menu = QMenu(self.goto_seg_btn)
        calendar = QCalendarWidget(menu)
        calendar.setGridVisible(True)
        calendar.setSelectedDate(self.anchor_date)
        calendar.clicked.connect(self._on_goto_date_picked)
        # If the popup is dismissed without picking a date (e.g. Esc, click
        # outside), the toggle still needs to reflect the real anchor date
        # rather than being left stuck on "Go to Date".
        menu.aboutToHide.connect(self._sync_today_toggle)
        action = QWidgetAction(menu)
        action.setDefaultWidget(calendar)
        menu.addAction(action)
        self._goto_menu = menu
        menu.exec(self.goto_seg_btn.mapToGlobal(self.goto_seg_btn.rect().bottomLeft()))

    def _on_goto_date_picked(self, qdate):
        # Same view/mode as before the jump - only the anchor date moves,
        # exactly like the "Today" jump.
        self.anchor_date = date(qdate.year(), qdate.month(), qdate.day())
        self.refresh()
        if self._goto_menu:
            self._goto_menu.close()

    def _sync_today_toggle(self):
        is_today = self.anchor_date == date.today()
        self.today_seg_btn.blockSignals(True)
        self.goto_seg_btn.blockSignals(True)
        self.today_seg_btn.setChecked(is_today)
        self.goto_seg_btn.setChecked(not is_today)
        self.today_seg_btn.blockSignals(False)
        self.goto_seg_btn.blockSignals(False)

    @staticmethod
    def _add_months(d, delta):
        month = d.month - 1 + delta
        year = d.year + month // 12
        month = month % 12 + 1
        return date(year, month, 1)

    def _columns_for_range(self):
        if self.mode == "day":
            return [self.anchor_date]
        ws = week_start(self.anchor_date)
        return [ws + timedelta(days=i) for i in range(7)]

    # ---- data refresh ----
    def refresh(self):
        self._sync_today_toggle()
        self._refresh_next_available()
        if self.mode == "month":
            self._show_month()
            return
        self.week_day_container.show()
        self.scroll.show()
        self.header.show()
        self.month_container.hide()
        self.day_list_panel.setVisible(self.mode == "day")
        columns = self._columns_for_range()
        range_start = datetime.combine(columns[0], time(0, 0))
        range_end = datetime.combine(columns[-1], time(0, 0)) + timedelta(days=1)
        appts = models.list_appointments_between(range_start, range_end)
        blocked = models.list_blocked_between(range_start, range_end)
        self.header.set_columns(columns)
        self.grid.set_data(columns, appts, blocked)
        if self.mode == "day":
            self.range_label.setText(columns[0].strftime("%A, %b %d, %Y"))
            self.day_list_title.setText(
                "Today's Appointments" if columns[0] == date.today()
                else f"Appointments — {columns[0].strftime('%a, %b %d')}"
            )
            self._populate_day_list(columns[0], appts, blocked)
        else:
            self.range_label.setText(f"{columns[0].strftime('%b %d')} – {columns[-1].strftime('%b %d, %Y')}")

    def _populate_day_list(self, day, appts, blocked):
        # Reentrancy guard: clear()/addItem() below can change how many rows
        # need scrolling, which can toggle the scrollbar and so resize
        # day_list's viewport - which the eventFilter below responds to by
        # calling straight back into this same method. Without this guard
        # that reentrant call lands mid-clear()/mid-populate on the same
        # QListWidget, which is exactly the kind of self-mutation-while-
        # iterating Qt doesn't handle gracefully (this was crashing the
        # whole app, not raising a catchable Python exception).
        if self._populating_day_list:
            return
        self._populating_day_list = True
        try:
            self._last_day_list_args = (day, appts, blocked)
            self.day_list.clear()
            entries = [(datetime.fromisoformat(a["start_datetime"]), "appt", a) for a in appts]
            for b in blocked:
                b_start = datetime.fromisoformat(b["start_datetime"])
                b_end = datetime.fromisoformat(b["end_datetime"])
                day_start = datetime.combine(day, time(0, 0))
                day_end = day_start + timedelta(days=1)
                if b_start < day_end and b_end > day_start:
                    entries.append((max(b_start, day_start), "block", b))
            entries.sort(key=lambda t: t[0])

            if not entries:
                empty = QListWidgetItem("No appointments or blocked time today.")
                empty.setFlags(Qt.NoItemFlags)
                self.day_list.addItem(empty)
                return

            for _, kind, obj in entries:
                item = QListWidgetItem()
                item.setData(Qt.UserRole, (kind, obj))
                row = self._build_day_row(kind, obj)
                # setFixedHeight(), not just setSizeHint(hint) on the item -
                # a plain QWidget's default vertical size policy (Preferred)
                # lets QListWidget's own item-widget embedding shrink it
                # below its sizeHint (measured directly: an unfixed row
                # consistently got squeezed several px shorter than its own
                # sizeHint once actually embedded, clipping the pill's
                # padding worst of all since it needed the most height).
                # Fixed makes that height non-negotiable, so the row is
                # embedded at exactly the size its own content asked for.
                hint = row.sizeHint()
                row.setFixedHeight(hint.height())
                item.setSizeHint(hint)
                self.day_list.addItem(item)
                self.day_list.setItemWidget(item, row)
        finally:
            self._populating_day_list = False

    def _build_day_row(self, kind, obj):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(6, 8, 6, 8)
        layout.setSpacing(10)

        if kind == "block":
            b_start = datetime.fromisoformat(obj["start_datetime"])
            b_end = datetime.fromisoformat(obj["end_datetime"])
            time_label = QLabel(f"{format_12h(b_start)} – {format_12h(b_end)}")
            time_label.setStyleSheet("font-weight: 700; color: #64748b; min-width: 130px;")
            reason_label = QLabel(f"Blocked: {obj['reason']}")
            reason_label.setStyleSheet("color: #64748b; font-style: italic;")
            layout.addWidget(time_label)
            layout.addWidget(reason_label, 1)
            return row

        a = obj
        s = datetime.fromisoformat(a["start_datetime"])
        e = datetime.fromisoformat(a["end_datetime"])
        time_label = QLabel(f"{format_12h(s)} – {format_12h(e)}")
        time_label.setStyleSheet("font-weight: 700; color: #1e293b;")

        bg, border, text_color = STATUS_STYLES.get(a["status"], ("#f8fafc", "#e2e8f0", "#1e293b"))
        pill = QLabel(STATUS_LABELS.get(a["status"], a["status"]))
        pill.setStyleSheet(
            f"background: {bg}; color: {text_color}; border: 1px solid {border}; "
            "border-radius: 10px; padding: 3px 12px; font-weight: 600; font-size: 9pt;"
        )
        pill.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        name_label = QLabel()
        name_label.setStyleSheet("font-weight: 600; color: #1e293b;")
        # Elided to whatever room is actually left after the time label and
        # the pill - both measured with their own real fontMetrics, never
        # shrunk - take theirs, rather than a hand-picked pixel guess. A
        # fixed guess is what let the pill keep getting squeezed off the
        # edge: on this list, actual rendered widths (this system's fonts,
        # this window's width) are always somewhat different from whatever
        # was assumed while writing the code.
        full_name = TimeGridWidget._appt_contact(a)
        margins = layout.contentsMargins()
        reserved = (
            margins.left() + margins.right()
            + time_label.sizeHint().width() + layout.spacing()
            + pill.sizeHint().width() + layout.spacing()
        )
        avail_for_name = max(40, self.day_list.viewport().width() - reserved)
        elided = name_label.fontMetrics().elidedText(full_name, Qt.ElideRight, avail_for_name)
        name_label.setText(elided)
        if elided != full_name:
            name_label.setToolTip(full_name)

        layout.addWidget(time_label)
        layout.addWidget(name_label)
        layout.addStretch()
        layout.addWidget(pill)
        return row

    def eventFilter(self, obj, event):
        if obj is self.day_list.viewport() and event.type() == QEvent.Resize:
            if self.mode == "day" and self._last_day_list_args:
                # Deferred, not called straight away: this resize can itself
                # be a side effect of _populate_day_list() still running
                # (clear()/addItem() changing whether the scrollbar shows,
                # which resizes the viewport right back at us) - calling
                # back in synchronously would re-enter it mid-build, which
                # used to crash the app outright (the reentrancy guard in
                # _populate_day_list now blocks that specific case, but
                # silently dropping this call meant the row widths computed
                # during that first, still-mid-populate pass were the ones
                # left on screen - built against the viewport's width from
                # *before* the scrollbar finished toggling, not the settled
                # width after. Deferring to the next event-loop tick always
                # runs after the current populate has fully finished, so
                # name-eliding gets recomputed against the real, final
                # width instead of leaving it stale.
                QTimer.singleShot(0, self._repopulate_day_list_if_still_relevant)
        return super().eventFilter(obj, event)

    def _repopulate_day_list_if_still_relevant(self):
        if self.mode == "day" and self._last_day_list_args:
            self._populate_day_list(*self._last_day_list_args)

    def _on_day_list_item_clicked(self, item):
        data = item.data(Qt.UserRole)
        if not data:
            return
        kind, obj = data
        if kind == "appt":
            self._open_appointment(obj)
        else:
            self._on_block_clicked(obj)

    def _show_month(self):
        self.week_day_container.hide()
        self.month_container.show()
        first = date(self.anchor_date.year, self.anchor_date.month, 1)
        self.month_view.set_month(self.anchor_date.year, self.anchor_date.month)
        self.range_label.setText(first.strftime("%B %Y"))
        self.month_header_label.setText(first.strftime("%B %Y"))

    def _on_month_day_clicked(self, d):
        # Both past and future days route to the day view: future days can
        # be booked there, past days are view-only (spec 7.1 / 8).
        # Deliberately delayed a beat rather than switching the instant the
        # click lands - jumping straight from a whole month to one day read
        # as jarring/disorienting. MonthGridWidget's pressed-cell highlight
        # covers the pause so the click still reads as immediately
        # registered, not as nothing having happened for a moment.
        QTimer.singleShot(220, lambda: self._switch_to_day_view(d))

    def _switch_to_day_view(self, d):
        self.anchor_date = d
        self.mode = "day"
        self.day_btn.blockSignals(True)
        self.day_btn.setChecked(True)
        self.day_btn.blockSignals(False)
        self.refresh()

    def _jump_to_next_available(self):
        if not self._next_available:
            return
        start, _end = self._next_available
        self._navigate_to(start.date())

    def _navigate_to(self, d):
        """Switch to week view on date d and refresh - no highlight/flash,
        just scrolls the calendar there."""
        self.anchor_date = d
        self.mode = "week"
        self.week_btn.blockSignals(True)
        self.week_btn.setChecked(True)
        self.week_btn.blockSignals(False)
        self.refresh()

    def _refresh_next_available(self):
        result = scheduling.find_next_open_slot(datetime.now())
        self._next_available = result
        if not result:
            self.next_available_label.setText("✦ Next Available Appointment: none found in the next 60 days")
            return
        start, _ = result
        when = start.strftime("%a, %b %d") + f" at {format_12h(start)}"
        self.next_available_label.setText(f"✦ Next Available Appointment: {when}")

    # ---- interactions ----
    def _on_slot_clicked(self, dt):
        self._open_appointment(None, start_dt=dt)

    def _open_search(self):
        from ui.search_dialog import AppointmentSearchDialog
        dlg = AppointmentSearchDialog(self)
        if dlg.exec() and dlg.selected_appt:
            appt = dlg.selected_appt
            d = datetime.fromisoformat(appt["start_datetime"]).date()
            self.anchor_date = d
            self.mode = "day"
            self.day_btn.blockSignals(True)
            self.day_btn.setChecked(True)
            self.day_btn.blockSignals(False)
            self.refresh()
            # Re-fetch rather than reuse the dialog's bundle - status/clients
            # could only be stale here if something else changed the
            # appointment in the moment the search dialog was open.
            fresh = models.get_appointment(appt["id"])
            if fresh:
                self._open_appointment(fresh)

    def _open_appointment(self, appt_row, start_dt=None):
        from ui.appointment_dialog import AppointmentDialog
        dlg = AppointmentDialog(
            self, appt_row=appt_row, start_dt=start_dt,
            require_admin=self.require_admin, require_session_admin=self.require_session_admin,
        )
        if dlg.exec() and dlg.result_changed:
            if dlg.saved_start_dt is not None:
                # A create/reschedule just landed on a specific date/time -
                # navigate the calendar there instead of just refreshing in
                # place, so the appointment that was just scheduled is
                # immediately visible. No flash overlay here (that's
                # specific to the "Next Available Appointment" jump).
                self._navigate_to(dlg.saved_start_dt.date())
            else:
                self.refresh()

    def _on_block_clicked(self, block_row):
        if QMessageBox.question(
            self, "Blocked Time", f"Reason: {block_row['reason']}\n\nRemove this blocked time?"
        ) == QMessageBox.Yes:
            if self.require_admin():
                models.delete_blocked_time(block_row["id"])
                self.refresh()

    def _open_block_dialog(self, dt):
        if not self.require_admin():
            return
        from ui.block_time_dialog import BlockTimeDialog
        dlg = BlockTimeDialog(self, start_dt=dt)
        if dlg.exec():
            self.refresh()
