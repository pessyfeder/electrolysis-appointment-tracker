import os
import sys
import traceback

# The embeddable Python interpreter this app ships with uses a python3xx._pth
# file that fully overrides sys.path, so it never auto-adds the script's own
# directory the way a normal Python install would. Add it explicitly so the
# sibling app/ and ui/ packages are always importable regardless of how (or
# from where) main.py is launched.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from app.db import init_db
from app.paths import app_data_dir
from ui.login_dialog import LoginDialog
from ui.main_window import MainWindow
from ui.theme import apply_theme


def _install_excepthook():
    """The packaged build runs windowed (no console), so an unhandled
    exception raised inside a Qt slot - e.g. a button click handler - would
    otherwise vanish silently: nothing gets recorded, no dialog appears, and
    the app just sits there as if the click did nothing. Route it to a log
    file and a visible dialog instead of losing it."""
    log_path = os.path.join(app_data_dir(), "error.log")

    def hook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except OSError:
            pass
        try:
            QMessageBox.critical(
                None, "Unexpected Error",
                f"Something went wrong and the last action may not have completed:\n\n"
                f"{exc_type.__name__}: {exc_value}\n\n"
                f"Details were saved to:\n{log_path}",
            )
        except Exception:
            pass

    sys.excepthook = hook


def main():
    _install_excepthook()
    app = QApplication(sys.argv)
    app.setApplicationName("Electrolysis Scheduler")
    apply_theme(app)

    init_db()

    login = LoginDialog()
    if login.exec() != LoginDialog.Accepted:
        sys.exit(0)

    window = MainWindow()
    # A normal, centered window rather than showMaximized() - it fits the
    # calendar grid to whatever size that ends up being either way (see
    # TimeGridWidget._relayout()), so there's no reason to force the app to
    # cover the whole screen on launch.
    #
    # Centering is deferred to right after show() rather than computed from
    # window.width() beforehand: MainWindow's actual minimum width is
    # derived from its toolbar's real layout (see MainWindow.__init__), not
    # a hardcoded number, and that isn't settled until the window has
    # actually been laid out - reading window.width() any earlier risks
    # centering against a stale, too-small size.
    def _center_on_screen():
        screen_geo = app.primaryScreen().availableGeometry()
        window.move(
            screen_geo.x() + max(0, (screen_geo.width() - window.width()) // 2),
            screen_geo.y() + max(0, (screen_geo.height() - window.height()) // 2),
        )

    window.show()
    QTimer.singleShot(0, _center_on_screen)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
