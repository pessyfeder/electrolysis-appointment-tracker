"""Shared pieces for giving a top-level window (QMainWindow or QDialog) a
custom title bar instead of the native OS one - drag, minimize/maximize/
close (or just close, for a small dialog), and edge/corner resize, all
still driven by the OS's own move/resize implementation via
QWindow.startSystemMove()/startSystemResize() so Aero Snap, proper resize
cursors, and multi-monitor DPI keep working exactly as they do for a normal
window - only the visible chrome is replaced."""

from PySide6.QtCore import Qt, QEvent, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton

RESIZE_MARGIN = 6
_BAR_BG = "#ffffff"

_BTN_STYLE = (
    "QPushButton { background: transparent; border: none; border-radius: 4px; }"
    "QPushButton:hover { background: rgba(15, 23, 42, 0.06); }"
    "QPushButton:pressed { background: rgba(15, 23, 42, 0.1); }"
)
_CLOSE_BTN_STYLE = (
    "QPushButton { background: transparent; border: none; border-radius: 4px; }"
    "QPushButton:hover { background: #e81123; }"
    "QPushButton:pressed { background: #c50f1f; }"
)


def make_app_icon(size=18):
    """Title-bar icon: the same 📅 calendar glyph used on the toolbar's
    "Schedule Appointment" button (see calendar_view.py), painted onto a
    small transparent pixmap instead of shipped as an image file - there's
    then nothing new to add to the PyInstaller spec's `datas` for it to
    survive the packaged build. No explicit font family is set so Qt falls
    back to the system's color-emoji font for this character instead of
    trying (and failing) to find it in a plain UI font like Segoe UI."""
    ratio = 2
    pm = QPixmap(size * ratio, size * ratio)
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    font = QFont()
    font.setPixelSize(round(size * 0.85))
    painter.setFont(font)
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, "📅")
    painter.end()
    return pm


class _CaptionButton(QPushButton):
    """A minimize/maximize/close button with its glyph drawn in code as a
    thin outline rather than set as Unicode text (─ ▢ ✕) - the Unicode
    glyphs render at inconsistent weights across fonts/sizes and read as
    clunky next to the rest of this flat, minimal bar. `kind` is one of
    "minimize", "maximize", "close"; the maximize button's glyph swaps to
    an overlapping-squares "restore" icon via set_maximized(), matching
    the thin-line caption buttons apps like Claude Desktop use."""

    def __init__(self, kind, style, parent=None):
        super().__init__(parent)
        self._kind = kind
        self._maximized = False
        self.setStyleSheet(style)

    def set_maximized(self, maximized):
        if maximized != self._maximized:
            self._maximized = maximized
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        color = QColor("#ffffff") if (self._kind == "close" and self.underMouse()) else QColor("#334155")
        pen = QPen(color)
        pen.setWidthF(1.3)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        cx, cy = self.width() / 2, self.height() / 2

        if self._kind == "minimize":
            painter.drawLine(QPointF(cx - 5, cy), QPointF(cx + 5, cy))
        elif self._kind == "maximize" and not self._maximized:
            painter.drawRect(QRectF(cx - 5, cy - 5, 10, 10))
        elif self._kind == "maximize" and self._maximized:
            # Overlapping-squares restore icon: the front (bottom-left)
            # square is filled with the bar's own background color so it
            # masks the corner of the back square behind it, instead of
            # the two outlines just crossing over each other.
            back = QRectF(cx - 2.5, cy - 5.5, 8, 8)
            front = QRectF(cx - 5.5, cy - 2.5, 8, 8)
            painter.drawRect(back)
            painter.setBrush(QColor(_BAR_BG))
            painter.drawRect(front)
        elif self._kind == "close":
            painter.drawLine(QPointF(cx - 5, cy - 5), QPointF(cx + 5, cy + 5))
            painter.drawLine(QPointF(cx - 5, cy + 5), QPointF(cx + 5, cy - 5))

        painter.end()


class FramelessTitleBar(QWidget):
    """Draggable replacement for the native title bar. `window` is the
    top-level widget this bar controls (its .windowHandle() is what
    actually gets asked to move). Minimize/maximize buttons are optional -
    a small popup dialog only needs a close button."""

    def __init__(self, window, title="", show_minimize=False, show_maximize=False, icon=None, height=32, parent=None):
        super().__init__(parent)
        self._window = window
        self.setObjectName("framelessTitleBar")
        self.setFixedHeight(height)
        # A plain QWidget (unlike QFrame) doesn't paint a stylesheet
        # background on its own - without this attribute the white bar
        # underneath the buttons never actually renders, leaving just the
        # app's ambient background showing through.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            "#framelessTitleBar {"
            f" background: {_BAR_BG};"
            " border-bottom: 1px solid #e5e7eb;"
            " }"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 6, 0)
        layout.setSpacing(2)

        # Icon/title are opt-in (a small popup dialog passes neither, for
        # a plain draggable strip like Claude Desktop's) - only shown when
        # actually provided.
        if icon is not None:
            icon_label = QLabel()
            icon_label.setPixmap(icon)
            icon_label.setFixedSize(icon.size())
            layout.addWidget(icon_label, 0, Qt.AlignVCenter)
            layout.addSpacing(3)

        self._title_label = QLabel(title)
        self._title_label.setStyleSheet("color: #1e293b; font-weight: 600; font-size: 10pt; background: transparent;")
        self._title_label.setVisible(bool(title))
        layout.addWidget(self._title_label, 0, Qt.AlignVCenter)
        layout.addStretch()

        # Buttons are shorter than the bar itself (with vertical margin on
        # either side) so their hover/pressed rounded-rect highlight reads
        # as a soft pill instead of a hard-edged block spanning the full
        # bar height - the flat edge-to-edge rectangles were what made the
        # old bar feel clunky.
        btn_h = height - 6

        self._max_btn = None
        if show_minimize:
            min_btn = _CaptionButton("minimize", _BTN_STYLE)
            min_btn.setFixedSize(36, btn_h)
            min_btn.setCursor(Qt.ArrowCursor)
            min_btn.clicked.connect(window.showMinimized)
            layout.addWidget(min_btn, 0, Qt.AlignVCenter)

        if show_maximize:
            self._max_btn = _CaptionButton("maximize", _BTN_STYLE)
            self._max_btn.setFixedSize(36, btn_h)
            self._max_btn.setCursor(Qt.ArrowCursor)
            self._max_btn.clicked.connect(self._toggle_maximize)
            layout.addWidget(self._max_btn, 0, Qt.AlignVCenter)

        close_btn = _CaptionButton("close", _CLOSE_BTN_STYLE)
        close_btn.setFixedSize(36, btn_h)
        close_btn.setCursor(Qt.ArrowCursor)
        close_btn.clicked.connect(window.close)
        layout.addWidget(close_btn, 0, Qt.AlignVCenter)

    def setTitle(self, text):
        self._title_label.setText(text)
        self._title_label.setVisible(bool(text))

    def sync_maximized(self):
        """Re-reads the window's actual maximized state into the restore/
        maximize glyph - needed because toggling can also happen outside
        the button itself (Aero Snap, Win+Up, double-clicking the bar)."""
        if self._max_btn is not None:
            self._max_btn.set_maximized(self._window.isMaximized())

    def _toggle_maximize(self):
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()
        self.sync_maximized()

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
