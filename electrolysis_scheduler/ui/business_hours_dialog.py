from datetime import date, datetime, time, timedelta

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTimeEdit, QPushButton,
    QGroupBox, QScrollArea, QWidget, QMessageBox
)
from PySide6.QtCore import QTime

from app import models, scheduling
from app.util import format_12h, format_client_name

DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

# How far ahead to look for existing appointments that a business-hours
# change would orphan. Appointments are only ever booked a limited distance
# out (see scheduling.find_next_open_slot's 60-day search), so this is a
# generous upper bound rather than a hard scheduling limit.
CONFLICT_SEARCH_DAYS = 365


class _BlockRow(QWidget):
    def __init__(self, start_time="09:00", end_time="17:00", on_remove=None):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.start_edit = QTimeEdit()
        self.start_edit.setDisplayFormat("h:mm AP")
        sh, sm = map(int, start_time.split(":"))
        self.start_edit.setTime(QTime(sh, sm))
        self.end_edit = QTimeEdit()
        self.end_edit.setDisplayFormat("h:mm AP")
        eh, em = map(int, end_time.split(":"))
        self.end_edit.setTime(QTime(eh, em))
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(lambda: on_remove(self) if on_remove else None)
        layout.addWidget(QLabel("From"))
        layout.addWidget(self.start_edit)
        layout.addWidget(QLabel("to"))
        layout.addWidget(self.end_edit)
        layout.addWidget(remove_btn)
        layout.addStretch()

    def as_tuple(self):
        return (
            f"{self.start_edit.time().hour():02d}:{self.start_edit.time().minute():02d}",
            f"{self.end_edit.time().hour():02d}:{self.end_edit.time().minute():02d}",
        )


class BusinessHoursEditor(QWidget):
    """The actual per-day hours editor - embeddable directly on a page (the
    Admin tab) as well as inside BusinessHoursDialog's modal popup.

    `on_saved` is called after a successful save (dialog usage passes
    `self.accept`; a persistent embedding does its own refresh/confirmation
    instead). `on_cancel`, if given, adds a Cancel button next to Save -
    only the modal dialog wants that; an always-visible tab doesn't need a
    way to "cancel" out of itself. `require_admin`, if given, is asked right
    before the save actually persists - the modal dialog's caller already
    re-verifies the admin password before ever opening it, so it passes
    nothing (no double prompt); the Admin tab has no such "before opening"
    moment since it's always on screen, so it gates at Save instead."""

    def __init__(self, parent=None, require_admin=None, on_saved=None, on_cancel=None):
        super().__init__(parent)
        self.require_admin = require_admin or (lambda: True)
        self.on_saved = on_saved or (lambda: None)

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        self.day_boxes = {}
        for day in DAYS:
            box = QGroupBox(day)
            box_layout = QVBoxLayout(box)
            rows_container = QVBoxLayout()
            box_layout.addLayout(rows_container)
            add_btn = QPushButton("+ Add time block")
            box_layout.addWidget(add_btn)
            self.day_boxes[day] = {"rows_container": rows_container, "rows": []}
            add_btn.clicked.connect(lambda checked=False, d=day: self._add_row(d))
            self.content_layout.addWidget(box)

            for hr in models.business_hours_for_day(day):
                self._add_row(day, hr["start_time"], hr["end_time"])

        self.content_layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        if on_cancel is not None:
            cancel_btn = QPushButton("Cancel")
            cancel_btn.clicked.connect(on_cancel)
            btn_row.addWidget(cancel_btn)
        save_btn = QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        outer.addLayout(btn_row)

    def _add_row(self, day, start_time="10:00", end_time="17:00"):
        info = self.day_boxes[day]

        def remove(row_widget):
            info["rows"].remove(row_widget)
            info["rows_container"].removeWidget(row_widget)
            row_widget.deleteLater()

        row = _BlockRow(start_time, end_time, on_remove=remove)
        info["rows"].append(row)
        info["rows_container"].addWidget(row)

    def _save(self):
        if not self.require_admin():
            return

        proposed = {}
        for day, info in self.day_boxes.items():
            blocks = []
            for row in info["rows"]:
                s, e = row.as_tuple()
                if s >= e:
                    QMessageBox.warning(self, "Invalid Block", f"{day}: end time must be after start time.")
                    return
                blocks.append((s, e))
            proposed[day] = blocks

        conflicts = self._find_conflicts(proposed)
        if conflicts:
            lines = "\n".join(f"- {c}" for c in conflicts)
            QMessageBox.warning(
                self, "Appointments Conflict With New Hours",
                "These upcoming appointments no longer fit inside the new business hours. "
                "Reschedule or cancel them first, then save again:\n\n" + lines
            )
            return

        for day, blocks in proposed.items():
            models.replace_business_hours_for_day(day, blocks)
        self.on_saved()

    @staticmethod
    def _fits_a_block(start_dt, end_dt, day_blocks):
        for s, e in day_blocks:
            sh, sm = map(int, s.split(":"))
            eh, em = map(int, e.split(":"))
            block_start = datetime.combine(start_dt.date(), time(sh, sm))
            block_end = datetime.combine(start_dt.date(), time(eh, em))
            if block_start <= start_dt and end_dt <= block_end:
                return True
        return False

    def _find_conflicts(self, proposed):
        """Only today-or-future appointments can be orphaned by an hours
        change (spec 8: business hours are only ever edited for today or
        future, and any appointment that no longer fits must be rescheduled
        or cancelled by the admin before the new hours can be saved)."""
        range_start = datetime.combine(date.today(), time(0, 0))
        range_end = range_start + timedelta(days=CONFLICT_SEARCH_DAYS)
        appts = models.list_appointments_between(range_start, range_end)
        conflicts = []
        for a in appts:
            if a["status"] not in models.ACTIVE_STATUSES:
                continue
            s = datetime.fromisoformat(a["start_datetime"])
            e = datetime.fromisoformat(a["end_datetime"])
            day = scheduling.day_name(s.date())
            if not self._fits_a_block(s, e, proposed[day]):
                names = ", ".join(format_client_name(c["first_name"], c["last_name"]) for c in a["clients"])
                conflicts.append(f"{s.strftime('%a %b %d')} {format_12h(s)}–{format_12h(e)}: {names}")
        return conflicts


class BusinessHoursDialog(QDialog):
    """Edit business hours per day (spec 7.1, Phase 3). Caller must re-verify
    the admin password before opening this dialog (spec 7.4)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Business Hours")
        self.setMinimumSize(480, 520)
        layout = QVBoxLayout(self)
        self.editor = BusinessHoursEditor(self, on_saved=self.accept, on_cancel=self.reject)
        layout.addWidget(self.editor)
