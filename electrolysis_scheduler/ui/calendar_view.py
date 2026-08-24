from datetime import datetime, date, time, timedelta

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QScrollArea,
    QComboBox, QMessageBox, QFrame
)
from PySide6.QtCore import Qt, QRectF, QTimer, Signal
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QFont

from app import models, scheduling
from app.util import format_12h, format_client_name
from ui.month_view import MonthGridWidget

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

PX_PER_MIN = 1.4
SLOT_MIN = 15
CARD_HEADER_HEIGHT = 26
CARD_TOP_MARGIN = 10
CARD_GAP = 14
CARD_RADIUS = 8


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
        p.fillRect(self.rect(), QColor("#f4f4f5"))
        col_width = self.width() / max(1, len(self.columns))
        font = QFont()
        font.setBold(True)
        p.setFont(font)
        today = date.today()
        for i, d in enumerate(self.columns):
            x = i * col_width
            rect = QRectF(x, 0, col_width, self.height())
            if d == today:
                p.fillRect(rect, QColor("#dbeafe"))
            elif d < today:
                p.fillRect(rect, QColor("#f1f5f9"))
            p.setPen(QPen(QColor("#94a3b8") if d < today and d != today else QColor("#333")))
            p.drawText(rect, Qt.AlignCenter, f"{DAY_NAMES[(d.weekday() + 1) % 7]} {d.month}/{d.day}")
            p.setPen(QPen(QColor("#ddd")))
            p.drawLine(int(x), 0, int(x), self.height())
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
        self.flash_range = None  # (datetime, datetime)
        self.flash_visible = True
        self._columns_cards = []   # per column: list of card dicts
        self._appt_layout = []
        self._block_layout = []
        self.setMinimumHeight(200)
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
        return self.width() / max(1, len(self.columns))

    @staticmethod
    def _full_height(block):
        block_start, block_end = block
        duration_min = (block_end - block_start).total_seconds() / 60
        body_h = max(20, duration_min * PX_PER_MIN)
        return CARD_HEADER_HEIGHT + body_h

    @classmethod
    def _stacked_height(cls, blocks):
        if not blocks:
            return 0
        return sum(cls._full_height(b) for b in blocks) + CARD_GAP * (len(blocks) - 1)

    def _relayout(self):
        col_width = self._col_width()
        today = date.today()

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

        am_height = max((self._stacked_height(am) for am, _ in per_col_periods), default=0)
        pm_height = max((self._stacked_height(pm) for _, pm in per_col_periods), default=0)

        am_row_y = CARD_TOP_MARGIN
        pm_row_y = am_row_y + (am_height + CARD_GAP if am_height else 0)
        max_height = max(am_row_y + am_height, pm_row_y + pm_height) + CARD_TOP_MARGIN

        self._columns_cards = []
        for i, d in enumerate(self.columns):
            x = i * col_width
            am, pm = per_col_periods[i]
            is_past = d < today
            cards = []
            for row_y, blocks in ((am_row_y, am), (pm_row_y, pm)):
                y = row_y
                for block_start, block_end in blocks:
                    full_h = self._full_height((block_start, block_end))
                    body_h = full_h - CARD_HEADER_HEIGHT
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

        self.setMinimumHeight(int(max_height))

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
                for cluster in self._cluster(card_appts):
                    n = len(cluster)
                    for idx, a in enumerate(cluster):
                        s = datetime.fromisoformat(a["start_datetime"])
                        e = datetime.fromisoformat(a["end_datetime"])
                        offset_min = (s - block_start).total_seconds() / 60
                        cell_w = body.width() / n
                        x = body.left() + idx * cell_w
                        y = body.top() + offset_min * PX_PER_MIN
                        h = max(6, (e - s).total_seconds() / 60 * PX_PER_MIN)
                        rect = QRectF(x + 1, y + 1, cell_w - 2, h - 2)
                        self._appt_layout.append((rect, a))

                for b in self.blocked:
                    b_start = datetime.fromisoformat(b["start_datetime"])
                    b_end = datetime.fromisoformat(b["end_datetime"])
                    seg_start = max(b_start, block_start)
                    seg_end = min(b_end, block_end)
                    if seg_end <= seg_start:
                        continue
                    off_start = (seg_start - block_start).total_seconds() / 60
                    off_end = (seg_end - block_start).total_seconds() / 60
                    y1 = body.top() + off_start * PX_PER_MIN
                    y2 = body.top() + off_end * PX_PER_MIN
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

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))

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
                header_color = QColor("#f1f5f9") if is_past else QColor("#eff6ff")
                text_color = QColor("#94a3b8") if is_past else QColor("#1d4ed8")

                # Header fill first (rounded top corners only, via the half-rect trick)...
                p.setBrush(QBrush(header_color))
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(card["header"], CARD_RADIUS, CARD_RADIUS)
                p.drawRect(QRectF(card["header"].left(), card["header"].center().y(),
                                   card["header"].width(), card["header"].height() / 2))

                # ...then the card border stroke on top, so it stays crisp over the header too.
                p.setPen(QPen(QColor("#e2e8f0"), 1))
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
                    y = card["body"].top() + minutes * PX_PER_MIN
                    p.drawLine(int(card["body"].left()), int(y), int(card["body"].right()), int(y))
                    minutes += 30

                # Past days: gray wash over the empty body, under any
                # appointments/blocks drawn later, so those stay legible.
                if is_past:
                    p.fillRect(card["body"], QColor(203, 213, 225, 90))

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
            text = f"{self._appt_names(a)}\n{format_12h(s)} · {STATUS_LABELS.get(a['status'], a['status'])}"
            p.drawText(rect.adjusted(4, 2, -4, -2), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, text)

        # Flash highlight ("Next Available Appointment" jump)
        if self.flash_range and self.flash_visible:
            fs, fe = self.flash_range
            rect = self._rect_for_range(fs, fe)
            if rect is not None:
                p.setBrush(QBrush(QColor(250, 204, 21, 160)))
                p.setPen(QPen(QColor("#ca8a04"), 2))
                p.drawRoundedRect(rect, 4, 4)
                p.drawText(rect, Qt.AlignCenter, "Next available")

        p.end()

    def _rect_for_range(self, start_dt, end_dt):
        if start_dt.date() not in self.columns:
            return None
        i = self.columns.index(start_dt.date())
        for card in self._columns_cards[i]:
            if card["block_start"] <= start_dt < card["block_end"]:
                off_start = (start_dt - card["block_start"]).total_seconds() / 60
                off_end = (end_dt - card["block_start"]).total_seconds() / 60
                body = card["body"]
                y1 = body.top() + off_start * PX_PER_MIN
                y2 = body.top() + off_end * PX_PER_MIN
                return QRectF(body.left() + 1, y1 + 1, body.width() - 2, y2 - y1 - 2)
        return None

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
        i = int(pos.x() / col_width)
        if i < 0 or i >= len(self.columns):
            return None
        if self.columns[i] < date.today():
            return None  # past days are not clickable for booking
        for card in self._columns_cards[i]:
            if card["body"].contains(pos):
                offset_min = (pos.y() - card["body"].top()) / PX_PER_MIN
                snapped = round(offset_min / SLOT_MIN) * SLOT_MIN
                snapped = max(0, snapped)
                return card["block_start"] + timedelta(minutes=snapped)
        return None


