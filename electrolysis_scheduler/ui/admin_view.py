from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QButtonGroup, QFrame,
    QStackedWidget, QMessageBox
)

from ui.business_hours_dialog import BusinessHoursEditor
from ui.block_time_dialog import BlockTimeForm


class AdminView(QWidget):
    """The Admin tab: a segmented control (same visual pattern as the
    calendar's Day/Week/Month toggle) that switches between three always-
    embedded pages - Edit Business Hours, Block Time Off, and Billing -
    instead of a menu that launches separate dialogs/pages. Opens on Edit
    Business Hours by default."""

    def __init__(self, parent=None, billing_view=None, on_calendar_changed=None):
        super().__init__(parent)
        self.billing_view = billing_view
        self.on_calendar_changed = on_calendar_changed or (lambda: None)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(10)

        segmented = QFrame()
        segmented.setObjectName("adminSegmented")
        segmented.setStyleSheet(
            "#adminSegmented { background: #f1f5f9; border-radius: 8px; }"
            "#adminSegmented QPushButton { background: transparent; border: 1px solid transparent; "
            "padding: 7px 18px; border-radius: 6px; color: #64748b; font-size: 12px; font-weight: 600; }"
            "#adminSegmented QPushButton:checked { background: #ffffff; color: #1e293b; "
            "border: 1px solid #e2e8f0; }"
        )
        seg_layout = QHBoxLayout(segmented)
        seg_layout.setContentsMargins(3, 3, 3, 3)
        seg_layout.setSpacing(2)

        self.hours_btn = QPushButton("Edit Business Hours")
        self.block_btn = QPushButton("Block Time Off")
        self.billing_btn = QPushButton("Billing")
        self._group = QButtonGroup(segmented)
        self._group.setExclusive(True)
        for btn in (self.hours_btn, self.block_btn, self.billing_btn):
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            self._group.addButton(btn)
            seg_layout.addWidget(btn)

        seg_row = QHBoxLayout()
        seg_row.addWidget(segmented)
        seg_row.addStretch()
        outer.addLayout(seg_row)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack)

        # No require_admin gate on these two - reaching the Admin tab at all
        # already required the password (see MainWindow._on_tab_changed),
        # and re-prompting again on every Save here would just be redundant
        # friction with no security benefit.
        self.hours_editor = BusinessHoursEditor(on_saved=self._on_hours_saved)
        self.block_form = BlockTimeForm(on_saved=self._on_block_saved)
        self.stack.addWidget(self.hours_editor)
        self.stack.addWidget(self.block_form)
        self.stack.addWidget(self.billing_view)

        # Set the initial checked state before wiring up toggled - connecting
        # first would fire the stack switch before the stack itself (and the
        # widgets it holds) exist yet.
        self.hours_btn.setChecked(True)
        self.hours_btn.toggled.connect(lambda checked: checked and self.stack.setCurrentIndex(0))
        self.block_btn.toggled.connect(lambda checked: checked and self.stack.setCurrentIndex(1))
        self.billing_btn.toggled.connect(lambda checked: checked and self._show_billing())

    def _show_billing(self):
        self.billing_view.refresh()
        self.stack.setCurrentIndex(2)

    def _on_hours_saved(self):
        self.on_calendar_changed()
        QMessageBox.information(self, "Saved", "Business hours updated.")

    def _on_block_saved(self):
        self.on_calendar_changed()
        QMessageBox.information(self, "Blocked", "Time blocked off.")

    def refresh(self):
        # Always land back on Edit Business Hours when the tab is
        # (re)entered, and refresh the Block Time Off form's date/time
        # defaults to "now" rather than whatever they were the last time
        # this widget happened to be constructed.
        self.hours_btn.blockSignals(True)
        self.hours_btn.setChecked(True)
        self.hours_btn.blockSignals(False)
        self.stack.setCurrentIndex(0)
        self.block_form.refresh()
