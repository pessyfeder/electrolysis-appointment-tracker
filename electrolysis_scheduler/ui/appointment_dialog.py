from datetime import datetime, timedelta

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox, QDateEdit, QTimeEdit,
    QSpinBox, QTextEdit, QPushButton, QLabel, QMessageBox, QCompleter
)
from PySide6.QtCore import QDate, QTime, Qt

from app import models, scheduling, billing
from app.util import format_12h
from ui.client_dialog import ClientDialog

STATUS_LABELS = {
    "scheduled": "Scheduled",
    "in_process": "In Progress",
    "completed": "Completed",
    "cancelled": "Cancelled",
    "no_show": "No-Show",
}


class AppointmentDialog(QDialog):
    def __init__(self, parent=None, appt_row=None, start_dt=None, client_id=None):
        super().__init__(parent)
        self.appt_row = appt_row
        self.appt_id = appt_row["id"] if appt_row else None
        self.setWindowTitle("Edit Appointment" if appt_row else "New Appointment")
        self.setMinimumWidth(400)
        self.result_changed = False

        layout = QVBoxLayout(self)

        if appt_row:
            status_label = QLabel(f"Status: {STATUS_LABELS.get(appt_row['status'], appt_row['status'])}")
            status_label.setStyleSheet("font-weight: 600;")
            layout.addWidget(status_label)
            self.status_label = status_label
        else:
            self.status_label = None

        form = QFormLayout()

        client_row_widget = QHBoxLayout()
        self.client_combo = QComboBox()
        self.client_combo.setEditable(True)
        self.client_combo.setInsertPolicy(QComboBox.NoInsert)
        self._clients = models.list_clients()
        for c in self._clients:
            self.client_combo.addItem(f"{c['last_name']}, {c['first_name']} — {c['phone']}", c["id"])
        self.client_combo.setCurrentIndex(-1)
        completer = QCompleter([self.client_combo.itemText(i) for i in range(self.client_combo.count())])
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.client_combo.setCompleter(completer)
        quick_add_btn = QPushButton("+ New Client")
        quick_add_btn.clicked.connect(self._quick_add_client)
        client_row_widget.addWidget(self.client_combo, 1)
        client_row_widget.addWidget(quick_add_btn)
        form.addRow("Client:", client_row_widget)

        if appt_row:
            for i in range(self.client_combo.count()):
                if self.client_combo.itemData(i) == appt_row["client_id"]:
                    self.client_combo.setCurrentIndex(i)
                    break
        elif client_id:
            for i in range(self.client_combo.count()):
                if self.client_combo.itemData(i) == client_id:
                    self.client_combo.setCurrentIndex(i)
                    break

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("h:mm AP")
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(15, 240)
        self.duration_spin.setSingleStep(15)
        self.duration_spin.setSuffix(" min")
        self.duration_spin.setValue(30)

        if appt_row:
            s = datetime.fromisoformat(appt_row["start_datetime"])
            e = datetime.fromisoformat(appt_row["end_datetime"])
            self.date_edit.setDate(QDate(s.year, s.month, s.day))
            self.time_edit.setTime(QTime(s.hour, s.minute))
            self.duration_spin.setValue(int((e - s).total_seconds() // 60))
        elif start_dt:
            self.date_edit.setDate(QDate(start_dt.year, start_dt.month, start_dt.day))
            self.time_edit.setTime(QTime(start_dt.hour, start_dt.minute))
        else:
            today = QDate.currentDate()
            self.date_edit.setDate(today)

        form.addRow("Date:", self.date_edit)
        form.addRow("Start time:", self.time_edit)
        form.addRow("Duration:", self.duration_spin)

        self.end_time_label = QLabel()
        form.addRow("Ends:", self.end_time_label)
        self.date_edit.dateChanged.connect(self._refresh_end_label)
        self.time_edit.timeChanged.connect(self._refresh_end_label)
        self.duration_spin.valueChanged.connect(self._refresh_end_label)
        self._refresh_end_label()

        self.notes_edit = QTextEdit(appt_row["notes"] if appt_row and appt_row["notes"] else "")
        self.notes_edit.setFixedHeight(70)
        form.addRow("Notes:", self.notes_edit)

        layout.addLayout(form)

        if appt_row and appt_row["status"] == "completed" and appt_row["price"] is not None:
            price_label = QLabel(f"Price: ${appt_row['price']:.2f}")
            price_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #1e7e34;")
            layout.addWidget(price_label)

        # Editable fields only make sense while still scheduled
        editable = (appt_row is None) or (appt_row["status"] == "scheduled")
        for w in (self.client_combo, self.date_edit, self.time_edit, self.duration_spin, self.notes_edit):
            w.setEnabled(editable)

        btn_row = QHBoxLayout()

        if appt_row and appt_row["status"] == "scheduled":
            start_btn = QPushButton("Start Session")
            start_btn.clicked.connect(self._start_session)
            btn_row.addWidget(start_btn)
            no_show_btn = QPushButton("Mark No-Show")
            no_show_btn.clicked.connect(self._mark_no_show)
            btn_row.addWidget(no_show_btn)
            cancel_appt_btn = QPushButton("Cancel Appointment")
            cancel_appt_btn.clicked.connect(self._cancel_appointment)
            btn_row.addWidget(cancel_appt_btn)

        if appt_row and appt_row["status"] == "in_process":
            end_btn = QPushButton("End Session")
            end_btn.setStyleSheet("font-weight: 600;")
            end_btn.clicked.connect(self._end_session)
            btn_row.addWidget(end_btn)

        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)

        if editable:
            save_btn = QPushButton("Save")
            save_btn.setDefault(True)
            save_btn.clicked.connect(self._save)
            btn_row.addWidget(save_btn)

        layout.addLayout(btn_row)

    def _refresh_end_label(self):
        s = self._current_start()
        e = s + timedelta(minutes=self.duration_spin.value())
        self.end_time_label.setText(format_12h(e))

    def _current_start(self):
        d = self.date_edit.date()
        t = self.time_edit.time()
        return datetime(d.year(), d.month(), d.day(), t.hour(), t.minute())

    def _quick_add_client(self):
        dlg = ClientDialog(self)
        if dlg.exec():
            self._clients = models.list_clients()
            self.client_combo.clear()
            for c in self._clients:
                self.client_combo.addItem(f"{c['last_name']}, {c['first_name']} — {c['phone']}", c["id"])
            for i in range(self.client_combo.count()):
                if self.client_combo.itemData(i) == dlg.client_id:
                    self.client_combo.setCurrentIndex(i)
                    break

    def _selected_client_id(self):
        idx = self.client_combo.currentIndex()
        if idx < 0:
            return None
        return self.client_combo.itemData(idx)

    def _save(self):
        client_id = self._selected_client_id()
        if not client_id:
            QMessageBox.warning(self, "Missing Client", "Please select or add a client.")
            return
        start_dt = self._current_start()
        end_dt = start_dt + timedelta(minutes=self.duration_spin.value())
        try:
            scheduling.validate_appointment(client_id, start_dt, end_dt, exclude_id=self.appt_id)
        except scheduling.SchedulingError as e:
            QMessageBox.warning(self, "Can't Book That Time", str(e))
            return

        if self.appt_id:
            models.update_appointment(self.appt_id, client_id, start_dt, end_dt, self.notes_edit.toPlainText())
        else:
            models.create_appointment(client_id, start_dt, end_dt, self.notes_edit.toPlainText())
        self.result_changed = True
        self.accept()

    def _start_session(self):
        from app.db import now_iso
        models.start_session(self.appt_id, now_iso())
        self.result_changed = True
        self.accept()

    def _end_session(self):
        started = self.appt_row["session_started_at"]
        started_dt = datetime.fromisoformat(started) if started else datetime.fromisoformat(self.appt_row["start_datetime"])
        ended_dt = datetime.now()
        if ended_dt <= started_dt:
            ended_dt = started_dt + timedelta(minutes=1)
        price = billing.calculate_price(started_dt, ended_dt)
        models.end_session(self.appt_id, price)
        QMessageBox.information(self, "Session Complete", f"Amount owed: ${price:.2f}")
        self.result_changed = True
        self.accept()

    def _mark_no_show(self):
        models.set_appointment_status(self.appt_id, "no_show")
        self.result_changed = True
        self.accept()

    def _cancel_appointment(self):
        if QMessageBox.question(self, "Cancel Appointment", "Cancel this appointment?") == QMessageBox.Yes:
            models.set_appointment_status(self.appt_id, "cancelled")
            self.result_changed = True
            self.accept()
