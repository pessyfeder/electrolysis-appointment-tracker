from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QPushButton,
    QHBoxLayout, QMessageBox
)

from app import models
from app.util import format_phone, is_valid_phone
from ui.widgets import required_label, required_hint_label


class ClientDialog(QDialog):
    """Add or edit a client's basic info. Pops up during booking (quick-add
    for a new client, or a light edit of an existing one). Only last name and
    phone are required - first name is optional. Balance, full appointment/
    payment history, and archive live in the admin-gated client detail view
    under the Billing tab."""

    def __init__(self, parent=None, client_row=None):
        super().__init__(parent)
        self.client_row = client_row
        self.client_id = client_row["id"] if client_row else None
        self.setWindowTitle("Edit Client" if client_row else "Add Client")
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.first_name = QLineEdit(client_row["first_name"] if client_row else "")
        self.last_name = QLineEdit(client_row["last_name"] if client_row else "")
        self.phone = QLineEdit(format_phone(client_row["phone"]) if client_row else "")
        self.phone.setPlaceholderText("(555) 123-4567")
        self.phone.editingFinished.connect(self._format_phone_field)
        form.addRow(required_label("Last name:"), self.last_name)
        form.addRow("First name (optional):", self.first_name)
        form.addRow(required_label("Phone:"), self.phone)
        layout.addLayout(form)

        layout.addWidget(required_hint_label())

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _format_phone_field(self):
        formatted = format_phone(self.phone.text())
        if formatted:
            self.phone.setText(formatted)

    def _save(self):
        first = self.first_name.text().strip()
        last = self.last_name.text().strip()
        phone = self.phone.text().strip()
        if not last:
            QMessageBox.warning(self, "Missing Info", "Last name is required.")
            return
        if not phone or not is_valid_phone(phone):
            QMessageBox.warning(self, "Invalid Phone", "Enter a valid 10-digit phone number.")
            return
        phone = format_phone(phone)
        if self.client_id:
            models.update_client(self.client_id, first, last, phone, "")
        else:
            self.client_id = models.create_client(first, last, phone, "")
        self.accept()
