from datetime import datetime, date, time, timedelta

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QScrollArea,
    QComboBox, QMenu, QMessageBox
)
from PySide6.QtCore import Qt, QRectF, QTimer, Signal
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QFont

from app import models, scheduling
from app.util import format_12h

DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

STATUS_COLORS = {
    "scheduled": QColor("#3b82f6"),
    "in_process": QColor("#f59e0b"),
    "completed": QColor("#22a35d"),
    "cancelled": QColor("#9ca3af"),
    "no_show": QColor("#dc2626"),
}
STATUS_LABELS = {
    "scheduled": "Scheduled", "in_process": "In Progress", "completed": "Completed",
    "cancelled": "Cancelled", "no_show": "No-Show",
}

GUTTER_WIDTH = 56
DAY_START_MIN = 9 * 60
DAY_END_MIN = 23 * 60
PX_PER_MIN = 1.4
SLOT_MIN = 15


def week_start(d: date) -> date:
    # Weeks start on Sunday to match the business_hours table (spec 7.1).
    offset = (d.weekday() + 1) % 7  # Monday=0..Sunday=6 -> Sunday=0
    return d - timedelta(days=offset)


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
        p.fillRect(self.rect(), QColor("#f4f4f5"))
        col_width = (self.width() - GUTTER_WIDTH) / max(1, len(self.columns))
        font = QFont()
        font.setBold(True)
        p.setFont(font)
        today = date.today()
        for i, d in enumerate(self.columns):
            x = GUTTER_WIDTH + i * col_width
            rect = QRectF(x, 0, col_width, self.height())
            if d == today:
                p.fillRect(rect, QColor("#dbeafe"))
            p.setPen(QPen(QColor("#333")))
            p.drawText(rect, Qt.AlignCenter, f"{DAY_NAMES[(d.weekday() + 1) % 7]} {d.month}/{d.day}")
            p.setPen(QPen(QColor("#ddd")))
            p.drawLine(int(x), 0, int(x), self.height())
        p.end()


