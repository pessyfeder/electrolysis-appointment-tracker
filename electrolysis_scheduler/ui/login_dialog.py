from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox, QFormLayout
)
from PySide6.QtCore import Qt

from app import auth


class LoginDialog(QDialog):
    """Gates opening the app at all (spec 7.4). Handles first-run setup too."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Electrolysis Scheduler — Sign In")
        self.setModal(True)
        self.setMinimumWidth(360)
        self._first_run = not auth.has_password_set()

        layout = QVBoxLayout(self)
        title = QLabel("Set an Admin Password" if self._first_run else "Enter Admin Password")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(title)

        if self._first_run:
            sub = QLabel("This password will be required every time the app opens.")
            sub.setWordWrap(True)
            layout.addWidget(sub)

        form = QFormLayout()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        form.addRow("Password:", self.password_edit)

        if self._first_run:
            self.confirm_edit = QLineEdit()
            self.confirm_edit.setEchoMode(QLineEdit.Password)
            form.addRow("Confirm:", self.confirm_edit)
        layout.addLayout(form)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #c0392b;")
        layout.addWidget(self.error_label)

        submit = QPushButton("Set Password" if self._first_run else "Unlock")
        submit.setDefault(True)
        submit.clicked.connect(self._on_submit)
        layout.addWidget(submit)

        self.password_edit.returnPressed.connect(self._on_submit)

    def _on_submit(self):
        pw = self.password_edit.text()
        if self._first_run:
            confirm = self.confirm_edit.text()
            if len(pw) < 4:
                self.error_label.setText("Password must be at least 4 characters.")
                return
            if pw != confirm:
                self.error_label.setText("Passwords do not match.")
                return
            auth.set_password(pw)
            self.accept()
        else:
            if auth.verify_password(pw):
                self.accept()
            else:
                self.error_label.setText("Incorrect password.")
                self.password_edit.clear()
                self.password_edit.setFocus()


def prompt_admin_reauth(parent) -> bool:
    """Used for the second password gate when editing time availability (spec 7.4)."""
    from PySide6.QtWidgets import QInputDialog
    pw, ok = QInputDialog.getText(
        parent, "Enter Admin Password",
        "Enter Admin Password:",
        QLineEdit.Password,
    )
    if not ok:
        return False
    if auth.verify_password(pw):
        return True
    QMessageBox.warning(parent, "Incorrect Password", "That password is incorrect.")
    return False
