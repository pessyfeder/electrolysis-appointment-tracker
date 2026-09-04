from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QCheckBox,
    QListWidget, QListWidgetItem, QLabel, QPushButton, QWidget
)

from app import models
from app.util import format_12h, format_client_name
from ui.calendar_view import STATUS_STYLES, STATUS_LABELS
from ui.widgets import ClickToOpenDateEdit


class AppointmentSearchDialog(QDialog):
    """Find an appointment by client name/phone and/or date, then jump to
    it - a plain text/date filter over search_appointments() rather than
    scrubbing through the calendar to find one client's booking."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Search Appointments")
        self.setMinimumSize(560, 480)
        self.selected_appt = None

        layout = QVBoxLayout(self)

        filters = QHBoxLayout()
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("Client name or phone…")
        self.query_edit.textChanged.connect(self._run_search)
        filters.addWidget(self.query_edit, 1)

        self.date_check = QCheckBox("On date:")
        self.date_check.toggled.connect(self._on_date_toggle)
        filters.addWidget(self.date_check)

        self.date_edit = ClickToOpenDateEdit()
        self.date_edit.setDate(datetime.now().date())
        self.date_edit.setEnabled(False)
        self.date_edit.dateChanged.connect(self._run_search)
        filters.addWidget(self.date_edit)
        layout.addLayout(filters)

        self.results_list = QListWidget()
        self.results_list.setStyleSheet(
            "QListWidget { border: 1px solid #e2e8f0; border-radius: 8px; } "
            "QListWidget::item { border-bottom: 1px solid #f1f5f9; } "
            "QListWidget::item:selected { background: #eff6ff; }"
        )
        self.results_list.itemDoubleClicked.connect(self._on_item_chosen)
        layout.addWidget(self.results_list, 1)

        hint = QLabel("Double-click a result to open it.")
        hint.setStyleSheet("color: #64748b; font-size: 9pt;")
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._run_search()
        self.query_edit.setFocus()

    def _on_date_toggle(self, checked):
        self.date_edit.setEnabled(checked)
        self._run_search()

    def _run_search(self):
        query = self.query_edit.text().strip()
        on_date = self.date_edit.date().toPython() if self.date_check.isChecked() else None
        self.results_list.clear()

        if not query and on_date is None:
            self._show_placeholder("Type a name/phone, or check a date, to search.")
            return

        results = models.search_appointments(query, on_date)
        if not results:
            self._show_placeholder("No matching appointments.")
            return

        for a in results:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, a)
            row = self._build_result_row(a)
            item.setSizeHint(row.sizeHint())
            self.results_list.addItem(item)
            self.results_list.setItemWidget(item, row)

    def _show_placeholder(self, text):
        placeholder = QListWidgetItem(text)
        placeholder.setFlags(Qt.NoItemFlags)
        self.results_list.addItem(placeholder)

    @staticmethod
    def _build_result_row(a):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        s = datetime.fromisoformat(a["start_datetime"])
        when_label = QLabel(f"{s.strftime('%a, %b %d, %Y')} · {format_12h(s)}")
        when_label.setStyleSheet("font-weight: 700; color: #1e293b;")
        names = ", ".join(
            format_client_name(c["first_name"], c["last_name"]) for c in a["clients"]
        ) or "(no client)"
        name_label = QLabel(names)
        name_label.setStyleSheet("color: #334155;")

        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(when_label)
        col.addWidget(name_label)
        layout.addLayout(col, 1)

        bg, border, text_color = STATUS_STYLES.get(a["status"], ("#f8fafc", "#e2e8f0", "#1e293b"))
        pill = QLabel(STATUS_LABELS.get(a["status"], a["status"]))
        pill.setStyleSheet(
            f"background: {bg}; color: {text_color}; border: 1px solid {border}; "
            "border-radius: 9px; padding: 2px 10px; font-weight: 600; font-size: 9pt;"
        )
        layout.addWidget(pill)
        return row

    def _on_item_chosen(self, item):
        appt = item.data(Qt.UserRole)
        if appt:
            self.selected_appt = appt
            self.accept()
