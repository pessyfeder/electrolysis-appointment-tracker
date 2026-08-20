from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTimeEdit, QPushButton,
    QGroupBox, QScrollArea, QWidget, QMessageBox
)
from PySide6.QtCore import QTime

from app import models

DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


class _BlockRow(QWidget):
    def __init__(self, start_time="09:00", end_time="17:00", on_remove=None):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.start_edit = QTimeEdit()
        self.start_edit.setDisplayFormat("h:mm AP")
        sh, sm = map(int, start_time.split(":"))
        self.start_edit.setTime(QTime(sh, sm))
        self.end_edit = QTimeEdit()
        self.end_edit.setDisplayFormat("h:mm AP")
        eh, em = map(int, end_time.split(":"))
        self.end_edit.setTime(QTime(eh, em))
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(lambda: on_remove(self) if on_remove else None)
        layout.addWidget(QLabel("From"))
        layout.addWidget(self.start_edit)
        layout.addWidget(QLabel("to"))
        layout.addWidget(self.end_edit)
        layout.addWidget(remove_btn)
        layout.addStretch()

    def as_tuple(self):
        return (
            f"{self.start_edit.time().hour():02d}:{self.start_edit.time().minute():02d}",
            f"{self.end_edit.time().hour():02d}:{self.end_edit.time().minute():02d}",
        )


class BusinessHoursDialog(QDialog):
    """Edit business hours per day (spec 7.1, Phase 3). Caller must re-verify
    the admin password before opening this dialog (spec 7.4)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Business Hours")
        self.setMinimumSize(480, 520)

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        self.day_boxes = {}
        for day in DAYS:
            box = QGroupBox(day)
            box_layout = QVBoxLayout(box)
            rows_container = QVBoxLayout()
            box_layout.addLayout(rows_container)
            add_btn = QPushButton("+ Add time block")
            box_layout.addWidget(add_btn)
            self.day_boxes[day] = {"rows_container": rows_container, "rows": []}
            add_btn.clicked.connect(lambda checked=False, d=day: self._add_row(d))
            self.content_layout.addWidget(box)

            for hr in models.business_hours_for_day(day):
                self._add_row(day, hr["start_time"], hr["end_time"])

        self.content_layout.addStretch()

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        outer.addLayout(btn_row)

    def _add_row(self, day, start_time="10:00", end_time="17:00"):
        info = self.day_boxes[day]

        def remove(row_widget):
            info["rows"].remove(row_widget)
            info["rows_container"].removeWidget(row_widget)
            row_widget.deleteLater()

        row = _BlockRow(start_time, end_time, on_remove=remove)
        info["rows"].append(row)
        info["rows_container"].addWidget(row)

    def _save(self):
        for day, info in self.day_boxes.items():
            blocks = []
            for row in info["rows"]:
                s, e = row.as_tuple()
                if s >= e:
                    QMessageBox.warning(self, "Invalid Block", f"{day}: end time must be after start time.")
                    return
                blocks.append((s, e))
            models.replace_business_hours_for_day(day, blocks)
        self.accept()
