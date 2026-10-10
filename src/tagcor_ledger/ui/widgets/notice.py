"""提示框：出了問題、被擋下來，或做完一件需要讀一下的事。**按鈕寫「確定」。**

靜態的 `QMessageBox.warning()`／`information()` 用的是 Qt 的標準按鈕文字，而這個程式沒有載入
Qt 自己的翻譯 —— 全中文的提示框底下是英文的「OK」（2026-10-09 截圖時發現，從第一天就這樣）。
做法跟確認框（`confirm.py`）一樣：自己建 `QMessageBox`，標準按鈕照用，只換掉上面的字。
`tests/unit/test_architecture.py` 擋住直接呼叫那些靜態函式。

「確定」不是「好」也不是「OK」：專案裡每一張自己的對話框（新增、排序、表單）確認鈕都寫「確定」，
這裡跟它們同一個字。
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

OK_TEXT = "確定"


def warn(parent: QWidget, title: str, text: str) -> None:
    """失敗或被擋下來 —— 要讓使用者讀完、知道接下來怎麼辦的那種。"""
    _show(QMessageBox.Icon.Warning, parent, title, text)


def inform(parent: QWidget, title: str, text: str) -> None:
    """不是錯誤，但要讓使用者知道一件事（例如產生了幾件待確認草稿）。"""
    _show(QMessageBox.Icon.Information, parent, title, text)


def _show(icon: QMessageBox.Icon, parent: QWidget, title: str, text: str) -> None:
    box = QMessageBox(icon, title, text, QMessageBox.StandardButton.Ok, parent)
    box.button(QMessageBox.StandardButton.Ok).setText(OK_TEXT)
    box.exec()
