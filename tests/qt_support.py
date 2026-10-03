"""One hidden QApplication for native widget contract tests."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

QT_APP = QApplication.instance() or QApplication([])
