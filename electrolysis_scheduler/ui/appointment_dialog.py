from datetime import datetime, timedelta

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox, QDateEdit,
    QTextEdit, QPushButton, QLabel, QMessageBox, QCompleter, QGroupBox, QFrame,
    QApplication
)
from PySide6.QtCore import QDate, Qt, QEvent, QPoint, QPointF
from PySide6.QtGui import QMouseEvent

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


class _ClickToOpenDateEdit(QDateEdit):
    """Clicking anywhere on the field opens the calendar popup - the same
    click-to-open behavior as the start-time dropdown - instead of
    requiring the small calendar-icon button specifically. Past dates are
    excluded via minimumDate, which Qt's calendar renders grayed out and
    refuses to select.

    Implemented by replaying the click at the button's own position and
    routing it straight to QDateEdit's real handler (bypassing this
    override, which would otherwise re-enter itself and recurse forever)."""

    def mousePressEvent(self, event):
        if self.isEnabled() and self.calendarPopup():
            pos = QPoint(max(0, self.width() - 12), self.height() // 2)
            press = QMouseEvent(QEvent.MouseButtonPress, QPointF(pos), self.mapToGlobal(pos),
                                 Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
            release = QMouseEvent(QEvent.MouseButtonRelease, QPointF(pos), self.mapToGlobal(pos),
                                   Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
            QDateEdit.mousePressEvent(self, press)
            QDateEdit.mouseReleaseEvent(self, release)
        else:
            super().mousePressEvent(event)


class AppointmentDialog(QDialog):
    def __init__(self, parent=None, appt_row=None, start_dt=None, client_id=None, require_admin=None):
        super().__init__(parent)
        self.require_admin = require_admin or (lambda: True)
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

        self.date_edit = _ClickToOpenDateEdit()
        self.date_edit.setCalendarPopup(True)
        if self._timing_editable:
            # Past dates are never bookable, whether this is a brand-new
            # appointment or an editable (not-yet-started) one being
            # rescheduled - grayed out and unselectable in the calendar.
            self.date_edit.setMinimumDate(QDate.currentDate())
        self.date_edit.setEnabled(self._timing_editable)

        self.time_combo = QComboBox()
        self.time_combo.setEnabled(self._timing_editable)

        self.duration_combo = QComboBox()
        self.duration_combo.setEnabled(self._timing_editable)

        initial_duration = None
        if appt_row:
            s = datetime.fromisoformat(appt_row["start_datetime"])
            e = datetime.fromisoformat(appt_row["end_datetime"])
            self.date_edit.setDate(QDate(s.year, s.month, s.day))
            initial_start_dt = s
            initial_duration = int((e - s).total_seconds() // 60)
        elif start_dt:
            self.date_edit.setDate(QDate(start_dt.year, start_dt.month, start_dt.day))
            initial_start_dt = start_dt
        else:
            self.date_edit.setDate(QDate.currentDate())
            initial_start_dt = scheduling.earliest_bookable_start(datetime.now().date())

        form.addRow("Date: *", self.date_edit)
        form.addRow("Start time: *", self.time_combo)
        form.addRow("Duration: *", self.duration_combo)

        self.end_time_label = QLabel()
        form.addRow("Ends:", self.end_time_label)

        if self._timing_editable:
            self.date_edit.dateChanged.connect(self._on_date_changed)
            self.time_combo.currentIndexChanged.connect(self._on_date_or_time_changed)
            self.duration_combo.currentIndexChanged.connect(self._refresh_end_label)
            self._populate_time_options(self.date_edit.date().toPython(), initial_dt=initial_start_dt)
            self._refresh_duration_options(initial=initial_duration)
        else:
            self.time_combo.addItem(format_12h(initial_start_dt), initial_start_dt)
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
        dt = self.time_combo.currentData()
        if dt is not None:
            return dt
        d = self.date_edit.date()
        return datetime(d.year(), d.month(), d.day(), 0, 0)

    def _populate_time_options(self, date_, initial_dt=None):
        """Fills the start-time dropdown with every 5-minute-interval time
        on `date_` that a minimum-length appointment could start at (spec:
        clicking Start Time should show a dropdown with ALL possible start
        times in 5-minute intervals; selecting one displays it in the
        field). `initial_dt` is kept in the list even if it wouldn't
        otherwise be offered, so editing an appointment always shows its
        own current time as an option."""
        candidates = scheduling.bookable_start_candidates(date_, exclude_id=self.appt_id)
        if initial_dt is not None and initial_dt not in candidates:
            candidates = sorted(candidates + [initial_dt])

        self.time_combo.blockSignals(True)
        self.time_combo.clear()
        for dt in candidates:
            label = format_12h(dt)
            if dt == candidates[0]:
                label += "  (earliest)"
            self.time_combo.addItem(label, dt)
        target = initial_dt if initial_dt is not None else (candidates[0] if candidates else None)
        idx = self.time_combo.findData(target) if target is not None else -1
        if idx < 0 and self.time_combo.count():
            idx = 0
        if idx >= 0:
            self.time_combo.setCurrentIndex(idx)
        self.time_combo.blockSignals(False)

    def _on_date_changed(self):
        self._populate_time_options(self.date_edit.date().toPython())
        self._refresh_duration_options()

    def _on_date_or_time_changed(self):
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
            start_btn.setToolTip("Requires the admin password")
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
            end_btn.setToolTip("Requires the admin password")
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
        # Several callers (e.g. End Session) immediately pop a modal
        # QMessageBox right after this. Without forcing the pending layout/
        # paint to flush first, the freshly recolored row wouldn't actually
        # get drawn until something later forced a repaint - it would look
        # like the color change only "took" after reopening the dialog.
        QApplication.processEvents()

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
        # Starting a session begins the billing clock, so it's admin-gated
        # to prevent an accidental tap from starting the wrong client.
        if not self.require_admin():
            return
        from app.db import now_iso
        models.start_client_session(c["id"], now_iso())
        self.result_changed = True
        self._reload_from_db()

    def _end_client(self, c):
        # Ending a session locks in the billed price, so it's admin-gated
        # for the same reason starting one is.
        if not self.require_admin():
            return
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