class CalendarView(QWidget):
    def __init__(self, parent=None, require_admin=None):
        super().__init__(parent)
        self.require_admin = require_admin or (lambda: True)
        self.mode = "week"
        self.anchor_date = date.today()
        self._next_available = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(10)

        toolbar_card = QFrame()
        toolbar_card.setObjectName("toolbarCard")
        toolbar_card.setStyleSheet(
            "#toolbarCard { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; }"
        )
        toolbar = QHBoxLayout(toolbar_card)
        toolbar.setContentsMargins(12, 10, 12, 10)
        toolbar.setSpacing(8)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Month", "Week"])
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
        self.range_label.setStyleSheet("font-weight: 700; font-size: 14px; margin-left: 6px;")
        toolbar.addWidget(self.range_label)
        toolbar.addStretch()

        add_btn = QPushButton("+ Add Appointment")
        add_btn.setObjectName("primaryButton")
        add_btn.clicked.connect(lambda: self._open_appointment(None))
        toolbar.addWidget(add_btn)

        block_btn = QPushButton("Block Time Off")
        block_btn.clicked.connect(lambda: self._open_block_dialog(None))
        toolbar.addWidget(block_btn)

        outer.addWidget(toolbar_card)

        self.next_available_label = ClickableLabel("")
        self.next_available_label.setCursor(Qt.PointingHandCursor)
        self.next_available_label.setStyleSheet(
            "background: #eff6ff; color: #1d4ed8; font-weight: 600; "
            "padding: 8px 12px; border-radius: 8px; border: 1px solid #dbeafe;"
        )
        self.next_available_label.clicked.connect(self._jump_to_next_available)
        outer.addWidget(self.next_available_label)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        self.header = DayHeaderWidget()
        header_row.addWidget(self.header)
        outer.addLayout(header_row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.grid = TimeGridWidget()
        self.scroll.setWidget(self.grid)
        outer.addWidget(self.scroll)

        self.grid.slot_clicked.connect(self._on_slot_clicked)
        self.grid.appt_clicked.connect(self._open_appointment)
        self.grid.block_clicked.connect(self._on_block_clicked)
        self.grid.block_time_requested.connect(self._open_block_dialog)

        self.month_view = MonthGridWidget()
        self.month_view.day_clicked.connect(self._on_month_day_clicked)
        outer.addWidget(self.month_view)

        self.refresh()

    # ---- navigation ----
    def _on_mode_change(self, text):
        self.mode = text.lower()
        self.refresh()

    def _go_prev(self):
        if self.mode == "week":
            self.anchor_date -= timedelta(days=7)
        else:
            self.anchor_date = self._add_months(self.anchor_date, -1)
        self.refresh()

    def _go_next(self):
        if self.mode == "week":
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
        ws = week_start(self.anchor_date)
        return [ws + timedelta(days=i) for i in range(7)]

    # ---- data refresh ----
    def refresh(self):
        self._refresh_next_available()
        if self.mode == "month":
            self._show_month()
            return
        self.scroll.show()
        self.header.show()
        self.month_view.hide()
        columns = self._columns_for_range()
        range_start = datetime.combine(columns[0], time(0, 0))
        range_end = datetime.combine(columns[-1], time(0, 0)) + timedelta(days=1)
        appts = models.list_appointments_between(range_start, range_end)
        blocked = models.list_blocked_between(range_start, range_end)
        self.header.set_columns(columns)
        self.grid.set_data(columns, appts, blocked)
        self.range_label.setText(f"{columns[0].strftime('%b %d')} – {columns[-1].strftime('%b %d, %Y')}")

    def _show_month(self):
        self.scroll.hide()
        self.header.hide()
        self.month_view.show()
        first = date(self.anchor_date.year, self.anchor_date.month, 1)
        self.month_view.set_month(self.anchor_date.year, self.anchor_date.month)
        self.range_label.setText(first.strftime("%B %Y"))

    def _on_month_day_clicked(self, d):
        # Both past and future days route to the week view: future days can
        # be booked there, past days are view-only (spec 7.1 / 8).
        self.anchor_date = d
        self.mode = "week"
        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentText("Week")
        self.mode_combo.blockSignals(False)
        self.refresh()

    def _jump_to_next_available(self):
        if not self._next_available:
            return
        start, end = self._next_available
        self.anchor_date = start.date()
        self.mode = "week"
        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentText("Week")
        self.mode_combo.blockSignals(False)
        self.refresh()
        self.grid.flash_slot(start, end)
        QTimer.singleShot(6000, self.grid.clear_flash)

    def _refresh_next_available(self):
        result = scheduling.find_next_open_slot(datetime.now())
        self._next_available = result
        if not result:
            self.next_available_label.setText("Next Available Appointment: none found in the next 60 days")
            return
        start, _ = result
        when = start.strftime("%a, %b %d") + f" at {format_12h(start)}"
        self.next_available_label.setText(f"Next Available Appointment: {when}")

    # ---- interactions ----
    def _on_slot_clicked(self, dt):
        self._open_appointment(None, start_dt=dt)

    def _open_appointment(self, appt_row, start_dt=None):
        from ui.appointment_dialog import AppointmentDialog
        dlg = AppointmentDialog(self, appt_row=appt_row, start_dt=start_dt, require_admin=self.require_admin)
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
