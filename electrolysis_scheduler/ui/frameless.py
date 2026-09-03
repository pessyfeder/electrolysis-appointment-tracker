"""Shared pieces for giving a top-level window (QMainWindow or QDialog) a
custom title bar instead of the native OS one - drag, minimize/maximize/
close (or just close, for a small dialog), and edge/corner resize, all
still driven by the OS's own move/resize implementation via
QWindow.startSystemMove()/startSystemResize() so Aero Snap, proper resize
cursors, and multi-monitor DPI keep working exactly as they do for a normal
window - only the visible chrome is replaced."""

from PySide6.QtCore import Qt, QEvent
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton

RESIZE_MARGIN = 6

_BTN_STYLE = (
    "QPushButton { background: transparent; border: none; color: #ffffff; font-size: 13px; }"
    "QPushButton:hover { background: rgba(255, 255, 255, 0.15); }"
    "QPushButton:pressed { background: rgba(255, 255, 255, 0.25); }"
)
_CLOSE_BTN_STYLE = (
    "QPushButton { background: transparent; border: none; color: #ffffff; font-size: 13px; }"
    "QPushButton:hover { background: #e81123; }"
    "QPushButton:pressed { background: #c50f1f; }"
)


class FramelessTitleBar(QWidget):
    """Draggable replacement for the native title bar. `window` is the
    top-level widget this bar controls (its .windowHandle() is what
    actually gets asked to move). Minimize/maximize buttons are optional -
    a small popup dialog only needs a close button."""

    def __init__(self, window, title="", show_minimize=False, show_maximize=False, parent=None):
        super().__init__(parent)
        self._window = window
        self.setObjectName("framelessTitleBar")
        self.setFixedHeight(38)
        # A plain QWidget (unlike QFrame) doesn't paint a stylesheet
        # background on its own - without this attribute the dark bar
        # underneath the title/buttons never actually renders, leaving
        # just the app's ambient pale background showing through and the
        # white button glyphs invisible against it.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("#framelessTitleBar { background: #1e293b; }")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 0, 0)
        layout.setSpacing(0)

        self._title_label = QLabel(title)
        self._title_label.setStyleSheet("color: #f1f5f9; font-weight: 600; font-size: 11pt; background: transparent;")
        layout.addWidget(self._title_label)
        layout.addStretch()

        self._max_btn = None
        if show_minimize:
            min_btn = QPushButton("─")
            min_btn.setFixedSize(44, 38)
            min_btn.setStyleSheet(_BTN_STYLE)
            min_btn.setCursor(Qt.ArrowCursor)
            min_btn.clicked.connect(window.showMinimized)
            layout.addWidget(min_btn)

        if show_maximize:
            self._max_btn = QPushButton("▢")
            self._max_btn.setFixedSize(44, 38)
            self._max_btn.setStyleSheet(_BTN_STYLE)
            self._max_btn.setCursor(Qt.ArrowCursor)
            self._max_btn.clicked.connect(self._toggle_maximize)
            layout.addWidget(self._max_btn)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(44, 38)
        close_btn.setStyleSheet(_CLOSE_BTN_STYLE)
        close_btn.setCursor(Qt.ArrowCursor)
        close_btn.clicked.connect(window.close)
        layout.addWidget(close_btn)

    def setTitle(self, text):
        self._title_label.setText(text)

    def _toggle_maximize(self):
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self._max_btn is not None and event.button() == Qt.LeftButton:
            self._toggle_maximize()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class _ResizeGrip(QWidget):
    def __init__(self, window, edge, cursor):
        super().__init__(window)
        self._window = window
        self._edge = edge
        self.setCursor(cursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemResize(self._edge)
                event.accept()


class ResizeGrips:
    """Adds the 8 invisible edge/corner strips a frameless QMainWindow needs
    for the OS to let the user resize it by dragging - purely visual chrome
    was removed, but the resize AFFORDANCE has to be rebuilt by hand since
    it normally comes from the native frame. Call `layout()` from the
    window's resizeEvent and `set_active(bool)` when its maximized state
    changes (a maximized window can't be resized, so the grips should stop
    intercepting clicks then)."""

    def __init__(self, window):
        self.window = window
        m = RESIZE_MARGIN
        self.top = _ResizeGrip(window, Qt.TopEdge, Qt.SizeVerCursor)
        self.bottom = _ResizeGrip(window, Qt.BottomEdge, Qt.SizeVerCursor)
        self.left = _ResizeGrip(window, Qt.LeftEdge, Qt.SizeHorCursor)
        self.right = _ResizeGrip(window, Qt.RightEdge, Qt.SizeHorCursor)
        self.top_left = _ResizeGrip(window, Qt.TopEdge | Qt.LeftEdge, Qt.SizeFDiagCursor)
        self.top_right = _ResizeGrip(window, Qt.TopEdge | Qt.RightEdge, Qt.SizeBDiagCursor)
        self.bottom_left = _ResizeGrip(window, Qt.BottomEdge | Qt.LeftEdge, Qt.SizeBDiagCursor)
        self.bottom_right = _ResizeGrip(window, Qt.BottomEdge | Qt.RightEdge, Qt.SizeFDiagCursor)
        self._all = [
            self.top, self.bottom, self.left, self.right,
            self.top_left, self.top_right, self.bottom_left, self.bottom_right,
        ]

    def layout(self):
        w, h = self.window.width(), self.window.height()
        m = RESIZE_MARGIN
        self.top.setGeometry(m, 0, max(0, w - 2 * m), m)
        self.bottom.setGeometry(m, h - m, max(0, w - 2 * m), m)
        self.left.setGeometry(0, m, m, max(0, h - 2 * m))
        self.right.setGeometry(w - m, m, m, max(0, h - 2 * m))
        self.top_left.setGeometry(0, 0, m, m)
        self.top_right.setGeometry(w - m, 0, m, m)
        self.bottom_left.setGeometry(0, h - m, m, m)
        self.bottom_right.setGeometry(w - m, h - m, m, m)
        for g in self._all:
            g.raise_()

    def set_active(self, active):
        for g in self._all:
            g.setVisible(active)
