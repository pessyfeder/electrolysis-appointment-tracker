from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem
)
from PySide6.QtGui import QColor

from ui.widgets import style_history_table

REPORT_FONT_PT = 13
DEBT_COLOR = QColor("#b91c1c")


class PaymentReportDialog(QDialog):
    """Large, easy-to-read popup shown for a payment report - the tablet
    this app runs on has no spreadsheet/PDF viewer, so a report needs to be
    comfortably readable inside its own big window rather than squeezed
    into the Billing tab alongside everything else.

    One consolidated ledger, money in and money owed together in date
    order: a payment is a normal positive amount, and an unpaid charge
    (no-show or an unpaid completed session) is shown as a negative amount
    in red, the same way a bank statement or account ledger reads."""

    def __init__(self, parent, start_d, end_d, payments, unpaid_charges):
        super().__init__(parent)
        self.setWindowTitle(
            f"Billing Report — {start_d.toString('MMM d, yyyy')} to {end_d.toString('MMM d, yyyy')}"
        )
        self.resize(900, 650)
        self.setSizeGripEnabled(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(14)

        title = QLabel(
            f"{start_d.toString('MMM d, yyyy')} – {end_d.toString('MMM d, yyyy')}"
        )
        title.setStyleSheet("font-weight: 700; font-size: 16pt; color: #1e293b;")
        outer.addWidget(title)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Date", "Client", "Amount", "Method / Notes"])
        style_history_table(self.table, stretch_column=3)
        self.table.setStyleSheet(f"QTableWidget {{ font-size: {REPORT_FONT_PT}pt; }}")
        self.table.horizontalHeader().setStyleSheet(f"font-size: {REPORT_FONT_PT}pt; font-weight: 600;")
        self.table.verticalHeader().setDefaultSectionSize(32)
        outer.addWidget(self.table, 1)

        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("font-weight: 700; font-size: 13pt; color: #1e293b;")
        self.summary_label.setWordWrap(True)
        outer.addWidget(self.summary_label)

        self._populate(payments, unpaid_charges)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setObjectName("primaryButton")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        outer.addLayout(close_row)

    def _populate(self, payments, unpaid_charges):
        rows = []
        for p in payments:
            rows.append({
                "date": datetime.fromisoformat(p["paid_at"]),
                "client": f'{p["first_name"]} {p["last_name"]}'.strip(),
                "amount": p["amount"],
                "method_notes": p["method"],
                "is_debt": False,
            })
        for ch in unpaid_charges:
            rows.append({
                "date": datetime.fromisoformat(ch["start_datetime"]),
                "client": f'{ch["first_name"]} {ch["last_name"]}'.strip(),
                "amount": ch["amount"],
                "method_notes": "No Show" if ch["status"] == "no_show" else "Unpaid",
                "is_debt": True,
            })
        rows.sort(key=lambda r: r["date"])

        self.table.setRowCount(len(rows))
        collected = 0.0
        owed = 0.0
        for row, r in enumerate(rows):
            self.table.setItem(row, 0, QTableWidgetItem(r["date"].strftime("%b %d, %Y")))
            self.table.setItem(row, 1, QTableWidgetItem(r["client"]))
            amount_text = f'-${r["amount"]:.2f}' if r["is_debt"] else f'${r["amount"]:.2f}'
            amount_item = QTableWidgetItem(amount_text)
            if r["is_debt"]:
                amount_item.setForeground(DEBT_COLOR)
                font = amount_item.font()
                font.setBold(True)
                amount_item.setFont(font)
            self.table.setItem(row, 2, amount_item)
            self.table.setItem(row, 3, QTableWidgetItem(r["method_notes"]))
            if r["is_debt"]:
                owed += r["amount"]
            else:
                collected += r["amount"]

        if not rows:
            self.summary_label.setText("No payments or unpaid charges in this date range.")
        else:
            net = collected - owed
            self.summary_label.setText(
                f"Collected: ${collected:.2f}   |   Owed (unpaid): ${owed:.2f}   |   Net: ${net:.2f}"
            )
