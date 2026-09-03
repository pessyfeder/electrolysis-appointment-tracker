from datetime import datetime, timedelta, time

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QFormLayout, QTimeEdit, QCheckBox,
    QTextEdit, QPushButton, QHBoxLayout, QMessageBox, QLabel
)
from PySide6.QtCore import QDate, QTime

from app import models
from app.util import format_client_name
from ui.widgets import ClickToOpenDateEdit


class BlockTimeForm(QWidget):
    """The actual block-off-time form - embeddable directly on a page (the
    Admin tab) as well as inside BlockTimeDialog's modal popup. Reason is
    required (spec 7.1). See BusinessHoursEditor for why `on_saved`,
    `on_cancel`, and `require_admin` are structured this way."""

    def __init__(self, parent=None, start_dt=None, require_admin=None, on_saved=None, on_cancel=None):
        super().__init__(parent)
        self.require_admin = require_admin or (lambda: True)
        self.on_saved = on_saved or (lambda: None)
        self._default_start_dt = start_dt or datetime.now()

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.date_edit = ClickToOpenDateEdit()
        form.addRow("Date: *", self.date_edit)

        self.full_day_check = QCheckBox("Block the entire day")
        form.addRow("", self.full_day_check)

        self.start_time_edit = QTimeEdit()
        self.start_time_edit.setDisplayFormat("h:mm AP")
        self.end_time_edit = QTimeEdit()
        self.end_time_edit.setDisplayFormat("h:mm AP")
        form.addRow("From: *", self.start_time_edit)
        form.addRow("To: *", self.end_time_edit)

        self.full_day_check.toggled.connect(self._toggle_full_day)

        self.reason_edit = QTextEdit()
        self.reason_edit.setFixedHeight(70)
        self.reason_edit.setPlaceholderText("Why are you unavailable?")
        form.addRow("Reason: *", self.reason_edit)

        layout.addLayout(form)

        required_hint = QLabel("* Required")
        required_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(required_hint)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        if on_cancel is not None:
            cancel_btn = QPushButton("Cancel")
            cancel_btn.clicked.connect(on_cancel)
            btn_row.addWidget(cancel_btn)
        save_btn = QPushButton("Block Time Off")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        # In the modal dialog this widget sizes to its content either way,
        # but embedded directly on a full-height page (the Admin tab)
        # without this, the plain QVBoxLayout stretches the form rows apart
        # to fill all the extra vertical space instead of collecting it
        # below the button row.
        layout.addStretch()

        self._reset_fields()

    def refresh(self, start_dt=None):
        """Re-anchors the form's date/time defaults to "now" (or a given
        moment) - without this, a persistently-embedded form (the Admin
        tab) would keep showing whatever date happened to be current when
        the widget was first constructed, potentially hours or days stale."""
        self._default_start_dt = start_dt or datetime.now()
        self._reset_fields()

    def _reset_fields(self):
        start_dt = self._default_start_dt
        self.date_edit.setDate(QDate(start_dt.year, start_dt.month, start_dt.day))
        self.full_day_check.setChecked(False)
        self.start_time_edit.setTime(QTime(start_dt.hour, start_dt.minute))
        end_default = start_dt + timedelta(minutes=30)
        self.end_time_edit.setTime(QTime(end_default.hour, end_default.minute))
        self.reason_edit.clear()

    def _toggle_full_day(self, checked):
        self.start_time_edit.setEnabled(not checked)
        self.end_time_edit.setEnabled(not checked)

    def _save(self):
        if not self.require_admin():
            return

        reason = self.reason_edit.toPlainText().strip()
        if not reason:
            QMessageBox.warning(self, "Reason Required", "Please enter a reason for blocking this time off.")
            return

        d = self.date_edit.date()
        if self.full_day_check.isChecked():
            start_dt = datetime(d.year(), d.month(), d.day(), 0, 0)
            end_dt = start_dt + timedelta(days=1)
        else:
            st = self.start_time_edit.time()
            et = self.end_time_edit.time()
            start_dt = datetime(d.year(), d.month(), d.day(), st.hour(), st.minute())
            end_dt = datetime(d.year(), d.month(), d.day(), et.hour(), et.minute())
            if end_dt <= start_dt:
                QMessageBox.warning(self, "Invalid Range", "End time must be after start time.")
                return

        conflicting = [
            a for a in models.list_appointments_between(start_dt, end_dt)
            if a["status"] in models.ACTIVE_STATUSES
        ]
        if conflicting:
            names = ", ".join(
                format_client_name(c["first_name"], c["last_name"])
                for a in conflicting for c in a["clients"]
            )
            if QMessageBox.question(
                self, "Existing Appointments",
                f"This overlaps existing appointment(s) with {names}. Block the time anyway? "
                "(You'll still need to reschedule or cancel those appointments separately.)"
            ) != QMessageBox.Yes:
                return

        models.create_blocked_time(start_dt, end_dt, reason)
        self._reset_fields()
        self.on_saved()


class BlockTimeDialog(QDialog):
    """Block a time slot or a full day off. Reason is required (spec 7.1)."""

    def __init__(self, parent=None, start_dt=None):
        super().__init__(parent)
        self.setWindowTitle("Block Off Time")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        self.form = BlockTimeForm(self, start_dt=start_dt, on_saved=self.accept, on_cancel=self.reject)
        layout.addWidget(self.form)
