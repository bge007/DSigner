"""
DSigner - Main Application Entry Point

Application: DSigner
Version: 0.2.0
Publisher: BGE
Organised by: Benoy George
License: MIT
Purpose: Read, inspect, and digitally sign PDF documents with certificates
from the Windows Certificate Store.
"""
import ctypes
import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from core.app_info import APP_ID, APP_NAME, APP_VERSION
from core.logging_setup import setup_logging
from core.resources import resource_path
from ui.main_window import MainWindow

os.environ["QT_QPA_FONTDIR"] = ""

APP_STYLE = """
QMainWindow, QWidget {
    background: #f4f6fb;
    color: #1e293b;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", sans-serif;
    font-size: 10pt;
}
QGroupBox {
    background: #ffffff;
    border: 1px solid #dbe2ef;
    border-radius: 8px;
    margin-top: 14px;
    padding: 12px 8px 8px 8px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #334155;
}
QPushButton {
    background: #e2e8f0;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 6px 14px;
}
QPushButton:hover { background: #cbd5e1; }
QPushButton:disabled { color: #94a3b8; background: #eef2f7; }
QPushButton#primaryButton {
    background: #2563eb;
    color: white;
    border: none;
    font-weight: 600;
}
QPushButton#primaryButton:hover { background: #1d4ed8; }
QPushButton#signButton {
    background: #16a34a;
    color: white;
    border: none;
    font-weight: 700;
    padding: 8px 18px;
}
QPushButton#signButton:hover { background: #15803d; }
QPushButton#signButton:checked { background: #166534; }
QPushButton#signButton:disabled { background: #b7dfc5; color: #f0fdf4; }
QLineEdit, QSpinBox {
    background: white;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 4px 6px;
}
QLineEdit:focus, QSpinBox:focus { border-color: #2563eb; }
QLabel#fileLabel { color: #64748b; padding-left: 8px; }
QLabel#hintLabel { color: #64748b; font-size: 9pt; font-weight: 400; }
QScrollArea {
    border: 1px solid #dbe2ef;
    border-radius: 6px;
    background: #e2e8f0;
}
QScrollArea > QWidget > QWidget { background: #e2e8f0; }
QStatusBar { color: #475569; }
QTabWidget::pane { border: none; }
QTabBar::tab {
    background: #e2e8f0;
    border: 1px solid #cbd5e1;
    border-bottom: none;
    padding: 6px 14px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
    color: #475569;
}
QTabBar::tab:selected { background: white; color: #1e293b; font-weight: 600; }
QTabBar::tab:hover:!selected { background: #cbd5e1; }
QTableWidget {
    background: white;
    border: 1px solid #dbe2ef;
    border-radius: 6px;
    gridline-color: #eef2f7;
    selection-background-color: #2563eb;
    selection-color: white;
}
QTableWidget::item:selected {
    background: #2563eb;
    color: white;
}
QTableWidget::item:selected:!active {
    background: #60a5fa;
    color: white;
}
QHeaderView::section {
    background: #eef2f7;
    border: none;
    border-bottom: 1px solid #dbe2ef;
    padding: 5px 8px;
    font-weight: 600;
}
"""


def main():
    setup_logging()

    # give the app its own taskbar identity/icon on Windows
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setStyleSheet(APP_STYLE)
    app.setWindowIcon(QIcon(resource_path("assets/logo.png")))
    window = MainWindow()
    window.show()
    window.restore_session()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
