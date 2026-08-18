"""PySide6 application runner."""

from __future__ import annotations

import sys
from typing import cast

from PySide6.QtWidgets import QApplication

from tagcor_ledger.app.bootstrap import StartupContext
from tagcor_ledger.ui.main_window import MainWindow
from tagcor_ledger.ui.theme import apply_dark_theme


def run_gui(context: StartupContext) -> int:
    app = cast(QApplication, QApplication.instance() or QApplication(sys.argv[:1]))
    apply_dark_theme(app)
    window = MainWindow(context.paths)
    window.show()
    return int(app.exec())
