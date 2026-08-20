from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QSplitter, QMessageBox,
    QHeaderView, QCheckBox
)
from PySide6.QtCore import Qt

from app import models
from app.util import format_12h
from ui.client_dialog import ClientDialog

STATUS_LABELS = {
    "scheduled": "Scheduled", "in_process": "In Progress", "completed": "Completed",
    "cancelled": "Cancelled", "no_show": "No-Show",
}


class ClientsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_client_id = None

        splitter = QSplitter()
        root = QHBoxLayout(self)
        root.addWidget(splitter)

        # --- Left: search + list ---
        left = QWidget()
        left_layout = QVBoxLayout(left)
        top_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search by name or phone…")
        self.search_edit.textChanged.connect(self.refresh_list)
        self.show_archived_check = QCheckBox("Show archived")
        self.show_archived_check.toggled.connect(self.refresh_list)
        top_row.addWidget(self.search_edit)
        left_layout.addLayout(top_row)
        left_layout.addWidget(self.show_archived_check)

        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._on_select)
        left_layout.addWidget(self.list_widget)

        add_btn = QPushButton("+ Add Client")
        add_btn.clicked.connect(self._add_client)
        left_layout.addWidget(add_btn)

        splitter.addWidget(left)

        # --- Right: detail panel ---
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.name_label = QLabel("Select a client")
        self.name_label.setStyleSheet("font-size: 18px; font-weight: 600;")
        right_layout.addWidget(self.name_label)

        self.phone_label = QLabel("")
        right_layout.addWidget(self.phone_label)
        self.notes_label = QLabel("")
        self.notes_label.setWordWrap(True)
        right_layout.addWidget(self.notes_label)

        self.balance_label = QLabel("")
        self.balance_label.setStyleSheet("font-size: 14px; font-weight: 600;")
        right_layout.addWidget(self.balance_label)

        btn_row = QHBoxLayout()
        edit_btn = QPushButton("Edit")
        edit_btn.clicked.connect(self._edit_client)
        self.archive_btn = QPushButton("Archive")
        self.archive_btn.clicked.connect(self._toggle_archive)
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(self.archive_btn)
        btn_row.addStretch()
        right_layout.addLayout(btn_row)

        right_layout.addWidget(QLabel("Appointment History"))
        self.appt_table = QTableWidget(0, 4)
        self.appt_table.setHorizontalHeaderLabels(["Date", "Status", "Notes", "Price"])
        self.appt_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.appt_table.setEditTriggers(QTableWidget.NoEditTriggers)
        right_layout.addWidget(self.appt_table)

        right_layout.addWidget(QLabel("Payment History"))
        self.payment_table = QTableWidget(0, 4)
        self.payment_table.setHorizontalHeaderLabels(["Date", "Amount", "Method", "Notes"])
        self.payment_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.payment_table.setEditTriggers(QTableWidget.NoEditTriggers)
        right_layout.addWidget(self.payment_table)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        self.refresh_list()

    def refresh_list(self):
        search = self.search_edit.text().strip()
        self.list_widget.clear()
        rows = models.list_clients(search=search, include_archived=self.show_archived_check.isChecked())
        for c in rows:
            label = f"{c['last_name']}, {c['first_name']}" + (" (archived)" if c["archived"] else "")
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, c["id"])
            self.list_widget.addItem(item)

    def _on_select(self, current, previous):
        if not current:
            self.selected_client_id = None
            return
        self.selected_client_id = current.data(Qt.UserRole)
        self._refresh_detail()

    def _refresh_detail(self):
        if not self.selected_client_id:
            return
        c = models.get_client(self.selected_client_id)
        if not c:
            return
        self.name_label.setText(f"{c['first_name']} {c['last_name']}" + (" (archived)" if c["archived"] else ""))
        self.phone_label.setText(f"Phone: {c['phone']}")
        self.notes_label.setText(f"Notes: {c['notes'] or '—'}")
        self.archive_btn.setText("Unarchive" if c["archived"] else "Archive")

        balance = models.client_balance(c["id"])
        if balance > 0:
            self.balance_label.setText(f"Balance owed: ${balance:.2f}")
            self.balance_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #c0392b;")
        elif balance < 0:
            self.balance_label.setText(f"Credit on file: ${-balance:.2f}")
            self.balance_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #1e7e34;")
        else:
            self.balance_label.setText("Balance: $0.00")
            self.balance_label.setStyleSheet("font-size: 14px; font-weight: 600;")

        appts = models.list_appointments_for_client(c["id"])
        self.appt_table.setRowCount(len(appts))
        for row, a in enumerate(appts):
            dt = datetime.fromisoformat(a["start_datetime"])
            self.appt_table.setItem(row, 0, QTableWidgetItem(f"{dt.strftime('%Y-%m-%d')} {format_12h(dt)}"))
            self.appt_table.setItem(row, 1, QTableWidgetItem(STATUS_LABELS.get(a["status"], a["status"])))
            self.appt_table.setItem(row, 2, QTableWidgetItem(a["notes"] or ""))
            self.appt_table.setItem(row, 3, QTableWidgetItem(f"${a['price']:.2f}" if a["price"] is not None else ""))

        payments = models.list_payments_for_client(c["id"])
        self.payment_table.setRowCount(len(payments))
        for row, p in enumerate(payments):
            paid_at = datetime.fromisoformat(p["paid_at"])
            self.payment_table.setItem(row, 0, QTableWidgetItem(paid_at.strftime("%Y-%m-%d %H:%M")))
            self.payment_table.setItem(row, 1, QTableWidgetItem(f"${p['amount']:.2f}"))
            self.payment_table.setItem(row, 2, QTableWidgetItem(p["method"]))
            self.payment_table.setItem(row, 3, QTableWidgetItem(p["notes"] or ""))

    def _add_client(self):
        dlg = ClientDialog(self)
        if dlg.exec():
            self.refresh_list()

    def _edit_client(self):
        if not self.selected_client_id:
            return
        c = models.get_client(self.selected_client_id)
        dlg = ClientDialog(self, client_row=c)
        if dlg.exec():
            self.refresh_list()
            self._refresh_detail()

    def _toggle_archive(self):
        if not self.selected_client_id:
            return
        c = models.get_client(self.selected_client_id)
        new_state = not bool(c["archived"])
        verb = "archive" if new_state else "unarchive"
        if QMessageBox.question(self, "Confirm", f"Are you sure you want to {verb} this client?") == QMessageBox.Yes:
            models.archive_client(self.selected_client_id, archived=new_state)
            self.refresh_list()
            self._refresh_detail()
