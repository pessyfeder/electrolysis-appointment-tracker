from PySide6.QtWidgets import QMainWindow, QTabWidget, QMenuBar
from PySide6.QtGui import QAction
from PySide6.QtCore import QTimer

from ui.calendar_view import CalendarView
from ui.billing_view import BillingView
from ui.login_dialog import prompt_admin_reauth


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Electrolysis Scheduler")
        self.resize(1200, 800)

        self.tabs = QTabWidget()
        self.calendar_view = CalendarView(self, require_admin=self.require_admin)
        self.billing_view = BillingView(self, require_admin=self.require_admin)

        self.tabs.addTab(self.calendar_view, "Appointments")
        self.tabs.addTab(self.billing_view, "Billing")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.setCentralWidget(self.tabs)

        admin_menu = self.menuBar().addMenu("Admin")
        hours_action = QAction("Edit Business Hours…", self)
        hours_action.triggered.connect(self._edit_business_hours)
        admin_menu.addAction(hours_action)

        self._did_initial_refresh = False

    def showEvent(self, event):
        super().showEvent(event)
        # The calendar's month/week grids are hand-painted using their own
        # width/height at paint time, but they're first populated with data
        # while still off-screen (during __init__, before this window has
        # been laid out to its real on-screen size). That leaves the very
        # first frame looking wrong/"raw" until something - previously,
        # only a click - forced a fresh repaint at the correct size.
        # Trigger one more refresh right after the window actually becomes
        # visible (deferred to the next event-loop tick so layout has
        # settled) instead of waiting on the user to stumble into a click.
        if not self._did_initial_refresh:
            self._did_initial_refresh = True
            QTimer.singleShot(0, self.calendar_view.refresh)

    def require_admin(self) -> bool:
        return prompt_admin_reauth(self)

    def _edit_business_hours(self):
        if not self.require_admin():
            return
        from ui.business_hours_dialog import BusinessHoursDialog
        dlg = BusinessHoursDialog(self)
        if dlg.exec():
            self.calendar_view.refresh()

    def _on_tab_changed(self, index):
        widget = self.tabs.widget(index)
        if widget is self.calendar_view:
            self.calendar_view.refresh()
        elif widget is self.billing_view:
            self.billing_view.refresh()
