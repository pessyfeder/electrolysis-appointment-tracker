from datetime import datetime, timedelta

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox,
    QTextEdit, QPushButton, QLabel, QTableWidget, QTableWidgetItem,
    QFileDialog, QMessageBox, QCompleter
)
from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor

from app import models, billing
from app.util import format_client_name
from ui.client_detail_dialog import ClientDetailDialog
from ui.widgets import (
    ClickToOpenDateEdit, TypeOnlyDoubleSpinBox, open_dropdown_on_click,
    required_label, required_hint_label, make_card, style_history_table
)

METHODS = ["cash", "card", "check", "other"]


class BillingView(QWidget):
    def __init__(self, parent=None, require_admin=None):
        super().__init__(parent)
        self.require_admin = require_admin or (lambda: True)
        root = QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(14)

        # --- Left: record a payment ---
        left, left_layout = make_card("Record a Payment")
        form = QFormLayout()
        form.setSpacing(10)

        self.client_combo = QComboBox()
        self.client_combo.setEditable(True)
        self.client_combo.setInsertPolicy(QComboBox.NoInsert)
        self._reload_clients()
        completer = QCompleter([self.client_combo.itemText(i) for i in range(self.client_combo.count())])
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.client_combo.setCompleter(completer)
        open_dropdown_on_click(self.client_combo)
        self.client_combo.currentIndexChanged.connect(self._refresh_balance_preview)
        form.addRow(required_label("Client:"), self.client_combo)

        self.balance_preview = QLabel("")
        form.addRow("Current balance:", self.balance_preview)

        self.amount_spin = TypeOnlyDoubleSpinBox()
        self.amount_spin.setRange(0, 100000)
        self.amount_spin.setPrefix("$")
        self.amount_spin.setDecimals(2)
        form.addRow(required_label("Amount:"), self.amount_spin)

        self.method_combo = QComboBox()
        self.method_combo.addItems(METHODS)
        form.addRow(required_label("Method:"), self.method_combo)

        self.notes_edit = QTextEdit()
        self.notes_edit.setFixedHeight(60)
        form.addRow("Notes (optional):", self.notes_edit)

        left_layout.addLayout(form)

        left_layout.addWidget(required_hint_label())

        record_btn = QPushButton("Record Payment")
        record_btn.setObjectName("primaryButton")
        record_btn.setDefault(True)
        record_btn.clicked.connect(self._record_payment)
        left_layout.addWidget(record_btn)
        left_layout.addStretch()

        root.addWidget(left, 1)

        # --- Right: balances + export ---
        right = QVBoxLayout()
        right.setSpacing(14)

        balances_box, balances_layout = make_card("Client Balances")
        balances_hint = QLabel(
            "Double-click a client for balance, full history, and archive (admin password required)."
        )
        balances_hint.setWordWrap(True)
        balances_hint.setStyleSheet("color: #64748b;")
        balances_layout.addWidget(balances_hint)
        self.balances_table = QTableWidget(0, 2)
        self.balances_table.setHorizontalHeaderLabels(["Client", "Balance"])
        style_history_table(self.balances_table, stretch_column=0)
        self.balances_table.itemDoubleClicked.connect(self._open_client_detail)
        balances_layout.addWidget(self.balances_table)
        right.addWidget(balances_box, 2)

        export_box, export_layout = make_card("Export Payments (CSV)")
        range_row = QHBoxLayout()
        self.start_date_edit = ClickToOpenDateEdit()
        self.start_date_edit.setDate(QDate.currentDate().addMonths(-1))
        self.end_date_edit = ClickToOpenDateEdit()
        self.end_date_edit.setDate(QDate.currentDate())
        range_row.addWidget(QLabel("From:"))
        range_row.addWidget(self.start_date_edit)
        range_row.addWidget(QLabel("To:"))
        range_row.addWidget(self.end_date_edit)
        export_layout.addLayout(range_row)
        export_btn = QPushButton("Export CSV…")
        export_btn.clicked.connect(self._export_csv)
        export_layout.addWidget(export_btn)
        right.addWidget(export_box, 1)

        root.addLayout(right, 1)

        self.refresh()

    def _reload_clients(self):
        self.client_combo.clear()
        for c in models.list_clients():
            self.client_combo.addItem(format_client_name(c["first_name"], c["last_name"]), c["id"])

    def refresh(self):
        self._reload_clients()
        self._refresh_balance_preview()
        self._refresh_balances_table()

    @staticmethod
    def _balance_text_and_color(balance):
        if balance > 0:
            return f"Owes ${balance:.2f}", "#b91c1c"
        if balance < 0:
            return f"${-balance:.2f} credit", "#15803d"
        return "$0.00", "#64748b"

    def _refresh_balance_preview(self):
        client_id = self._selected_client_id()
        if not client_id:
            self.balance_preview.setText("")
            self.balance_preview.setStyleSheet("")
            return
        text, color = self._balance_text_and_color(models.client_balance(client_id))
        self.balance_preview.setText(text)
        self.balance_preview.setStyleSheet(f"color: {color}; font-weight: 600;")

    def _refresh_balances_table(self):
        clients = models.list_clients()
        self.balances_table.setRowCount(len(clients))
        for row, c in enumerate(clients):
            balance = models.client_balance(c["id"])
            name_item = QTableWidgetItem(format_client_name(c["first_name"], c["last_name"]))
            name_item.setData(Qt.UserRole, c["id"])
            self.balances_table.setItem(row, 0, name_item)
            text, color = self._balance_text_and_color(balance)
            item = QTableWidgetItem(text.replace("Owes ", ""))
            item.setForeground(QColor(color))
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            self.balances_table.setItem(row, 1, item)

    def _open_client_detail(self, item):
        row = item.row()
        client_id = self.balances_table.item(row, 0).data(Qt.UserRole)
        if not client_id or not self.require_admin():
            return
        dlg = ClientDetailDialog(self, client_id)
        dlg.exec()
        self._refresh_balances_table()

    def _selected_client_id(self):
        """currentIndex()/itemData() only update once an item is actually
        chosen from the dropdown/completer. If the user types a name (e.g.
        to filter via the completer) and clicks Record Payment without
        picking a suggestion, the combo's displayed text and its
        currentIndex fall out of sync - currentIndex still points at
        whichever client was previously selected, so trusting it blindly
        would silently record the payment against the wrong client. Resolve
        by exact text match instead so a stale/unselected index is
        rejected rather than misattributed."""
        idx = self.client_combo.currentIndex()
        text = self.client_combo.currentText().strip()
        if idx >= 0 and self.client_combo.itemText(idx) == text:
            return self.client_combo.itemData(idx)
        match = self.client_combo.findText(text, Qt.MatchFixedString)
        if match >= 0:
            return self.client_combo.itemData(match)
        return None

    def _record_payment(self):
        client_id = self._selected_client_id()
        if not client_id:
            QMessageBox.warning(self, "Missing Client", "Please select a client from the list.")
            return
        amount = self.amount_spin.value()
        if amount <= 0:
            QMessageBox.warning(self, "Invalid Amount", "Enter an amount greater than $0.")
            return
        models.create_payment(
            client_id, amount, self.method_combo.currentText(), self.notes_edit.toPlainText()
        )
        self.amount_spin.setValue(0)
        self.notes_edit.clear()
        self.refresh()
        QMessageBox.information(self, "Payment Recorded", f"Recorded ${amount:.2f}.")

    def _export_csv(self):
        start_d = self.start_date_edit.date()
        end_d = self.end_date_edit.date()
        start_dt = datetime(start_d.year(), start_d.month(), start_d.day(), 0, 0)
        end_dt = datetime(end_d.year(), end_d.month(), end_d.day(), 23, 59, 59)
        if end_dt < start_dt:
            QMessageBox.warning(self, "Invalid Range", "End date must be on or after the start date.")
            return
        default_name = f"payments_{start_d.toString('yyyy-MM-dd')}_to_{end_d.toString('yyyy-MM-dd')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export Payments CSV", default_name, "CSV Files (*.csv)")
        if not path:
            return
        count = billing.export_payments_csv(path, start_dt, end_dt)
        QMessageBox.information(self, "Export Complete", f"Exported {count} payment(s) to {path}.")
