from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QMessageBox
)

from app import models
from app.util import format_12h, format_client_name, format_phone
from ui.widgets import make_card, style_history_table

STATUS_LABELS = {
    "scheduled": "Scheduled", "in_process": "In Progress", "completed": "Completed",
    "cancelled": "Cancelled", "no_show": "No-Show",
}


class ClientDetailDialog(QDialog):
    """Admin-gated view of a client's balance, full appointment/payment
    history, and archive toggle. Opened from the Billing tab, or from the
    calendar when viewing a past day's bookings. Styled to match the
    Billing tab's cards rather than plain native-Qt chrome, since this
    dialog is itself reached from Billing and shows the same kind of data
    (balances, payment history)."""

    def __init__(self, parent, client_id):
        super().__init__(parent)
        self.client_id = client_id
        c = models.get_client(client_id)
        self.archived = bool(c["archived"])
        display_name = format_client_name(c["first_name"], c["last_name"])
        self.setWindowTitle(display_name)
        self.setMinimumSize(560, 620)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(14)

        header_card, header_layout = make_card(display_name)
        header_layout.addWidget(QLabel(f"Phone: {format_phone(c['phone'])}"))

        self.balance_label = QLabel()
        header_layout.addWidget(self.balance_label)
        self._refresh_balance()

        archive_row = QHBoxLayout()
        self.archive_btn = QPushButton("Unarchive" if self.archived else "Archive")
        self.archive_btn.clicked.connect(self._toggle_archive)
        archive_row.addWidget(self.archive_btn)
        archive_row.addStretch()
        header_layout.addLayout(archive_row)
        outer.addWidget(header_card)

        appt_card, appt_layout = make_card("Appointment History")
        self.appt_table = QTableWidget(0, 4)
        self.appt_table.setHorizontalHeaderLabels(["Date", "Status", "Notes", "Price"])
        style_history_table(self.appt_table, stretch_column=2)
        appt_layout.addWidget(self.appt_table)
        outer.addWidget(appt_card, 1)

        payment_card, payment_layout = make_card("Payment History")
        self.payment_table = QTableWidget(0, 4)
        self.payment_table.setHorizontalHeaderLabels(["Date", "Amount", "Method", "Notes"])
        style_history_table(self.payment_table, stretch_column=3)
        payment_layout.addWidget(self.payment_table)
        outer.addWidget(payment_card, 1)

        self._refresh_history()

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        outer.addLayout(close_row)

    def _refresh_balance(self):
        balance = models.client_balance(self.client_id)
        if balance > 0:
            self.balance_label.setText(f"Balance owed: ${balance:.2f}")
            self.balance_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #b91c1c;")
        elif balance < 0:
            self.balance_label.setText(f"Credit on file: ${-balance:.2f}")
            self.balance_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #15803d;")
        else:
            self.balance_label.setText("Balance: $0.00")
            self.balance_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #64748b;")

    def _refresh_history(self):
        appts = models.list_appointments_for_client(self.client_id)
        self.appt_table.setRowCount(len(appts))
        for row, a in enumerate(appts):
            dt = datetime.fromisoformat(a["start_datetime"])
            self.appt_table.setItem(row, 0, QTableWidgetItem(f"{dt.strftime('%Y-%m-%d')} {format_12h(dt)}"))
            self.appt_table.setItem(row, 1, QTableWidgetItem(STATUS_LABELS.get(a["status"], a["status"])))
            self.appt_table.setItem(row, 2, QTableWidgetItem(a["appointment_notes"] or ""))
            self.appt_table.setItem(row, 3, QTableWidgetItem(f"${a['price']:.2f}" if a["price"] is not None else ""))

        payments = models.list_payments_for_client(self.client_id)
        self.payment_table.setRowCount(len(payments))
        for row, p in enumerate(payments):
            paid_at = datetime.fromisoformat(p["paid_at"])
            self.payment_table.setItem(row, 0, QTableWidgetItem(paid_at.strftime("%Y-%m-%d %H:%M")))
            self.payment_table.setItem(row, 1, QTableWidgetItem(f"${p['amount']:.2f}"))
            self.payment_table.setItem(row, 2, QTableWidgetItem(p["method"]))
            self.payment_table.setItem(row, 3, QTableWidgetItem(p["notes"] or ""))

    def _toggle_archive(self):
        verb = "unarchive" if self.archived else "archive"
        if QMessageBox.question(self, "Confirm", f"Are you sure you want to {verb} this client?") != QMessageBox.Yes:
            return
        self.archived = not self.archived
        models.archive_client(self.client_id, archived=self.archived)
        self.archive_btn.setText("Unarchive" if self.archived else "Archive")
