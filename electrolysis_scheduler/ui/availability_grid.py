from datetime import date, timedelta

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont

from app import scheduling

DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
HEADER_H = 28
BADGE_SIZE = 22
ROW_HEIGHT = 68

# (background, border, text) - same soft-tint approach as calendar_view's
# STATUS_STYLES, just for "is there any opening at all that day" rather
# than an appointment's own status.
_AVAILABLE = ("#f0fdf4", "#bbf7d0", "#15803d")
_FULL = ("#f8fafc", "#e2e8f0", "#94a3b8")
_OUT_OF_RANGE = ("#ffffff", "#f1f5f9", "#cbd5e1")


class AvailabilityGridWidget(QWidget):
    """A wall-calendar-style grid (Sun-Sat columns, one row per week) over
    a search range - each in-range day tinted green/gray for whether the
    chosen duration has any open start time that day at all
    (scheduling.bookable_start_candidates), the same visual language as
    Month view rather than a plain list of dates. Clicking a green day
    hands it off to Day view (see AvailabilitySearchDialog) to actually
    pick a time and book, instead of opening the booking dialog straight
    from here."""

    day_clicked = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.range_start = date.today()
        self.range_end = date.today()
        self.cells = []
        self._availability = {}
        self._hover_idx = None
        self._pressed_idx = None
        self.setMouseTracking(True)

    def set_search(self, duration_minutes, num_days):
        today = date.today()
        self.range_start = today
        self.range_end = today + timedelta(days=num_days - 1)

        grid_start = self.range_start - timedelta(days=(self.range_start.weekday() + 1) % 7)
        grid_end = self.range_end + timedelta(days=(6 - (self.range_end.weekday() + 1) % 7))
        self.cells = []
        d = grid_start
        while d <= grid_end:
            self.cells.append(d)
            d += timedelta(days=1)

        self._availability = {
            d: bool(scheduling.bookable_start_candidates(d, min_duration=duration_minutes))
            for d in self.cells if self._in_range(d)
        }
        self._hover_idx = None
        self._pressed_idx = None
        self.setMinimumHeight(HEADER_H + self._rows() * ROW_HEIGHT)
        self.update()

    def _in_range(self, d):
        return self.range_start <= d <= self.range_end

    def _rows(self):
        return max(1, len(self.cells) // 7)

    def _cell_rect(self, idx):
        rows = self._rows()
        col_w = self.width() / 7
        row_h = (self.height() - HEADER_H) / rows
        row, col = divmod(idx, 7)
        return QRectF(col * col_w, HEADER_H + row * row_h, col_w, row_h)

    def _clickable(self, idx):
        d = self.cells[idx]
        return self._in_range(d) and self._availability.get(d, False)

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
        status_font = QFont()
        status_font.setBold(True)
        status_font.setPointSize(8)

        for idx, d in enumerate(self.cells):
            rect = self._cell_rect(idx).adjusted(3, 3, -3, -3)
            in_range = self._in_range(d)
            is_available = in_range and self._availability.get(d, False)
            is_today = d == today
            is_hover = idx == self._hover_idx and self._clickable(idx)
            is_pressed = idx == self._pressed_idx

            if not in_range:
                bg, border, text_color = _OUT_OF_RANGE
            elif is_available:
                bg, border, text_color = _AVAILABLE
            else:
                bg, border, text_color = _FULL

            fill = QColor(bg)
            if is_pressed:
                fill = fill.darker(110)
            elif is_hover:
                fill = fill.darker(104)
            p.setBrush(QBrush(fill))
            p.setPen(QPen(QColor(border)))
            p.drawRoundedRect(rect, 8, 8)

            num_rect = QRectF(rect.left() + 6, rect.top() + 6, BADGE_SIZE, BADGE_SIZE)
            if is_today:
                p.setBrush(QBrush(QColor("#2563eb")))
                p.setPen(Qt.NoPen)
                p.drawEllipse(num_rect)
                p.setPen(QPen(QColor("#ffffff")))
            else:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(text_color)))
            p.setFont(num_font)
            p.drawText(num_rect, Qt.AlignCenter, str(d.day))

            if in_range:
                label_rect = QRectF(rect.left() + 4, rect.bottom() - 20, rect.width() - 8, 16)
                p.setFont(status_font)
                p.setPen(QPen(QColor(text_color)))
                p.drawText(
                    label_rect, Qt.AlignLeft | Qt.AlignVCenter,
                    "Open" if is_available else "Full"
                )

            if is_hover:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor("#16a34a"), 1.5))
                p.drawRoundedRect(rect, 8, 8)

        p.end()

    def _idx_at(self, pos):
        if pos.y() < HEADER_H or not self.cells:
            return None
        rows = self._rows()
        col_w = self.width() / 7
        row_h = (self.height() - HEADER_H) / rows
        if col_w <= 0 or row_h <= 0:
            return None
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
        self.setCursor(Qt.PointingHandCursor if idx is not None and self._clickable(idx) else Qt.ArrowCursor)

    def leaveEvent(self, event):
        if self._hover_idx is not None:
            self._hover_idx = None
            self.update()
        self.setCursor(Qt.ArrowCursor)

    def mousePressEvent(self, event):
        pos = event.position() if hasattr(event, "position") else event.localPos()
        idx = self._idx_at(pos)
        if idx is not None and self._clickable(idx):
            self._pressed_idx = idx
            self.update()
            self.day_clicked.emit(self.cells[idx])

    def mouseReleaseEvent(self, event):
        if self._pressed_idx is not None:
            self._pressed_idx = None
            self.update()
