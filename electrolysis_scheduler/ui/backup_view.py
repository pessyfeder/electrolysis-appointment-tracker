import sqlite3
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QFileDialog, QMessageBox,
    QApplication
)

from app.backup import backup_database, restore_database
from ui.widgets import make_card, ADMIN_FORM_COLUMN_WIDTH


class BackupView(QWidget):
    """Admin tab page: copy the live database out to a file, or replace it
    with a previously-saved one. Reaching the Admin tab at all already
    required the password (see MainWindow._on_tab_changed), same as Edit
    Business Hours / Block Time Off - but Restore overwrites every client,
    appointment, and payment with no undo, so unlike those two it re-checks
    require_admin immediately before acting, matching the app's pattern for
    other points-of-no-return (Start/End Session, cancel, archive)."""

    def __init__(self, parent=None, require_admin=None):
        super().__init__(parent)
        self.require_admin = require_admin or (lambda: True)

        outer = QVBoxLayout(self)
        content = QWidget()
        content.setMaximumWidth(ADMIN_FORM_COLUMN_WIDTH)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(14)

        backup_card, backup_layout = make_card("Backup Database")
        backup_hint = QLabel(
            "Save a copy of all appointments, clients, and payments to a "
            "file - a USB drive or another folder are both fine. Keep this "
            "somewhere separate from this computer in case of disk failure."
        )
        backup_hint.setWordWrap(True)
        backup_hint.setStyleSheet("color: #64748b;")
        backup_layout.addWidget(backup_hint)
        backup_btn = QPushButton("Backup Database…")
        backup_btn.setObjectName("primaryButton")
        backup_btn.clicked.connect(self._backup)
        backup_layout.addWidget(backup_btn)
        content_layout.addWidget(backup_card)

        restore_card, restore_layout = make_card("Restore Database")
        restore_hint = QLabel(
            "Replace ALL current appointments, clients, and payments with "
            "the contents of a backup file. This cannot be undone - anything "
            "recorded since that backup was made will be lost. The app will "
            "close afterward; reopen it to see the restored data."
        )
        restore_hint.setWordWrap(True)
        restore_hint.setStyleSheet("color: #64748b;")
        restore_layout.addWidget(restore_hint)
        restore_btn = QPushButton("Restore Database…")
        restore_btn.clicked.connect(self._restore)
        restore_layout.addWidget(restore_btn)
        content_layout.addWidget(restore_card)

        content_layout.addStretch()
        outer.addWidget(content)
        outer.addStretch()

    def _default_backup_name(self):
        return f"scheduler_backup_{datetime.now().strftime('%Y-%m-%d_%H%M')}.db"

    def _backup(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Backup Database", self._default_backup_name(), "SQLite Database (*.db)"
        )
        if not path:
            return
        try:
            backup_database(path)
        except OSError as exc:
            QMessageBox.critical(self, "Backup Failed", f"Could not write the backup file:\n{exc}")
            return
        QMessageBox.information(self, "Backup Complete", f"Saved to:\n{path}")

    def _restore(self):
        if not self.require_admin():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Restore Database", "", "SQLite Database (*.db);;All Files (*)"
        )
        if not path:
            return
        confirm = QMessageBox.warning(
            self, "Confirm Restore",
            "This will permanently replace all current appointments, clients, "
            "and payments with the contents of:\n\n"
            f"{path}\n\n"
            "Anything recorded since that backup was made will be lost, and "
            "the app will close so it can reopen with the restored data.\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            restore_database(path)
        except (OSError, sqlite3.DatabaseError) as exc:
            QMessageBox.critical(
                self, "Restore Failed",
                f"The current database was not changed.\n\n{exc}",
            )
            return
        QMessageBox.information(
            self, "Restore Complete",
            "The database was restored. The app will now close - reopen it "
            "to see the restored data.",
        )
        QApplication.instance().quit()
