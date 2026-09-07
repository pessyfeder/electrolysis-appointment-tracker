from datetime import date, datetime, time, timedelta

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTimeEdit, QPushButton,
    QWidget, QMessageBox
)
from PySide6.QtCore import QDate, QTime, Signal

from app import models, scheduling
from app.util import format_12h, format_client_name
from ui.widgets import ClickToOpenDateEdit, required_label, apply_large_form_style


class _BlockRow(QWidget):
    changed = Signal()

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
        self.start_edit.timeChanged.connect(self.changed)
        self.end_edit.timeChanged.connect(self.changed)
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
    """Overrides business hours for one specific date - not a recurring
    weekly change. Mirrors BlockTimeForm's pattern (pick a date, edit,
    Save/Cancel) rather than the old per-weekday grouped editor, since a
    change here is meant to affect just the selected date - every other
    date, including every other occurrence of that same weekday, keeps
    using its normal schedule.

    Picking a date loads whatever's currently in effect for it: its
    existing override if one has been set, otherwise its normal weekday
    hours as an editable starting point. Reset to Default Hours removes the
    override entirely, reverting the date back to that weekday's schedule.

    `on_saved` is called after a successful save or reset (dialog usage
    passes `self.accept`; a persistent embedding does its own refresh
    instead). Cancel, next to Save, always discards any unsaved edits and
    reloads the selected date's current effective hours - for the modal
    dialog that's immediately followed by closing it (`on_cancel`, if
    given, e.g. `self.reject`, runs right after); the always-embedded Admin
    tab just needs the revert, so it passes nothing extra. `require_admin`,
    if given, is asked right before a save/reset actually persists - the
    modal dialog's caller already re-verifies the admin password before
    ever opening it, so it passes nothing (no double prompt); the Admin tab
    has no such "before opening" moment since it's always on screen, so it
    gates at Save/Reset instead."""

    def __init__(self, parent=None, require_admin=None, on_saved=None, on_cancel=None):
        super().__init__(parent)
        self.require_admin = require_admin or (lambda: True)
        self.on_saved = on_saved or (lambda: None)
        self._on_cancel_extra = on_cancel
        self._loading = False
        self._rows = []

        outer = QVBoxLayout(self)

        date_row = QHBoxLayout()
        date_row.addWidget(required_label("Date:"))
        self.date_edit = ClickToOpenDateEdit()
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.dateChanged.connect(self._load_for_current_date)
        date_row.addWidget(self.date_edit)
        date_row.addStretch()
        outer.addLayout(date_row)

        self.status_hint = QLabel("")
        self.status_hint.setWordWrap(True)
        self.status_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        outer.addWidget(self.status_hint)

        self.rows_container = QVBoxLayout()
        outer.addLayout(self.rows_container)

        self.add_row_btn = QPushButton("+ Add time block")
        self.add_row_btn.clicked.connect(lambda: self._add_row())
        outer.addWidget(self.add_row_btn)

        outer.addStretch()

        self.reset_btn = QPushButton("Reset to Default Hours")
        self.reset_btn.clicked.connect(self._reset_to_default)
        outer.addWidget(self.reset_btn)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        # Save/Cancel start disabled - nothing has changed yet, so there's
        # nothing to save or to cancel out of. _mark_dirty() (wired to every
        # row's add/remove/edit) enables both; a successful Save or Cancel
        # puts them back to a clean, disabled state.
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        btn_row.addWidget(self.cancel_btn)
        self.save_btn = QPushButton("Save")
        self.save_btn.setEnabled(False)
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._save)
        btn_row.addWidget(self.save_btn)
        outer.addLayout(btn_row)

        apply_large_form_style(self)
        self._load_for_current_date()

    def _current_date(self):
        d = self.date_edit.date()
        return date(d.year(), d.month(), d.day())

    def _load_for_current_date(self):
        self._loading = True
        d = self._current_date()
        override = models.get_business_hours_override(d.isoformat())
        has_override = override is not None
        if has_override:
            blocks = override
            self.status_hint.setText(
                f"{d.strftime('%A, %b %d, %Y')} has custom hours set - editing below changes "
                "only this date."
            )
        else:
            weekday_rows = models.business_hours_for_day(scheduling.day_name(d))
            blocks = [(r["start_time"], r["end_time"]) for r in weekday_rows]
            self.status_hint.setText(
                f"Showing {d.strftime('%A')}'s normal hours. Saving sets custom hours for "
                f"{d.strftime('%b %d, %Y')} only - every other {d.strftime('%A')} is unaffected."
            )

        self._clear_rows()
        for s, e in blocks:
            self._add_row(s, e, mark_dirty=False)
        self.reset_btn.setEnabled(has_override)

        self._loading = False
        self._mark_clean()

    def _clear_rows(self):
        for row in list(self._rows):
            self.rows_container.removeWidget(row)
            row.deleteLater()
        self._rows = []

    def _add_row(self, start_time="10:00", end_time="17:00", mark_dirty=True):
        def remove(row_widget):
            self._rows.remove(row_widget)
            self.rows_container.removeWidget(row_widget)
            row_widget.deleteLater()
            self._mark_dirty()

        row = _BlockRow(start_time, end_time, on_remove=remove)
        row.changed.connect(self._mark_dirty)
        self._rows.append(row)
        self.rows_container.addWidget(row)
        if mark_dirty:
            self._mark_dirty()

    def _mark_dirty(self):
        if self._loading:
            return
        self.cancel_btn.setEnabled(True)
        self.save_btn.setEnabled(True)

    def _mark_clean(self):
        self.cancel_btn.setEnabled(False)
        self.save_btn.setEnabled(False)

    def _cancel(self):
        self._load_for_current_date()
        if self._on_cancel_extra:
            self._on_cancel_extra()

    def _reset_to_default(self):
        if not self.require_admin():
            return
        d = self._current_date()
        models.clear_business_hours_override(d.isoformat())
        self._load_for_current_date()
        self.on_saved()

    def _collect_blocks(self):
        """Returns (blocks, error_message). error_message is None when the
        rows describe a valid set of hours. Closing a date entirely is
        Block Time Off's job, not this editor's - so unlike an ordinary
        time block, an empty row list here is rejected rather than treated
        as "closed all day"."""
        blocks = []
        for row in self._rows:
            s, e = row.as_tuple()
            if s >= e:
                return None, "End time must be after start time."
            blocks.append((s, e))
        if not blocks:
            return None, 'Add at least one time block. To close this date entirely, use "Block Time Off" instead.'
        return blocks, None

    def _save(self):
        if not self.require_admin():
            return

        blocks, error = self._collect_blocks()
        if error:
            QMessageBox.warning(self, "Invalid Hours", error)
            return

        d = self._current_date()
        conflicts = self._find_conflicts(d, blocks)
        if conflicts:
            lines = "\n".join(f"- {c}" for c in conflicts)
            QMessageBox.warning(
                self, "Appointments Conflict With New Hours",
                f"These appointments on {d.strftime('%b %d, %Y')} no longer fit inside the new "
                "hours. Reschedule or cancel them first, then save again:\n\n" + lines
            )
            return

        models.set_business_hours_override(d.isoformat(), blocks)
        self._load_for_current_date()
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

    def _find_conflicts(self, d, blocks):
        """Appointments on `d` that no longer fit inside the proposed
        hours for that one date."""
        range_start = datetime.combine(d, time(0, 0))
        range_end = range_start + timedelta(days=1)
        appts = models.list_appointments_between(range_start, range_end)
        conflicts = []
        for a in appts:
            if a["status"] not in models.ACTIVE_STATUSES:
                continue
            s = datetime.fromisoformat(a["start_datetime"])
            e = datetime.fromisoformat(a["end_datetime"])
            if not self._fits_a_block(s, e, blocks):
                names = ", ".join(format_client_name(c["first_name"], c["last_name"]) for c in a["clients"])
                conflicts.append(f"{format_12h(s)}–{format_12h(e)}: {names}")
        return conflicts


class BusinessHoursDialog(QDialog):
    """Edit business hours for one specific date. Caller must re-verify the
    admin password before opening this dialog (spec 7.4)."""

    def __init__(self, parent=None, start_dt=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Business Hours")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        self.editor = BusinessHoursEditor(self, on_saved=self.accept, on_cancel=self.reject)
        if start_dt is not None:
            self.editor.date_edit.setDate(QDate(start_dt.year, start_dt.month, start_dt.day))
        layout.addWidget(self.editor)
