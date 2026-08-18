"""PySide6 application runner."""

from __future__ import annotations

import sys
from typing import cast

from PySide6.QtWidgets import QApplication

from tagcor_ledger.app.bootstrap import StartupContext
from tagcor_ledger.app.logging_setup import get_logger
from tagcor_ledger.ui.error_handler import install_exception_handler
from tagcor_ledger.ui.main_window import MainWindow
from tagcor_ledger.ui.theme import apply_dark_theme


def run_gui(context: StartupContext) -> int:
    app = cast(QApplication, QApplication.instance() or QApplication(sys.argv[:1]))
    # 在建視窗之前裝 —— 建構過程本身也可能丟例外。
    install_exception_handler()
    apply_dark_theme(app)
    window = MainWindow(context.paths)
    window.show()
    get_logger("ui").info("window shown")
    exit_code = int(app.exec())
    get_logger("ui").info("window closed code=%s", exit_code)
    return exit_code
