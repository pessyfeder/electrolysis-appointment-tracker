from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QTextEdit, QPushButton,
    QHBoxLayout, QMessageBox
)

from app import models


class ClientDialog(QDialog):
    """Add or edit a client. Pops up during booking for quick-add (spec 8.2)."""

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
        self.phone = QLineEdit(client_row["phone"] if client_row else "")
        self.notes = QTextEdit(client_row["notes"] if client_row and client_row["notes"] else "")
        self.notes.setFixedHeight(80)
        form.addRow("First name:", self.first_name)
        form.addRow("Last name:", self.last_name)
        form.addRow("Phone:", self.phone)
        form.addRow("Notes:", self.notes)
        layout.addLayout(form)

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

    def _save(self):
        first = self.first_name.text().strip()
        last = self.last_name.text().strip()
        phone = self.phone.text().strip()
        if not first or not last or not phone:
            QMessageBox.warning(self, "Missing Info", "First name, last name, and phone are required.")
            return
        notes = self.notes.toPlainText()
        if self.client_id:
            models.update_client(self.client_id, first, last, phone, notes)
        else:
            self.client_id = models.create_client(first, last, phone, notes)
        self.accept()
