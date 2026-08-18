"""啟動失敗時的 Qt 對話框。

單獨放一個模組，是為了讓 `main.py` 不必自己 import PySide6 —— Qt 本身就是啟動可能失敗
的一環（DLL 載入失敗、沒有顯示裝置），所以呼叫端必須能在 import 這一步就接住失敗並退回
stderr。把 Qt 關在這裡，`main.py` 只需要 try 一個 import。
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox


def show_startup_failure(title: str, body: str) -> None:
    """顯示錯誤並等使用者關閉。

    這裡刻意**不套用深色主題** —— 主題來自 QSS 資源，而資源讀不到本身就可能是啟動失敗
    的原因。用 Qt 預設外觀比較醜，但保證顯示得出來。
    """
    app = QApplication.instance() or QApplication(sys.argv[:1])
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle("TagCor Ledger")
    box.setText(title)
    box.setInformativeText(body)
    box.setStandardButtons(QMessageBox.StandardButton.Close)
    close_button = box.button(QMessageBox.StandardButton.Close)
    if close_button is not None:
        close_button.setText("關閉")
    box.exec()
    del app
