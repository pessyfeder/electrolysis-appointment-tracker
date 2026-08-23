from datetime import datetime, timedelta

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox, QDateEdit, QTimeEdit,
    QTextEdit, QPushButton, QLabel, QMessageBox, QCompleter, QGroupBox, QFrame
)
from PySide6.QtCore import QDate, QTime, Qt

from app import models, scheduling, billing
from app.util import format_12h, format_client_name, format_phone, format_duration_minutes
from ui.client_dialog import ClientDialog

STATUS_LABELS = {
    "scheduled": "Scheduled",
    "in_process": "In Progress",
    "completed": "Completed",
    "cancelled": "Cancelled",
    "no_show": "No-Show",
}

# (background, border, text) per client-session status - used both for the
# calendar cards and the per-client "session" rows below (spec: session
# label should change color by status and show the status).
STATUS_ROW_STYLES = {
    "scheduled": ("#eff6ff", "#bfdbfe", "#1d4ed8"),
    "in_process": ("#fffbeb", "#fde68a", "#b45309"),
    "completed": ("#f0fdf4", "#bbf7d0", "#15803d"),
    "cancelled": ("#f8fafc", "#e2e8f0", "#64748b"),
    "no_show": ("#fef2f2", "#fecaca", "#b91c1c"),
}


class _NoticeTimeEdit(QTimeEdit):
    """The start time can always be typed in directly. The first time the
    field gains focus for a given date, it also pops up a notice listing
    that date's permissible (bookable) start times, rather than silently
    overwriting whatever the user has typed."""

    def __init__(self, on_focus, parent=None):
        super().__init__(parent)
        self._on_focus = on_focus

    def focusInEvent(self, event):
        super().focusInEvent(event)
        if self.isEnabled():
            self._on_focus()


