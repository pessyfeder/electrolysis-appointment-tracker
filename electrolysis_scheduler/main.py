import sys

from PySide6.QtWidgets import QApplication

from app.db import init_db
from ui.login_dialog import LoginDialog
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Electrolysis Scheduler")

    init_db()

    login = LoginDialog()
    if login.exec() != LoginDialog.Accepted:
        sys.exit(0)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