class TimeGridWidget(QWidget):
    slot_clicked = Signal(object)          # datetime
    appt_clicked = Signal(object)          # appt row
    block_clicked = Signal(object)         # blocked_time row
    block_time_requested = Signal(object)  # datetime (right-click -> block this)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.columns = [date.today()]
        self.appointments = []
        self.blocked = []
        self.flash_range = None  # (datetime, datetime)
        self.flash_visible = True
        self._appt_layout = []
        self._block_layout = []
        self.setMinimumHeight(int((DAY_END_MIN - DAY_START_MIN) * PX_PER_MIN))
        self.setMouseTracking(True)

        self._flash_timer = QTimer(self)
        self._flash_timer.timeout.connect(self._toggle_flash)

    def set_data(self, columns, appointments, blocked):
        self.columns = columns
        self.appointments = appointments
        self.blocked = blocked
        self._relayout()
        self.update()

    def flash_slot(self, start_dt, end_dt):
        self.flash_range = (start_dt, end_dt)
        self.flash_visible = True
        self._flash_timer.start(500)
        self.update()

    def clear_flash(self):
        self.flash_range = None
        self._flash_timer.stop()
        self.update()

    def _toggle_flash(self):
        self.flash_visible = not self.flash_visible
        self.update()

    def _col_width(self):
        return (self.width() - GUTTER_WIDTH) / max(1, len(self.columns))

    def _y_for_minutes(self, minutes):
        return (minutes - DAY_START_MIN) * PX_PER_MIN

    def _minutes_for_y(self, y):
        return DAY_START_MIN + y / PX_PER_MIN

    def _relayout(self):
        col_width = self._col_width()
        self._appt_layout = []
        for i, d in enumerate(self.columns):
            day_appts = sorted(
                [a for a in self.appointments if datetime.fromisoformat(a["start_datetime"]).date() == d],
                key=lambda a: a["start_datetime"],
            )
            clusters = self._cluster(day_appts)
            for cluster in clusters:
                n = len(cluster)
                for idx, a in enumerate(cluster):
                    s = datetime.fromisoformat(a["start_datetime"])
                    e = datetime.fromisoformat(a["end_datetime"])
                    x = GUTTER_WIDTH + i * col_width + idx * (col_width / n)
                    y = self._y_for_minutes(s.hour * 60 + s.minute)
                    h = max(6, (e - s).total_seconds() / 60 * PX_PER_MIN)
                    rect = QRectF(x + 1, y + 1, col_width / n - 2, h - 2)
                    self._appt_layout.append((rect, a))

        self._block_layout = []
        for i, d in enumerate(self.columns):
            day_blocks = [
                b for b in self.blocked
                if datetime.fromisoformat(b["start_datetime"]).date() <= d <= datetime.fromisoformat(b["end_datetime"]).date()
            ]
            for b in day_blocks:
                b_start = datetime.fromisoformat(b["start_datetime"])
                b_end = datetime.fromisoformat(b["end_datetime"])
                day_start_dt = datetime.combine(d, time(0, 0))
                day_end_dt = day_start_dt + timedelta(days=1)
                seg_start = max(b_start, day_start_dt)
                seg_end = min(b_end, day_end_dt)
                start_min = max(DAY_START_MIN, seg_start.hour * 60 + seg_start.minute)
                if seg_end >= day_end_dt:
                    end_min = DAY_END_MIN
                else:
                    end_min = min(DAY_END_MIN, seg_end.hour * 60 + seg_end.minute)
                if end_min <= start_min:
                    continue
                x = GUTTER_WIDTH + i * col_width
                y = self._y_for_minutes(start_min)
                h = (end_min - start_min) * PX_PER_MIN
                rect = QRectF(x + 1, y + 1, col_width - 2, h - 2)
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

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        col_width = self._col_width()

        # Background + business-hours shading
        p.fillRect(self.rect(), QColor("#ffffff"))
        for i, d in enumerate(self.columns):
            x = GUTTER_WIDTH + i * col_width
            blocks = scheduling.business_blocks_for_date(d)
            if not blocks:
                p.fillRect(QRectF(x, 0, col_width, self.height()), QColor("#f0f0f0"))
                continue
            open_ranges = []
            for bs, be in blocks:
                open_ranges.append((bs.hour * 60 + bs.minute, be.hour * 60 + be.minute))
            open_ranges.sort()
            cursor = DAY_START_MIN
            for start_m, end_m in open_ranges:
                if start_m > cursor:
                    y1 = self._y_for_minutes(cursor)
                    y2 = self._y_for_minutes(start_m)
                    p.fillRect(QRectF(x, y1, col_width, y2 - y1), QColor("#f0f0f0"))
                cursor = max(cursor, end_m)
            if cursor < DAY_END_MIN:
                y1 = self._y_for_minutes(cursor)
                y2 = self._y_for_minutes(DAY_END_MIN)
                p.fillRect(QRectF(x, y1, col_width, y2 - y1), QColor("#f0f0f0"))

        # Gridlines
        p.setPen(QPen(QColor("#e5e5e5")))
        minutes = DAY_START_MIN
        while minutes <= DAY_END_MIN:
            y = self._y_for_minutes(minutes)
            p.drawLine(GUTTER_WIDTH, int(y), self.width(), int(y))
            minutes += 60
        for i in range(len(self.columns) + 1):
            x = GUTTER_WIDTH + i * col_width
            p.drawLine(int(x), 0, int(x), self.height())

        # Time labels
        p.setPen(QPen(QColor("#666")))
        minutes = DAY_START_MIN
        while minutes <= DAY_END_MIN:
            y = self._y_for_minutes(minutes)
            label_time = datetime.combine(date.today(), time(minutes // 60, minutes % 60))
            p.drawText(QRectF(0, y - 8, GUTTER_WIDTH - 6, 16), Qt.AlignRight | Qt.AlignVCenter, format_12h(label_time))
            minutes += 60

        # Blocked times (hatched)
        for rect, b in self._block_layout:
            p.fillRect(rect, QColor("#d1d5db"))
            p.setPen(QPen(QColor("#9ca3af"), 1))
            step = 8
            xr = rect
            xi = xr.left() - xr.height()
            while xi < xr.right():
                p.drawLine(int(xi), int(xr.bottom()), int(xi + xr.height()), int(xr.top()))
                xi += step
            p.setPen(QPen(QColor("#4b5563")))
            p.drawText(rect.adjusted(4, 2, -4, -2), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
                       f"Blocked: {b['reason']}")
            p.setPen(QPen(QColor("#9ca3af")))
            p.drawRect(rect)

        # Appointments
        for rect, a in self._appt_layout:
            color = STATUS_COLORS.get(a["status"], QColor("#999"))
            p.setBrush(QBrush(color))
            p.setPen(QPen(color.darker(130), 1))
            p.drawRoundedRect(rect, 4, 4)
            p.setPen(QPen(QColor("#ffffff")))
            s = datetime.fromisoformat(a["start_datetime"])
            text = f"{a['first_name']} {a['last_name']}\n{format_12h(s)} · {STATUS_LABELS.get(a['status'], a['status'])}"
            p.drawText(rect.adjusted(4, 2, -4, -2), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, text)

        # Flash highlight
        if self.flash_range and self.flash_visible:
            fs, fe = self.flash_range
            if fs.date() in self.columns:
                i = self.columns.index(fs.date())
                x = GUTTER_WIDTH + i * col_width
                y1 = self._y_for_minutes(fs.hour * 60 + fs.minute)
                y2 = self._y_for_minutes(fe.hour * 60 + fe.minute)
                rect = QRectF(x + 1, y1 + 1, col_width - 2, y2 - y1 - 2)
                p.setBrush(QBrush(QColor(250, 204, 21, 160)))
                p.setPen(QPen(QColor("#ca8a04"), 2))
                p.drawRoundedRect(rect, 4, 4)
                p.drawText(rect, Qt.AlignCenter, "Next available")

        p.end()

    def _event_at(self, pos):
        for rect, a in self._appt_layout:
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
        x, y = pos.x(), pos.y()
        if x < GUTTER_WIDTH:
            return None
        i = int((x - GUTTER_WIDTH) / col_width)
        if i < 0 or i >= len(self.columns):
            return None
        minutes = self._minutes_for_y(y)
        snapped = round(minutes / SLOT_MIN) * SLOT_MIN
        snapped = max(DAY_START_MIN, min(DAY_END_MIN, snapped))
        d = self.columns[i]
        return datetime.combine(d, time(0, 0)) + timedelta(minutes=snapped)


class CalendarView(QWidget):
    def __init__(self, parent=None, require_admin=None):
        super().__init__(parent)
        self.require_admin = require_admin or (lambda: True)
        self.mode = "week"
        self.anchor_date = date.today()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        toolbar = QHBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Day", "Week", "Month"])
        self.mode_combo.setCurrentText("Week")
        self.mode_combo.currentTextChanged.connect(self._on_mode_change)
        toolbar.addWidget(self.mode_combo)

        prev_btn = QPushButton("<")
        prev_btn.setFixedWidth(32)
        prev_btn.clicked.connect(self._go_prev)
        today_btn = QPushButton("Today")
        today_btn.clicked.connect(self._go_today)
        next_btn = QPushButton(">")
        next_btn.setFixedWidth(32)
        next_btn.clicked.connect(self._go_next)
        toolbar.addWidget(prev_btn)
        toolbar.addWidget(today_btn)
        toolbar.addWidget(next_btn)

        self.range_label = QLabel("")
        self.range_label.setStyleSheet("font-weight: 600; font-size: 14px;")
        toolbar.addWidget(self.range_label)
        toolbar.addStretch()

        add_btn = QPushButton("+ Add Appointment")
        add_btn.clicked.connect(lambda: self._open_appointment(None))
        toolbar.addWidget(add_btn)

        block_btn = QPushButton("Block Time Off")
        block_btn.clicked.connect(lambda: self._open_block_dialog(None))
        toolbar.addWidget(block_btn)

        suggest_btn = QPushButton("Suggest Next Slot")
        suggest_btn.clicked.connect(self._suggest_slot)
        toolbar.addWidget(suggest_btn)

        layout.addLayout(toolbar)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        self.header = DayHeaderWidget()
        header_row.addWidget(self.header)
        layout.addLayout(header_row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.grid = TimeGridWidget()
        self.scroll.setWidget(self.grid)
        layout.addWidget(self.scroll)

        self.grid.slot_clicked.connect(self._on_slot_clicked)
        self.grid.appt_clicked.connect(self._open_appointment)
        self.grid.block_clicked.connect(self._on_block_clicked)
        self.grid.block_time_requested.connect(self._open_block_dialog)

        self.month_view = None  # lazily built

        self.refresh()

    # ---- navigation ----
    def _on_mode_change(self, text):
        self.mode = text.lower()
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

    @staticmethod
    def _add_months(d, delta):
        month = d.month - 1 + delta
        year = d.year + month // 12
        month = month % 12 + 1
        return date(year, month, 1)

    def _columns_for_range(self):
        if self.mode == "day":
            return [self.anchor_date]
        elif self.mode == "week":
            ws = week_start(self.anchor_date)
            return [ws + timedelta(days=i) for i in range(7)]
        return []

    # ---- data refresh ----
    def refresh(self):
        if self.mode == "month":
            self._show_month()
            return
        self.scroll.show()
        self.header.show()
        if self.month_view is not None:
            self.month_view.hide()
        columns = self._columns_for_range()
        range_start = datetime.combine(columns[0], time(0, 0))
        range_end = datetime.combine(columns[-1], time(0, 0)) + timedelta(days=1)
        appts = models.list_appointments_between(range_start, range_end)
        blocked = models.list_blocked_between(range_start, range_end)
        self.header.set_columns(columns)
        self.grid.set_data(columns, appts, blocked)
        if self.mode == "day":
            self.range_label.setText(columns[0].strftime("%A, %B %d, %Y"))
        else:
            self.range_label.setText(f"{columns[0].strftime('%b %d')} – {columns[-1].strftime('%b %d, %Y')}")

    def _show_month(self):
        from ui.month_view import MonthGridWidget
        self.scroll.hide()
        self.header.hide()
        if self.month_view is None:
            self.month_view = MonthGridWidget()
            self.month_view.day_clicked.connect(self._jump_to_day)
            self.layout().addWidget(self.month_view)
        self.month_view.show()
        first = date(self.anchor_date.year, self.anchor_date.month, 1)
        self.month_view.set_month(self.anchor_date.year, self.anchor_date.month)
        self.range_label.setText(first.strftime("%B %Y"))

    def _jump_to_day(self, d):
        self.anchor_date = d
        self.mode = "day"
        self.mode_combo.setCurrentText("Day")

    # ---- interactions ----
    def _on_slot_clicked(self, dt):
        self._open_appointment(None, start_dt=dt)

    def _open_appointment(self, appt_row, start_dt=None):
        from ui.appointment_dialog import AppointmentDialog
        dlg = AppointmentDialog(self, appt_row=appt_row, start_dt=start_dt)
        if dlg.exec() and dlg.result_changed:
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

    def _suggest_slot(self):
        after = datetime.now()
        result = scheduling.find_next_open_slot(after)
        if not result:
            QMessageBox.information(self, "No Open Slots", "No open slot found in the next 60 days.")
            return
        start, end = result
        self.mode = "day"
        self.mode_combo.setCurrentText("Day")
        self.anchor_date = start.date()
        self.refresh()
        self.grid.flash_slot(start, end)
        QTimer.singleShot(6000, self.grid.clear_flash)
