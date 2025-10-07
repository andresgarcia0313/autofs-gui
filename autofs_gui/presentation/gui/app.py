from __future__ import annotations
import sys
from PySide6.QtWidgets import QApplication
# import pyqtdarktheme

from .main_window import MainWindow

def run():
    app = QApplication(sys.argv)
    # pyqtdarktheme.setup_theme()

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