class AppointmentDialog(QDialog):
    def __init__(self, parent=None, appt_row=None, start_dt=None, client_id=None):
        super().__init__(parent)
        self.appt_row = appt_row
        self.appt_id = appt_row["id"] if appt_row else None
        self._is_new = appt_row is None
        self.setWindowTitle("Edit Appointment" if appt_row else "New Appointment")
        self.setMinimumWidth(440)
        self.result_changed = False

        if appt_row:
            self._clients = [dict(r) for r in appt_row["clients"]]
        else:
            self._clients = []
            if client_id:
                c = models.get_client(client_id)
                self._clients.append({
                    "id": None, "client_id": c["id"], "first_name": c["first_name"],
                    "last_name": c["last_name"], "phone": c["phone"], "status": "scheduled",
                    "session_started_at": None, "price": None,
                })

        # An appointment whose start time has already gone by is locked from
        # further date/time editing; likewise once any client's session has
        # actually started, the timing can no longer be changed retroactively.
        self._is_past = bool(appt_row and datetime.fromisoformat(appt_row["start_datetime"]) < datetime.now())
        self._any_session_started = any(c["status"] in ("in_process", "completed") for c in self._clients)
        self._timing_editable = self._is_new or (not self._is_past and not self._any_session_started)

        layout = QVBoxLayout(self)

        self.status_label = None
        if appt_row:
            status_label = QLabel(f"Overall status: {STATUS_LABELS.get(appt_row['status'], appt_row['status'])}")
            status_label.setStyleSheet("font-weight: 600;")
            layout.addWidget(status_label)
            self.status_label = status_label

        if appt_row and self._is_past and appt_row["status"] == "scheduled":
            past_note = QLabel(
                "This appointment's start time has already passed, so its date/time can no "
                "longer be changed. You can still manage each client's session below."
            )
            past_note.setWordWrap(True)
            past_note.setStyleSheet(
                "color: #92400e; background: #fffbeb; border: 1px solid #fde68a; "
                "border-radius: 6px; padding: 6px 10px;"
            )
            layout.addWidget(past_note)

        form = QFormLayout()

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        if self._is_new:
            self.date_edit.setMinimumDate(QDate.currentDate())
        self.date_edit.setEnabled(self._timing_editable)

        self._notified_date = None
        self.time_edit = _NoticeTimeEdit(self._notify_start_times)
        self.time_edit.setDisplayFormat("h:mm AP")
        self.time_edit.setEnabled(self._timing_editable)

        self.duration_combo = QComboBox()
        self.duration_combo.setEnabled(self._timing_editable)

        initial_duration = None
        if appt_row:
            s = datetime.fromisoformat(appt_row["start_datetime"])
            e = datetime.fromisoformat(appt_row["end_datetime"])
            self.date_edit.setDate(QDate(s.year, s.month, s.day))
            self.time_edit.setTime(QTime(s.hour, s.minute))
            initial_duration = int((e - s).total_seconds() // 60)
        elif start_dt:
            self.date_edit.setDate(QDate(start_dt.year, start_dt.month, start_dt.day))
            self.time_edit.setTime(QTime(start_dt.hour, start_dt.minute))
        else:
            self.date_edit.setDate(QDate.currentDate())

        form.addRow("Date: *", self.date_edit)
        form.addRow("Start time: *", self.time_edit)
        form.addRow("Duration: *", self.duration_combo)

        self.end_time_label = QLabel()
        form.addRow("Ends:", self.end_time_label)

        if self._timing_editable:
            self.date_edit.dateChanged.connect(self._on_date_or_time_changed)
            self.time_edit.timeChanged.connect(self._on_date_or_time_changed)
            self.duration_combo.currentIndexChanged.connect(self._refresh_end_label)
            self._refresh_duration_options(initial=initial_duration)
        else:
            self.duration_combo.addItem(format_duration_minutes(initial_duration), initial_duration)
            self._refresh_end_label()

        self.notes_edit = QTextEdit(appt_row["notes"] if appt_row and appt_row["notes"] else "")
        self.notes_edit.setFixedHeight(60)
        form.addRow("Notes (optional):", self.notes_edit)

        layout.addLayout(form)

        required_hint = QLabel("* Required")
        required_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(required_hint)

        clients_box = QGroupBox("Clients on this appointment")
        clients_box_layout = QVBoxLayout(clients_box)
        self.clients_container = QVBoxLayout()
        clients_box_layout.addLayout(self.clients_container)

        add_row = QHBoxLayout()
        add_existing_btn = QPushButton("+ Add Client")
        add_existing_btn.clicked.connect(self._add_existing_client)
        add_new_btn = QPushButton("+ New Client")
        add_new_btn.clicked.connect(self._add_new_client)
        add_row.addWidget(add_existing_btn)
        add_row.addWidget(add_new_btn)
        add_row.addStretch()
        clients_box_layout.addLayout(add_row)

        layout.addWidget(clients_box)

        self._rebuild_client_rows()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        save_btn = QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    # ---- timing helpers ----

    def _current_start(self):
        d = self.date_edit.date()
        t = self.time_edit.time()
        return datetime(d.year(), d.month(), d.day(), t.hour(), t.minute())

    def _on_date_or_time_changed(self):
        self._notified_date = None
        self._refresh_duration_options()

    def _refresh_duration_options(self, initial=None):
        start = self._current_start()
        options = scheduling.valid_durations(start, exclude_id=self.appt_id)
        current = self.duration_combo.currentData() if self.duration_combo.count() else None
        self.duration_combo.blockSignals(True)
        self.duration_combo.clear()
        for m in options:
            self.duration_combo.addItem(format_duration_minutes(m), m)
        target = initial if initial is not None else current
        idx = self.duration_combo.findData(target) if target is not None else -1
        if idx < 0 and self.duration_combo.count():
            idx = 0
        if idx >= 0:
            self.duration_combo.setCurrentIndex(idx)
        self.duration_combo.blockSignals(False)
        self._refresh_end_label()

    def _refresh_end_label(self):
        minutes = self.duration_combo.currentData()
        if minutes is None:
            self.end_time_label.setText("No valid duration for this start time")
            return
        end = self._current_start() + timedelta(minutes=minutes)
        self.end_time_label.setText(format_12h(end))

    def _notify_start_times(self):
        """Shown once per date the field is focused on (spec: 'clicking on
        Appointment Start Time should pop up window notifying user of
        permissible start times'). Purely informational - it never touches
        the field's value, so manually typed times are never overwritten."""
        if not self._timing_editable:
            return
        d = self.date_edit.date().toPython()
        if self._notified_date == d:
            return
        self._notified_date = d

        blocks = scheduling.business_blocks_for_date(d)
        if not blocks:
            QMessageBox.information(
                self, "No Availability",
                f"{d.strftime('%A, %b %d')} has no business hours open."
            )
            return

        lines = [f"• {format_12h(s)} – {format_12h(e)}" for s, e in blocks]
        message = f"Business hours on {d.strftime('%A, %b %d')}:\n" + "\n".join(lines)
        earliest = scheduling.earliest_bookable_start(d, exclude_id=self.appt_id)
        if earliest:
            message += f"\n\nEarliest available start time: {format_12h(earliest)}"
        else:
            message += "\n\nNo open start times remain on this date."
        message += "\n\nYou can type any start time directly into the field."
        QMessageBox.information(self, "Permissible Start Times", message)

    # ---- client list ----

    def _rebuild_client_rows(self):
        while self.clients_container.count():
            item = self.clients_container.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if not self._clients:
            empty = QLabel("No clients added yet.")
            empty.setStyleSheet("color: #94a3b8; font-style: italic; padding: 4px;")
            self.clients_container.addWidget(empty)
        for c in self._clients:
            self.clients_container.addWidget(self._build_client_row(c))

    def _build_client_row(self, c):
        row = QFrame()
        row.setObjectName("clientRow")
        status = c["status"]
        bg, border, text_color = STATUS_ROW_STYLES.get(status, ("#f8fafc", "#e2e8f0", "#1e293b"))
        row.setStyleSheet(
            f"#clientRow {{ background: {bg}; border: 1px solid {border}; border-radius: 8px; }}"
        )
        h = QHBoxLayout(row)
        name = format_client_name(c["first_name"], c["last_name"])
        detail = STATUS_LABELS.get(status, status)
        if status == "completed" and c.get("price") is not None:
            detail += f" — ${c['price']:.2f}"
        info = QLabel()
        info.setTextFormat(Qt.RichText)
        info.setText(
            f"{name} — {format_phone(c['phone'])}"
            f"<br><span style='color:{text_color}; font-weight:600;'>{detail}</span>"
        )
        info.setWordWrap(True)
        h.addWidget(info, 1)

        edit_btn = QPushButton("Edit Info")
        edit_btn.clicked.connect(lambda checked=False, c=c: self._edit_client_info(c))
        h.addWidget(edit_btn)

        if status == "scheduled":
            start_btn = QPushButton("Start Session")
            start_btn.clicked.connect(lambda checked=False, c=c: self._start_client(c))
            h.addWidget(start_btn)
            no_show_btn = QPushButton("No-Show")
            no_show_btn.clicked.connect(lambda checked=False, c=c: self._set_status(c, "no_show"))
            h.addWidget(no_show_btn)
            cancel_btn = QPushButton("Cancel")
            cancel_btn.clicked.connect(lambda checked=False, c=c: self._set_status(c, "cancelled"))
            h.addWidget(cancel_btn)
            if len(self._clients) > 1:
                remove_btn = QPushButton("Remove")
                remove_btn.clicked.connect(lambda checked=False, c=c: self._remove_client(c))
                h.addWidget(remove_btn)
        elif status == "in_process":
            end_btn = QPushButton("End Session")
            end_btn.setStyleSheet("font-weight: 600;")
            end_btn.clicked.connect(lambda checked=False, c=c: self._end_client(c))
            h.addWidget(end_btn)

        return row

    def _reload_from_db(self):
        self.appt_row = models.get_appointment(self.appt_id)
        self._clients = [dict(r) for r in self.appt_row["clients"]]
        self._any_session_started = any(c["status"] in ("in_process", "completed") for c in self._clients)
        if self.status_label:
            self.status_label.setText(
                f"Overall status: {STATUS_LABELS.get(self.appt_row['status'], self.appt_row['status'])}"
            )
        self._rebuild_client_rows()

    def _edit_client_info(self, c):
        dlg = ClientDialog(self, client_row=models.get_client(c["client_id"]))
        if dlg.exec():
            updated = models.get_client(c["client_id"])
            c["first_name"], c["last_name"], c["phone"] = updated["first_name"], updated["last_name"], updated["phone"]
            self._rebuild_client_rows()

    def _attach_client(self, client_id):
        c = models.get_client(client_id)
        if self._is_new:
            self._clients.append({
                "id": None, "client_id": c["id"], "first_name": c["first_name"],
                "last_name": c["last_name"], "phone": c["phone"], "status": "scheduled",
                "session_started_at": None, "price": None,
            })
            self._rebuild_client_rows()
        else:
            models.add_client_to_appointment(self.appt_id, client_id)
            self.result_changed = True
            self._reload_from_db()

    def _add_existing_client(self):
        existing_ids = {c["client_id"] for c in self._clients}
        available = [c for c in models.list_clients() if c["id"] not in existing_ids]
        if not available:
            QMessageBox.information(self, "No Other Clients", "There are no other clients to add.")
            return

        picker = QDialog(self)
        picker.setWindowTitle("Add Client")
        picker.setMinimumWidth(360)
        v = QVBoxLayout(picker)
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        for cl in available:
            combo.addItem(f"{format_client_name(cl['first_name'], cl['last_name'])} — {format_phone(cl['phone'])}", cl["id"])
        completer = QCompleter([combo.itemText(i) for i in range(combo.count())])
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        combo.setCompleter(completer)
        combo.setCurrentIndex(-1)
        v.addWidget(combo)
        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(picker.reject)
        add_btn = QPushButton("Add")
        add_btn.setDefault(True)
        add_btn.clicked.connect(picker.accept)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(add_btn)
        v.addLayout(btn_row)

        if picker.exec() != QDialog.Accepted:
            return
        # currentIndex() only updates once an item is actually picked from
        # the dropdown/completer - typing a name and clicking Add without
        # selecting a suggestion would otherwise silently do nothing, so
        # fall back to resolving the typed text against the item list.
        idx = combo.currentIndex()
        text = combo.currentText().strip()
        if idx < 0 or combo.itemText(idx) != text:
            idx = combo.findText(text, Qt.MatchFixedString)
        if idx < 0:
            QMessageBox.warning(self, "No Client Selected", "Please select a client from the list.")
            return
        client_id = combo.itemData(idx)
        if client_id:
            self._attach_client(client_id)

    def _add_new_client(self):
        dlg = ClientDialog(self)
        if dlg.exec():
            self._attach_client(dlg.client_id)

    def _remove_client(self, c):
        if len(self._clients) <= 1:
            return
        name = format_client_name(c["first_name"], c["last_name"])
        if QMessageBox.question(self, "Remove Client", f"Remove {name} from this appointment?") != QMessageBox.Yes:
            return
        if self._is_new:
            self._clients = [x for x in self._clients if x is not c]
            self._rebuild_client_rows()
        else:
            models.remove_appointment_client(c["id"])
            self.result_changed = True
            self._reload_from_db()

    def _start_client(self, c):
        if self._is_new:
            QMessageBox.information(self, "Save First", "Save the appointment before starting a session.")
            return
        from app.db import now_iso
        models.start_client_session(c["id"], now_iso())
        self.result_changed = True
        self._reload_from_db()

    def _end_client(self, c):
        started = c.get("session_started_at")
        started_dt = datetime.fromisoformat(started) if started else datetime.fromisoformat(self.appt_row["start_datetime"])
        ended_dt = datetime.now()
        if ended_dt <= started_dt:
            ended_dt = started_dt + timedelta(minutes=1)
        price = billing.calculate_price(started_dt, ended_dt)
        models.end_client_session(c["id"], price)
        self.result_changed = True
        name = format_client_name(c["first_name"], c["last_name"])
        self._reload_from_db()
        QMessageBox.information(self, "Session Complete", f"Amount owed by {name}: ${price:.2f}")

        next_c = next((x for x in self._clients if x["status"] == "scheduled"), None)
        if next_c:
            next_name = format_client_name(next_c["first_name"], next_c["last_name"])
            if QMessageBox.question(
                self, "Start Next Client?", f"Start the session for {next_name} now?"
            ) == QMessageBox.Yes:
                self._start_client(next_c)

    def _set_status(self, c, status):
        verb = "mark this client as a no-show" if status == "no_show" else "cancel this client's appointment"
        name = format_client_name(c["first_name"], c["last_name"])
        if QMessageBox.question(self, "Confirm", f"Are you sure you want to {verb} for {name}?") != QMessageBox.Yes:
            return
        models.set_client_status(c["id"], status)
        self.result_changed = True
        self._reload_from_db()

    # ---- save ----

    def _save(self):
        if not self._clients:
            QMessageBox.warning(self, "No Clients", "Add at least one client to this appointment.")
            return

        minutes = self.duration_combo.currentData()
        if minutes is None:
            QMessageBox.warning(self, "Invalid Duration", "Choose a valid duration for this start time.")
            return

        start_dt = self._current_start()
        end_dt = start_dt + timedelta(minutes=minutes)
        try:
            scheduling.validate_appointment(start_dt, end_dt, exclude_id=self.appt_id)
        except scheduling.SchedulingError as e:
            QMessageBox.warning(self, "Can't Book That Time", str(e))
            return

        notes = self.notes_edit.toPlainText()
        if self.appt_id:
            models.update_appointment(self.appt_id, start_dt, end_dt, notes)
        else:
            client_ids = [c["client_id"] for c in self._clients]
            self.appt_id = models.create_appointment(client_ids, start_dt, end_dt, notes)
            self._is_new = False
        self.result_changed = True
        self.accept()
