from PySide6.QtWidgets import (
    QDateEdit, QAbstractSpinBox, QCalendarWidget, QDoubleSpinBox, QLabel,
    QFrame, QVBoxLayout, QTableWidget, QHeaderView
)
from PySide6.QtCore import Qt, QEvent, QPoint, QDate, QObject
from PySide6.QtGui import QTextCharFormat, QColor

_DISABLED_DATE_FORMAT = QTextCharFormat()
_DISABLED_DATE_FORMAT.setForeground(QColor("#cbd5e1"))
_ENABLED_DATE_FORMAT = QTextCharFormat()

REQUIRED_COLOR = "#dc2626"


def required_label(text):
    """A QFormLayout row label like 'Date: *' with the asterisk in red,
    so a required field reads as required at a glance rather than blending
    into the rest of the label."""
    lbl = QLabel(f'{text} <span style="color:{REQUIRED_COLOR};">*</span>')
    lbl.setTextFormat(Qt.RichText)
    return lbl


def required_hint_label():
    """The '* Required' legend shown near a form's required fields, in the
    same red as required_label()'s asterisks."""
    lbl = QLabel("* Required")
    lbl.setStyleSheet(f"color: {REQUIRED_COLOR}; font-size: 11px;")
    return lbl


# Scoped (via apply_large_form_style below), not a global theme.py change -
# Edit Business Hours and Block Time Off are the two forms an admin is most
# likely to be squinting at on a small/low-res screen (a front-desk tablet
# or laptop), so their text and controls run noticeably larger than the
# rest of the app's normal 10pt baseline instead of everywhere at once.
LARGE_FORM_FONT_PT = 13


def apply_large_form_style(widget):
    """Bumps font size and control padding for `widget` and everything
    inside it - a plain instance-level setStyleSheet, so it never leaks to
    a QMessageBox or other separately-parented top-level window it spawns,
    only to its own descendants."""
    widget.setStyleSheet(f"""
        QLabel {{ font-size: {LARGE_FORM_FONT_PT}pt; }}
        QPushButton {{ font-size: {LARGE_FORM_FONT_PT}pt; padding: 10px 20px; }}
        QTimeEdit, QDateEdit, QTextEdit, QCheckBox {{
            font-size: {LARGE_FORM_FONT_PT}pt;
        }}
        QTimeEdit, QDateEdit {{ padding: 8px 10px; }}
        QCheckBox::indicator {{ width: 22px; height: 22px; }}
    """)


def make_card(title):
    """A rounded white card with a bold heading, used throughout the Admin
    and Billing tabs in place of a plain QGroupBox - keeps the whole app
    reading as one consistent style rather than switching to native-Qt
    chrome for one particular window. Returns (card_frame, content_layout);
    add the rest of the card's widgets to content_layout."""
    card = QFrame()
    card.setObjectName("appCard")
    card.setStyleSheet(
        "#appCard { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 12px; }"
    )
    layout = QVBoxLayout(card)
    layout.setContentsMargins(18, 16, 18, 18)
    layout.setSpacing(12)
    title_label = QLabel(title)
    title_label.setStyleSheet("font-weight: 700; font-size: 13pt; color: #1e293b;")
    layout.addWidget(title_label)
    return card, layout


def style_history_table(table, stretch_column):
    """Common read-only history-table look (Billing's client balances,
    Client Detail's appointment/payment history, ...): alternating rows,
    no row-number gutter, whole-row selection, and every column sized to
    its own content except `stretch_column` (typically Notes - the one
    field with genuinely unpredictable length) which absorbs the rest of
    the width. Without this, QHeaderView.Stretch alone divides width
    evenly regardless of content, so a long fixed-format column (e.g. a
    date/time) gets squeezed and clipped while a usually-empty one (e.g.
    Notes) sits on wasted space."""
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QTableWidget.SelectRows)
    table.setAlternatingRowColors(True)
    header = table.horizontalHeader()
    for col in range(table.columnCount()):
        header.setSectionResizeMode(
            QHeaderView.Stretch if col == stretch_column else QHeaderView.ResizeToContents
        )


class _ShowPopupOnClick(QObject):
    """Installed on an editable QComboBox's internal line edit so a plain
    click into the field opens the full item list immediately, instead of
    only the small dropdown arrow doing that - otherwise the option list
    stays hidden from anyone who doesn't already know a name to type."""

    def __init__(self, combo):
        super().__init__(combo)
        self._combo = combo
        self._press_seen = False

    def eventFilter(self, obj, event):
        et = event.type()
        if et == QEvent.MouseButtonPress:
            # Only the press half of a click that starts while the popup
            # is closed counts - remembered so the popup only opens once
            # the *same* click's release has also gone by (see below).
            self._press_seen = not self._combo.view().isVisible()
        elif et == QEvent.MouseButtonRelease and self._press_seen:
            self._press_seen = False
            # Calling showPopup() synchronously from inside this same
            # click's mousePressEvent opens the popup, but then that same
            # click's still-upcoming mouseReleaseEvent (landing on the
            # line edit, not inside the freshly-opened popup) is read as
            # an "outside" click and immediately closes it again - the
            # popup flashes and disappears instead of staying open.
            # Opening it here instead, on the release, means this click's
            # own press+release is already fully done by the time the
            # popup exists, so there's no leftover event from it left to
            # dismiss anything. No extra artificial delay is needed - an
            # earlier version added one and it just made the popup feel
            # sluggish/forced instead of a normal, immediate open.
            if not self._combo.view().isVisible():
                self._combo.showPopup()
        return False


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
