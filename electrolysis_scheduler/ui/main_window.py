from PySide6.QtWidgets import QMainWindow, QTabWidget, QWidget, QVBoxLayout
from PySide6.QtCore import QTimer, QEvent, Qt

from ui.calendar_view import CalendarView
from ui.billing_view import BillingView
from ui.admin_view import AdminView
from ui.login_dialog import prompt_admin_reauth
from ui.frameless import FramelessTitleBar, ResizeGrips


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Electrolysis Scheduler")
        self.resize(1200, 800)
        self.setMinimumSize(900, 600)

        # Frameless: the native title bar/border is replaced below with a
        # custom one, so this window looks and behaves consistently instead
        # of picking up whatever accent color the OS window chrome happens
        # to be themed with.
        self.setWindowFlag(Qt.FramelessWindowHint)

        central = QWidget()
        central.setObjectName("appFrame")
        central.setAttribute(Qt.WA_StyledBackground, True)
        central.setStyleSheet("#appFrame { border: 1px solid #334155; }")
        outer = QVBoxLayout(central)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        self.title_bar = FramelessTitleBar(
            self, "Electrolysis Scheduler", show_minimize=True, show_maximize=True
        )
        outer.addWidget(self.title_bar)

        self.tabs = QTabWidget()
        self.calendar_view = CalendarView(self, require_admin=self.require_admin)
        self.billing_view = BillingView(self, require_admin=self.require_admin)
        self.admin_view = AdminView(
            self, billing_view=self.billing_view, on_calendar_changed=self.calendar_view.refresh,
        )

        self.tabs.addTab(self.calendar_view, "Appointments")
        self.tabs.addTab(self.admin_view, "Admin")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        outer.addWidget(self.tabs)

        # Catches a mouse click on the Admin tab before QTabBar acts on it,
        # so the password prompt appears - and the switch either happens or
        # doesn't - before any visual change, instead of the tab flashing
        # to Admin and then snapping back on a failed/cancelled password.
        self._admin_authenticated_click = False
        self.tabs.tabBar().installEventFilter(self)

        self.setCentralWidget(central)

        self._resize_grips = ResizeGrips(self)
        self._resize_grips.set_active(not self.isMaximized())

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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_grips.layout()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            # A maximized window has no edges to drag from, and the resize
            # grips sit right where Windows already treats the top edge as
            # "restore" territory - keep them enabled only while normal.
            self._resize_grips.set_active(not self.isMaximized())

    def require_admin(self) -> bool:
        return prompt_admin_reauth(self)

    def eventFilter(self, obj, event):
        if obj is self.tabs.tabBar() and event.type() == QEvent.MouseButtonPress:
            index = obj.tabAt(event.pos())
            admin_index = self.tabs.indexOf(self.admin_view)
            if index == admin_index and self.tabs.currentWidget() is not self.admin_view:
                if not self.require_admin():
                    return True  # swallow the click - the tab bar never switches at all
                # Password already verified for this click; let the event
                # continue on to QTabBar's normal handling so it performs
                # the actual switch, and tell _on_tab_changed not to ask
                # again right after.
                self._admin_authenticated_click = True
        return super().eventFilter(obj, event)

    def _on_tab_changed(self, index):
        widget = self.tabs.widget(index)
        if widget is self.admin_view:
            if not self._admin_authenticated_click:
                # Reached via something other than a plain tab-bar click
                # (e.g. keyboard navigation) - the event filter above never
                # ran, so fall back to gating here. This path still flashes
                # to Admin before reverting on failure, but that's a rare
                # enough entry point that the tradeoff is acceptable.
                if not self.require_admin():
                    self.tabs.blockSignals(True)
                    self.tabs.setCurrentWidget(self.calendar_view)
                    self.tabs.blockSignals(False)
                    return
            self._admin_authenticated_click = False
            self.admin_view.refresh()
        elif widget is self.calendar_view:
            self.calendar_view.refresh()
