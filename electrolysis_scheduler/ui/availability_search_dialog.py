from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox, QLabel,
    QPushButton, QScrollArea
)

from app import scheduling
from app.util import format_duration_minutes
from ui.availability_grid import AvailabilityGridWidget

# "Upcoming two weeks" by default; "Show More" steps through these in order,
# hiding the button once the last (longest) tier is reached - spec calls out
# "two weeks" then "e.g. the upcoming month" as the two concrete points, not
# an open-ended range, so a short fixed list reads clearer than a formula.
_RANGE_TIERS_DAYS = [14, 30]


class AvailabilitySearchDialog(QDialog):
    """Search Available Time Slot: pick a session length and see, as a
    calendar grid (same visual language as Month view), which upcoming
    days have any opening for it at all. Clicking an open day hands off
    to Day view to actually pick a time and book - the same two-step
    "browse, then pick a time" flow every other entry point into booking
    already uses, rather than a third, different way to book from here."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Search Available Time Slot")
        self.setMinimumSize(580, 520)
        self.selected_date = None
        self._tier_index = 0

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.duration_combo = QComboBox()
        for m in scheduling.default_duration_options():
            self.duration_combo.addItem(format_duration_minutes(m), m)
        self.duration_combo.currentIndexChanged.connect(self._run_search)
        form.addRow("Session length:", self.duration_combo)
        layout.addLayout(form)

        self.grid = AvailabilityGridWidget()
        self.grid.day_clicked.connect(self._choose)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(self.grid)
        layout.addWidget(scroll, 1)

        legend = QHBoxLayout()
        legend.addWidget(self._legend_dot("#22c55e", "Open"))
        legend.addWidget(self._legend_dot("#94a3b8", "Full / closed"))
        legend.addStretch()
        layout.addLayout(legend)

        self.range_label = QLabel("")
        self.range_label.setStyleSheet("color: #64748b; font-size: 9pt;")
        layout.addWidget(self.range_label)

        self.show_more_btn = QPushButton()
        self.show_more_btn.clicked.connect(self._show_more)
        layout.addWidget(self.show_more_btn)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._run_search()

    @staticmethod
    def _legend_dot(color, text):
        lbl = QLabel(f'<span style="color:{color};">⬤</span> {text}')
        lbl.setTextFormat(Qt.RichText)
        lbl.setStyleSheet("color: #334155; font-size: 9pt;")
        return lbl

    def _current_duration(self):
        return self.duration_combo.currentData()

    def _run_search(self):
        self._tier_index = 0
        self._populate()

    def _show_more(self):
        if self._tier_index < len(_RANGE_TIERS_DAYS) - 1:
            self._tier_index += 1
            self._populate()

    def _populate(self):
        duration = self._current_duration()
        num_days = _RANGE_TIERS_DAYS[self._tier_index]
        self.grid.set_search(duration, num_days)
        self.range_label.setText(f"Showing the upcoming {self._range_label(num_days)}.")

        more_left = self._tier_index < len(_RANGE_TIERS_DAYS) - 1
        self.show_more_btn.setVisible(more_left)
        if more_left:
            next_days = _RANGE_TIERS_DAYS[self._tier_index + 1]
            self.show_more_btn.setText(f"Show More (upcoming {self._range_label(next_days)})")

    @staticmethod
    def _range_label(num_days):
        return "month" if num_days >= 28 else f"{num_days // 7} weeks"

    def _choose(self, d):
        self.selected_date = d
        self.accept()
