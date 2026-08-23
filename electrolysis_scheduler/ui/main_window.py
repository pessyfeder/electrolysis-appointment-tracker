from PySide6.QtWidgets import QMainWindow, QTabWidget, QMenuBar
from PySide6.QtGui import QAction

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
