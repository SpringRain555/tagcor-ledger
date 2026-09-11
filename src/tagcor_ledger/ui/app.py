"""PySide6 應用程式的啟動器。"""

from __future__ import annotations

import sys
from typing import cast

from PySide6.QtWidgets import QApplication

from tagcor_ledger.app import startup_signal
from tagcor_ledger.app.bootstrap import StartupContext
from tagcor_ledger.app.logging_setup import get_logger
from tagcor_ledger.ui.error_handler import install_exception_handler
from tagcor_ledger.ui.instance_channel import ActivationServer, bring_to_front
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

    # 告訴啟動器「使用者看得到東西了」，它等的就是這個檔案。**在 `show()` 之後**，
    # 提早寫就只是「程式碼跑到這一行了」。寫不進去不影響使用，只是主控台會多等一會。
    marker = startup_signal.marker_path(context.paths)
    if not startup_signal.mark_ready(marker):
        get_logger("ui").warning("ready marker not written path=%s", marker)

    # 開一扇門，讓之後的啟動可以把這個視窗叫到最前面而不是被擋下來。
    # 變數要留著，否則 server 會被回收。開不起來也不影響使用，只是退回警告對話框。
    activation_server = ActivationServer(
        context.paths.ledger_dir, lambda: bring_to_front(window)
    )
    activation_server.start()

    exit_code = int(app.exec())
    activation_server.close()
    get_logger("ui").info("window closed code=%s", exit_code)
    return exit_code
