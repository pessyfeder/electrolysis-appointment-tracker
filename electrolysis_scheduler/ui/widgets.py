from PySide6.QtWidgets import QDateEdit, QAbstractSpinBox, QCalendarWidget, QDoubleSpinBox
from PySide6.QtCore import Qt, QEvent, QPoint, QDate, QObject, QTimer
from PySide6.QtGui import QTextCharFormat, QColor

_DISABLED_DATE_FORMAT = QTextCharFormat()
_DISABLED_DATE_FORMAT.setForeground(QColor("#cbd5e1"))
_ENABLED_DATE_FORMAT = QTextCharFormat()


class _ShowPopupOnClick(QObject):
    """Installed on an editable QComboBox's internal line edit so a plain
    click into the field opens the full item list immediately, instead of
    only the small dropdown arrow doing that - otherwise the option list
    stays hidden from anyone who doesn't already know a name to type."""

    def __init__(self, combo):
        super().__init__(combo)
        self._combo = combo

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and not self._combo.view().isVisible():
            # Calling showPopup() synchronously from inside this same
            # click's mousePressEvent opens the popup, but then that same
            # click's mouseReleaseEvent (landing on the line edit, not
            # inside the freshly-opened popup) is read as an "outside"
            # click and immediately closes it again - the popup flashes
            # and disappears instead of staying open. Deferring the call
            # to the next event-loop tick lets this click finish being
            # processed first, so the popup opens cleanly afterward and
            # stays open.
            QTimer.singleShot(0, self._show_popup_safely)
        return False

    def _show_popup_safely(self):
        if not self._combo.view().isVisible():
            self._combo.showPopup()


def open_dropdown_on_click(combo):
    """Call after making a QComboBox editable - see _ShowPopupOnClick."""
    combo.lineEdit().installEventFilter(_ShowPopupOnClick(combo))


class TypeOnlyDoubleSpinBox(QDoubleSpinBox):
    """A QDoubleSpinBox with the increment/decrement arrows hidden and the
    mouse scroll wheel disabled, so typing is the only way to change its
    value - e.g. a payment amount, where a stray scroll or an arrow click
    silently bumping the number is worse than either control being useful."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setButtonSymbols(QAbstractSpinBox.NoButtons)

    def wheelEvent(self, event):
        event.ignore()


class ClickToOpenDateEdit(QDateEdit):
    """A date field that can only be set via a calendar popup - never by
    typing, dragging, or selecting text. Clicking anywhere on the field
    (not just a small button) opens the popup. No spin/calendar button is
    drawn - the whole field is the click target, and it shows a pointing
    hand rather than a text-entry caret so it visibly reads as click-only.

    QAbstractSpinBox (which QDateEdit descends from) creates its own child
    QLineEdit that visually covers the text area, so a plain override of
    this widget's own mousePressEvent only ever fires for clicks that land
    outside that child - i.e. on the spin/calendar button, never the text
    itself. Qt's built-in calendarPopup mechanism is bypassed entirely for
    the same reason it can't be triggered reliably from here; instead this
    installs an event filter on that internal line edit and shows a
    hand-rolled QCalendarWidget popup.

    An optional per-date availability check (see set_availability_check)
    grays out and disables selection of individual dates within the
    min/max range too - e.g. closed weekdays or fully blocked-off days -
    on top of the plain min/max-date range."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setCalendarPopup(False)
        self.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self._popup = None
        self._is_available = None

        edit = self.lineEdit()
        edit.installEventFilter(self)
        edit.setReadOnly(True)
        # Focus (and the blinking text caret that comes with it) stays on
        # this outer widget instead of the inner line edit, so nothing ever
        # looks like an active text-entry cursor - only StrongFocus (not
        # ClickFocus) so Tab still lands here, since the line edit that
        # normally handles that no longer can.
        edit.setFocusPolicy(Qt.NoFocus)
        self.setFocusPolicy(Qt.StrongFocus)
        edit.setCursor(Qt.PointingHandCursor)
        self.setCursor(Qt.PointingHandCursor)

    def set_availability_check(self, fn):
        """fn(QDate) -> bool, called for every date shown in the popup to
        decide whether it's grayed out and unselectable, in addition to the
        plain minimumDate()/maximumDate() range - e.g. days with no
        business hours at all, or fully blocked off. Pass None to disable."""
        self._is_available = fn

    def eventFilter(self, obj, event):
        if obj is self.lineEdit():
            et = event.type()
            if et in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
                if self.isEnabled():
                    self._show_popup()
                return True
            if et == QEvent.Wheel:
                return True
            if et == QEvent.KeyPress and event.key() not in (Qt.Key_Tab, Qt.Key_Backtab):
                return True
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        # Covers clicks that land outside the internal line edit's rect
        # (there's little such area now that the button is hidden, but
        # keep this as a fallback so the field is never dead space).
        if self.isEnabled():
            self._show_popup()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            super().keyPressEvent(event)
        else:
            event.ignore()

    def wheelEvent(self, event):
        event.ignore()

    def _show_popup(self):
        cal = QCalendarWidget()
        cal.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        cal.setAttribute(Qt.WA_DeleteOnClose, True)
        cal.setGridVisible(True)
        cal.setMinimumDate(self.minimumDate())
        cal.setMaximumDate(self.maximumDate())
        cal.setSelectedDate(self.date())
        cal.clicked.connect(lambda d: self._pick(d, cal))
        cal.activated.connect(lambda d: self._pick(d, cal))
        cal.currentPageChanged.connect(lambda y, m: self._apply_day_formatting(cal, y, m))
        self._apply_day_formatting(cal, cal.yearShown(), cal.monthShown())
        cal.resize(300, 240)
        cal.move(self.mapToGlobal(QPoint(0, self.height())))
        cal.show()
        self._popup = cal

    def _is_selectable(self, d, cal):
        if not (cal.minimumDate() <= d <= cal.maximumDate()):
            return False
        if self._is_available is not None and not self._is_available(d):
            return False
        return True

    def _apply_day_formatting(self, cal, year, month):
        # QCalendarWidget already refuses to select dates outside
        # minimumDate()/maximumDate(), but doesn't dim any date on its own
        # (in or out of range) - without this, a blocked or closed day
        # looks identical to a bookable one.
        first = QDate(year, month, 1)
        for day in range(1, first.daysInMonth() + 1):
            d = QDate(year, month, day)
            fmt = _ENABLED_DATE_FORMAT if self._is_selectable(d, cal) else _DISABLED_DATE_FORMAT
            cal.setDateTextFormat(d, fmt)

    def _pick(self, picked_date, cal):
        if not self._is_selectable(picked_date, cal):
            return
        self.setDate(picked_date)
        cal.close()
