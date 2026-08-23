from datetime import datetime, timedelta, time

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QDateEdit, QTimeEdit, QCheckBox,
    QTextEdit, QPushButton, QHBoxLayout, QMessageBox, QLabel
)
from PySide6.QtCore import QDate, QTime

from app import models
from app.util import format_client_name


class BlockTimeDialog(QDialog):
    """Block a time slot or a full day off. Reason is required (spec 7.1)."""

    def __init__(self, parent=None, start_dt=None):
        super().__init__(parent)
        self.setWindowTitle("Block Off Time")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        start_dt = start_dt or datetime.now()
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate(start_dt.year, start_dt.month, start_dt.day))
        form.addRow("Date: *", self.date_edit)

        self.full_day_check = QCheckBox("Block the entire day")
        form.addRow("", self.full_day_check)

        self.start_time_edit = QTimeEdit()
        self.start_time_edit.setDisplayFormat("h:mm AP")
        self.start_time_edit.setTime(QTime(start_dt.hour, start_dt.minute))
        self.end_time_edit = QTimeEdit()
        self.end_time_edit.setDisplayFormat("h:mm AP")
        end_default = start_dt + timedelta(minutes=30)
        self.end_time_edit.setTime(QTime(end_default.hour, end_default.minute))
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
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Block Time")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _toggle_full_day(self, checked):
        self.start_time_edit.setEnabled(not checked)
        self.end_time_edit.setEnabled(not checked)

    def _save(self):
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
        self.accept()
