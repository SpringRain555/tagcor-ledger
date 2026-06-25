"""PySide6 application runner."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from tagcor_ledger.app.bootstrap import StartupContext
from tagcor_ledger.ui.main_window_phase12 import MainWindow


def run_gui(context: StartupContext) -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = MainWindow(context.paths)
    window.show()
    return int(app.exec())
