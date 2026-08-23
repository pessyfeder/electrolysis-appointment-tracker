"""App-wide look and feel: Fusion style + a flat QSS theme.

Applied once in main.py before any windows are constructed.
"""

STYLESHEET = """
* {
    font-family: "Segoe UI", sans-serif;
    font-size: 10pt;
    color: #1e293b;
}

QMainWindow, QDialog, QWidget {
    background: #f8fafc;
}

QToolTip {
    background: #1e293b;
    color: #f8fafc;
    border: none;
    padding: 4px 8px;
    border-radius: 4px;
}

/* ---- Tabs ---- */
QTabWidget::pane {
    border: 1px solid #e2e8f0;
    background: #ffffff;
    border-radius: 6px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #64748b;
    padding: 8px 18px;
    margin-right: 2px;
    border-bottom: 2px solid transparent;
    font-weight: 600;
}
QTabBar::tab:selected {
    color: #2563eb;
    border-bottom: 2px solid #2563eb;
}
QTabBar::tab:hover:!selected {
    color: #334155;
}

/* ---- Buttons ---- */
QPushButton {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 6px 14px;
    color: #334155;
}
QPushButton:hover {
    background: #f1f5f9;
    border-color: #94a3b8;
}
QPushButton:pressed {
    background: #e2e8f0;
}
QPushButton:disabled {
    color: #94a3b8;
    background: #f1f5f9;
    border-color: #e2e8f0;
}
QPushButton:default, QPushButton#primaryButton {
    background: #2563eb;
    border: 1px solid #1d4ed8;
    color: #ffffff;
    font-weight: 600;
}
QPushButton:default:hover, QPushButton#primaryButton:hover {
    background: #1d4ed8;
}
QPushButton:default:pressed, QPushButton#primaryButton:pressed {
    background: #1e40af;
}

/* ---- Inputs ---- */
QLineEdit, QTextEdit, QPlainTextEdit, QDoubleSpinBox, QSpinBox, QDateEdit, QComboBox {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: #bfdbfe;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QDoubleSpinBox:focus,
QSpinBox:focus, QDateEdit:focus, QComboBox:focus {
    border: 1px solid #2563eb;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    selection-background-color: #dbeafe;
    selection-color: #1e293b;
    outline: none;
}
QCheckBox {
    spacing: 8px;
}

/* ---- Lists / tables ---- */
QListWidget, QTableWidget {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    gridline-color: #f1f5f9;
    alternate-background-color: #f8fafc;
}
QListWidget::item, QTableWidget::item {
    padding: 4px;
}
QListWidget::item:selected, QTableWidget::item:selected {
    background: #dbeafe;
    color: #1e293b;
}
QHeaderView::section {
    background: #f1f5f9;
    color: #475569;
    padding: 6px;
    border: none;
    border-bottom: 1px solid #e2e8f0;
    font-weight: 600;
}

/* ---- Group boxes ---- */
QGroupBox {
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 10px;
    font-weight: 600;
    background: #ffffff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #334155;
}

/* ---- Menus ---- */
QMenuBar {
    background: #ffffff;
    border-bottom: 1px solid #e2e8f0;
}
QMenuBar::item:selected {
    background: #eff6ff;
    color: #2563eb;
}
QMenu {
    background: #ffffff;
    border: 1px solid #e2e8f0;
}
QMenu::item:selected {
    background: #eff6ff;
    color: #2563eb;
}

/* ---- Misc containers ---- */
QScrollArea {
    border: none;
}
QSplitter::handle {
    background: #e2e8f0;
}
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #cbd5e1;
    border-radius: 5px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background: #94a3b8;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 12px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #cbd5e1;
    border-radius: 5px;
    min-width: 24px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
"""


def apply_theme(app):
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
