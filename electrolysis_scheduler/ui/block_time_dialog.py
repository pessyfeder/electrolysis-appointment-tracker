from datetime import datetime, timedelta, time

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QFormLayout, QTimeEdit, QCheckBox,
    QTextEdit, QPushButton, QHBoxLayout, QMessageBox
)
from PySide6.QtCore import QDate, QTime

from app import models
from app.util import format_client_name
from ui.widgets import ClickToOpenDateEdit, required_label, required_hint_label, apply_large_form_style


class BlockTimeForm(QWidget):
    """The actual block-off-time form - embeddable directly on a page (the
    Admin tab) as well as inside BlockTimeDialog's modal popup. Reason is
    required (spec 7.1). See BusinessHoursEditor for why `on_saved`,
    `on_cancel`, and `require_admin` are structured this way."""

    def __init__(self, parent=None, start_dt=None, require_admin=None, on_saved=None, on_cancel=None):
        super().__init__(parent)
        self.require_admin = require_admin or (lambda: True)
        self.on_saved = on_saved or (lambda: None)
        self._on_cancel_extra = on_cancel
        self._default_start_dt = start_dt or datetime.now()

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.date_edit = ClickToOpenDateEdit()
        form.addRow(required_label("Date:"), self.date_edit)

        self.full_day_check = QCheckBox("Block the entire day")
        form.addRow("", self.full_day_check)

        self.start_time_edit = QTimeEdit()
        self.start_time_edit.setDisplayFormat("h:mm AP")
        self.end_time_edit = QTimeEdit()
        self.end_time_edit.setDisplayFormat("h:mm AP")
        form.addRow(required_label("From:"), self.start_time_edit)
        form.addRow(required_label("To:"), self.end_time_edit)

        self.full_day_check.toggled.connect(self._toggle_full_day)

        self.reason_edit = QTextEdit()
        self.reason_edit.setFixedHeight(90)
        self.reason_edit.setPlaceholderText("Why are you unavailable?")
        form.addRow(required_label("Reason:"), self.reason_edit)

        layout.addLayout(form)

        layout.addWidget(required_hint_label())

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        # Save/Cancel start disabled - nothing has been entered yet, so
        # there's nothing to save or discard. _mark_dirty() (wired to every
        # field below) enables both; a successful Save or Cancel resets the
        # form and puts them back to a clean, disabled state.
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        btn_row.addWidget(self.cancel_btn)
        self.save_btn = QPushButton("Block Time Off")
        self.save_btn.setEnabled(False)
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._save)
        btn_row.addWidget(self.save_btn)
        layout.addLayout(btn_row)

        # In the modal dialog this widget sizes to its content either way,
        # but embedded directly on a full-height page (the Admin tab)
        # without this, the plain QVBoxLayout stretches the form rows apart
        # to fill all the extra vertical space instead of collecting it
        # below the button row.
        layout.addStretch()

        self.date_edit.dateChanged.connect(self._mark_dirty)
        self.full_day_check.toggled.connect(self._mark_dirty)
        self.start_time_edit.timeChanged.connect(self._mark_dirty)
        self.end_time_edit.timeChanged.connect(self._mark_dirty)
        self.reason_edit.textChanged.connect(self._mark_dirty)

        apply_large_form_style(self)
        self._loading = False
        self._reset_fields()

    def refresh(self, start_dt=None):
        """Re-anchors the form's date/time defaults to "now" (or a given
        moment) - without this, a persistently-embedded form (the Admin
        tab) would keep showing whatever date happened to be current when
        the widget was first constructed, potentially hours or days stale."""
        self._default_start_dt = start_dt or datetime.now()
        self._reset_fields()

    def _reset_fields(self):
        # Guards _mark_dirty() while these fields are being set
        # programmatically (initial load, refresh(), Cancel, or a
        # just-completed Save) - none of those are a user edit, so none of
        # them should re-enable Save/Cancel.
        self._loading = True
        start_dt = self._default_start_dt
        self.date_edit.setDate(QDate(start_dt.year, start_dt.month, start_dt.day))
        self.full_day_check.setChecked(False)
        self.start_time_edit.setTime(QTime(start_dt.hour, start_dt.minute))
        end_default = start_dt + timedelta(minutes=30)
        self.end_time_edit.setTime(QTime(end_default.hour, end_default.minute))
        self.reason_edit.clear()
        self._loading = False
        self._mark_clean()

    def _mark_dirty(self):
        if self._loading:
            return
        self.cancel_btn.setEnabled(True)
        self.save_btn.setEnabled(True)

    def _mark_clean(self):
        self.cancel_btn.setEnabled(False)
        self.save_btn.setEnabled(False)

    def _toggle_full_day(self, checked):
        self.start_time_edit.setEnabled(not checked)
        self.end_time_edit.setEnabled(not checked)

    def _cancel(self):
        self._reset_fields()
        if self._on_cancel_extra:
            self._on_cancel_extra()

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
