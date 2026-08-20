from datetime import date, datetime, time, timedelta
import calendar as calendar_module

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QFont

from app import models

DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

STATUS_COLORS = {
    "scheduled": QColor("#3b82f6"),
    "in_process": QColor("#f59e0b"),
    "completed": QColor("#22a35d"),
    "cancelled": QColor("#9ca3af"),
    "no_show": QColor("#dc2626"),
}


class MonthGridWidget(QWidget):
    day_clicked = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.year = date.today().year
        self.month = date.today().month
        self.cells = []       # list of date objects, len == rows*7
        self.appts_by_day = {}
        self.blocked_days = set()
        self.setMinimumHeight(480)

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

        self.update()

    def _rows(self):
        return max(1, len(self.cells) // 7)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))

        header_h = 24
        rows = self._rows()
        col_w = self.width() / 7
        row_h = (self.height() - header_h) / rows

        font_bold = QFont()
        font_bold.setBold(True)
        p.setFont(font_bold)
        p.setPen(QPen(QColor("#555")))
        for i, name in enumerate(DAY_NAMES):
            p.drawText(QRectF(i * col_w, 0, col_w, header_h), Qt.AlignCenter, name)

        today = date.today()
        normal_font = QFont()
        p.setFont(normal_font)

        for idx, d in enumerate(self.cells):
            row = idx // 7
            col = idx % 7
            x = col * col_w
            y = header_h + row * row_h
            rect = QRectF(x, y, col_w, row_h)

            in_month = d.month == self.month
            bg = QColor("#ffffff") if in_month else QColor("#fafafa")
            if d == today:
                bg = QColor("#dbeafe")
            p.fillRect(rect, bg)
            if d in self.blocked_days:
                p.fillRect(rect.adjusted(2, 2, -2, -2), QColor(209, 213, 219, 120))

            p.setPen(QPen(QColor("#e5e5e5")))
            p.drawRect(rect)

            p.setPen(QPen(QColor("#333") if in_month else QColor("#bbb")))
            p.drawText(QRectF(x + 4, y + 2, col_w - 8, 16), Qt.AlignLeft, str(d.day))

            day_appts = self.appts_by_day.get(d, [])
            max_lines = max(1, int((row_h - 20) / 14))
            for i, a in enumerate(day_appts[:max_lines]):
                s = datetime.fromisoformat(a["start_datetime"])
                color = STATUS_COLORS.get(a["status"], QColor("#999"))
                line_rect = QRectF(x + 3, y + 20 + i * 14, col_w - 6, 13)
                p.fillRect(QRectF(line_rect.x(), line_rect.y() + 2, 4, 9), color)
                p.setPen(QPen(QColor("#333")))
                label = f"{s.hour % 12 or 12}:{s.minute:02d} {a['first_name']} {a['last_name'][:1]}."
                p.drawText(line_rect.adjusted(7, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, label)
            if len(day_appts) > max_lines:
                more_rect = QRectF(x + 4, y + row_h - 14, col_w - 8, 12)
                p.setPen(QPen(QColor("#666")))
                p.drawText(more_rect, Qt.AlignLeft, f"+{len(day_appts) - max_lines} more")

        p.end()

    def mousePressEvent(self, event):
        pos = event.position() if hasattr(event, "position") else event.localPos()
        header_h = 24
        rows = self._rows()
        col_w = self.width() / 7
        row_h = (self.height() - header_h) / rows
        if pos.y() < header_h:
            return
        col = int(pos.x() / col_w)
        row = int((pos.y() - header_h) / row_h)
        idx = row * 7 + col
        if 0 <= idx < len(self.cells):
            self.day_clicked.emit(self.cells[idx])
