from datetime import date, datetime, time, timedelta
import calendar as calendar_module

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont

from app import models

DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

STATUS_COLORS = {
    "scheduled": QColor("#3b82f6"),
    "in_process": QColor("#f59e0b"),
    "completed": QColor("#22a35d"),
    "cancelled": QColor("#9ca3af"),
    "no_show": QColor("#dc2626"),
}

HEADER_H = 32
BADGE_SIZE = 24


class MonthGridWidget(QWidget):
    """A real wall-calendar month grid. Every day routes to the week view
    (see CalendarView) - future days can be booked there, past days are
    grayed out here and view-only there."""

    day_clicked = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.year = date.today().year
        self.month = date.today().month
        self.cells = []       # list of date objects, len == rows*7
        self.appts_by_day = {}
        self.blocked_days = set()
        self._hover_idx = None
        self._pressed_idx = None
        # A floor to keep day cells from becoming unreadably squashed, not a
        # size the grid insists on - _cell_rect() already lays cells out
        # from self.height() directly, so it's fine with less. Kept modest
        # (rather than the ~520px a maximized window comfortably fit) so a
        # normal, non-maximized window height doesn't force this grid taller
        # than the space actually available and get its bottom rows cut off.
        self.setMinimumHeight(280)
        self.setMouseTracking(True)

    def set_month(self, year, month):
        self.year, self.month = year, month
        first = date(year, month, 1)
        start = first - timedelta(days=(first.weekday() + 1) % 7)  # back up to Sunday
        last_day = calendar_module.monthrange(year, month)[1]
        last = date(year, month, last_day)
        end = last + timedelta(days=(6 - (last.weekday() + 1) % 7))
        self.cells = []
        d = start
        while d <= end:
            self.cells.append(d)
            d += timedelta(days=1)

        range_start = datetime.combine(start, time(0, 0))
        range_end = datetime.combine(end, time(0, 0)) + timedelta(days=1)
        appts = models.list_appointments_between(range_start, range_end)
        self.appts_by_day = {}
        for a in appts:
            d = datetime.fromisoformat(a["start_datetime"]).date()
            self.appts_by_day.setdefault(d, []).append(a)
        for lst in self.appts_by_day.values():
            lst.sort(key=lambda a: a["start_datetime"])

        blocked = models.list_blocked_between(range_start, range_end)
        self.blocked_days = set()
        for b in blocked:
            bs = datetime.fromisoformat(b["start_datetime"]).date()
            be = datetime.fromisoformat(b["end_datetime"]).date()
            d = bs
            while d <= be:
                self.blocked_days.add(d)
                d += timedelta(days=1)

        self._hover_idx = None
        self._pressed_idx = None
        self.update()

    def _rows(self):
        return max(1, len(self.cells) // 7)

    def _cell_rect(self, idx):
        rows = self._rows()
        col_w = self.width() / 7
        row_h = (self.height() - HEADER_H) / rows
        row, col = divmod(idx, 7)
        return QRectF(col * col_w, HEADER_H + row * row_h, col_w, row_h)

    def _is_past(self, d):
        return d < date.today()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))

        col_w = self.width() / 7

        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(9)
        p.setFont(header_font)
        p.setPen(QPen(QColor("#64748b")))
        for i, name in enumerate(DAY_NAMES):
            p.drawText(QRectF(i * col_w, 0, col_w, HEADER_H), Qt.AlignCenter, name.upper())
        p.setPen(QPen(QColor("#94a3b8"), 2))
        p.drawLine(0, HEADER_H, int(self.width()), HEADER_H)

        today = date.today()
        num_font = QFont()
        num_font.setPointSize(10)
        chip_font = QFont()
        chip_font.setPointSize(8)

        for idx, d in enumerate(self.cells):
            rect = self._cell_rect(idx)
            in_month = d.month == self.month
            is_today = d == today
            is_past = self._is_past(d)
            # Past days aren't clickable for new bookings, so they're never
            # given the hover highlight that signals "you can click this".
            is_hover = idx == self._hover_idx and in_month and not is_past
            is_pressed = idx == self._pressed_idx

            bg = QColor("#ffffff") if in_month else QColor("#f8fafc")
            if is_past and in_month:
                # A single flat tint reads clearly as "past" on its own -
                # the extra wash this used to layer on top just made whole
                # weeks look heavy/muddy once "today" was late in the month.
                bg = QColor("#eef1f6")
            if is_hover:
                bg = QColor("#eff6ff")
            if is_pressed:
                # A stronger, more saturated fill than the hover tint - the
                # switch to Day view is deliberately delayed a beat (see
                # CalendarView._on_month_day_clicked), so this needs to read
                # as "your click registered, hang on" for that whole pause
                # rather than the page just sitting there looking unclicked.
                bg = QColor("#bfdbfe")
            p.fillRect(rect, bg)

            if d in self.blocked_days:
                p.fillRect(rect.adjusted(2, 2, -2, -2), QColor(226, 232, 240, 140))

            # Brushes set by earlier iterations (today's badge circle, chip
            # fills) must not leak into this plain stroked border.
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor("#f1f5f9")))
            p.drawRect(rect)

            # Day-number badge (filled circle for today)
            num_rect = QRectF(rect.right() - BADGE_SIZE - 6, rect.top() + 6, BADGE_SIZE, BADGE_SIZE)
            if is_today:
                p.setBrush(QBrush(QColor("#2563eb")))
                p.setPen(Qt.NoPen)
                p.drawEllipse(num_rect)
                p.setPen(QPen(QColor("#ffffff")))
            elif is_past and in_month:
                p.setPen(QPen(QColor("#94a3b8")))
            else:
                p.setPen(QPen(QColor("#1e293b") if in_month else QColor("#cbd5e1")))
            p.setFont(num_font)
            p.drawText(num_rect, Qt.AlignCenter, str(d.day))

            # Appointment chips
            day_appts = self.appts_by_day.get(d, [])
            p.setFont(chip_font)
            max_lines = max(1, int((rect.height() - 36) / 17))
            for i, a in enumerate(day_appts[:max_lines]):
                s = datetime.fromisoformat(a["start_datetime"])
                color = STATUS_COLORS.get(a["status"], QColor("#999"))
                chip_rect = QRectF(rect.left() + 6, rect.top() + 34 + i * 17, rect.width() - 12, 15)
                p.setBrush(QBrush(color.lighter(160)))
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(chip_rect, 4, 4)
                p.setPen(QPen(color.darker(150)))
                label = f"{s.hour % 12 or 12}:{s.minute:02d} {a['first_name'] or a['last_name']}"
                p.drawText(chip_rect.adjusted(5, 0, -3, 0), Qt.AlignLeft | Qt.AlignVCenter, label)
            if len(day_appts) > max_lines:
                more_rect = QRectF(rect.left() + 6, rect.bottom() - 15, rect.width() - 12, 13)
                p.setPen(QPen(QColor("#64748b")))
                p.drawText(more_rect, Qt.AlignLeft | Qt.AlignVCenter, f"+{len(day_appts) - max_lines} more")

            if is_hover:
                p.setPen(QPen(QColor("#93c5fd"), 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawRect(rect.adjusted(1, 1, -1, -1))

        p.end()

    def _idx_at(self, pos):
        if pos.y() < HEADER_H:
            return None
        rows = self._rows()
        col_w = self.width() / 7
        row_h = (self.height() - HEADER_H) / rows
        col = int(pos.x() / col_w)
        row = int((pos.y() - HEADER_H) / row_h)
        idx = row * 7 + col
        if 0 <= idx < len(self.cells):
            return idx
        return None

    def mouseMoveEvent(self, event):
        pos = event.position() if hasattr(event, "position") else event.localPos()
        idx = self._idx_at(pos)
        if idx != self._hover_idx:
            self._hover_idx = idx
            self.update()
        # A grayed-out past day shouldn't also get the "clickable" pointing
        # hand cursor - that combination is exactly what read as "obviously
        # non-clickable" was missing.
        if idx is not None and not self._is_past(self.cells[idx]):
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def leaveEvent(self, event):
        if self._hover_idx is not None:
            self._hover_idx = None
            self.update()
        self.setCursor(Qt.ArrowCursor)

    def mousePressEvent(self, event):
        pos = event.position() if hasattr(event, "position") else event.localPos()
        idx = self._idx_at(pos)
        if idx is not None:
            # Visible immediately, even though CalendarView waits a beat
            # before actually switching to Day view - otherwise the click
            # would appear to do nothing at all for that entire pause.
            self._pressed_idx = idx
            self.update()
            self.day_clicked.emit(self.cells[idx])
