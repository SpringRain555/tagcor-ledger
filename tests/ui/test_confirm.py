"""確認框：按鈕寫「是」「否」、預設是「否」、還原照勾選框說實話。

`confirm()` 固定把預設按鈕設成「否」。**這裡用真的對話框按 Enter**，不是只檢查傳了什麼參數 ——
要守的是「使用者按下 Enter 會發生什麼」，而那取決於 Qt 怎麼解讀參數（`question()` 不指定預設
按鈕時，焦點落在「是」上）。按鈕上的字也是看真的那個對話框：靜態的 `question()` 給的是英文的
Yes／No，`confirm()` 自己建對話框才換得掉。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from tagcor_ledger.ui.widgets.confirm import confirm


def _answer_with(action: Callable[[QMessageBox], None]) -> list[str]:
    """對話框一出來就做 `action`。回傳一個 list，對話框真的出現過就會有一筆。

    **找不到對話框時一定要收場**：`exec()` 會一直等，測試就掛在那裡。所以重試幾次，
    最後把所有看得到的 `QMessageBox` 關掉。
    """
    seen: list[str] = []

    def attempt(tries_left: int) -> None:
        box = QApplication.activeModalWidget()
        if isinstance(box, QMessageBox):
            seen.append(box.text())
            action(box)
            return
        if tries_left > 0:
            QTimer.singleShot(20, lambda: attempt(tries_left - 1))
            return
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QMessageBox) and widget.isVisible():
                widget.done(0)

    QTimer.singleShot(20, lambda: attempt(50))
    return seen


def test_pressing_enter_on_a_confirmation_means_no(qtbot: Any) -> None:
    """對話框一出來就按 Enter：**不動手**。這正是 `confirm()` 存在的理由。"""
    parent = QWidget()
    qtbot.addWidget(parent)
    seen = _answer_with(lambda box: QTest.keyClick(box, Qt.Key.Key_Return))

    assert confirm(parent, "確認刪除", "確定要刪除嗎？") is False
    assert seen == ["確定要刪除嗎？"], "對話框沒有出現，這條沒在測 Enter"


def test_clicking_yes_is_the_only_way_to_say_yes(qtbot: Any) -> None:
    """陽性對照：按「是」要回傳 True —— 否則上一條的 False 可能只是「什麼都會回 False」。"""
    parent = QWidget()
    qtbot.addWidget(parent)
    seen = _answer_with(lambda box: box.button(QMessageBox.StandardButton.Yes).click())

    assert confirm(parent, "確認刪除", "確定要刪除嗎？") is True
    assert seen, "對話框沒有出現"


def test_the_buttons_say_yes_and_no_in_chinese(qtbot: Any) -> None:
    """按鈕寫「是」「否」，不是 Qt 的英文 Yes／No；「否」同時是預設與 Esc 的那一顆。

    **不加 `&Y`／`&N` 助記鍵** —— 加了的話單按一個 Y 鍵就等於「是」。
    """
    parent = QWidget()
    qtbot.addWidget(parent)
    found: dict[str, Any] = {}

    def inspect(box: QMessageBox) -> None:
        yes = box.button(QMessageBox.StandardButton.Yes)
        no = box.button(QMessageBox.StandardButton.No)
        found.update(
            yes=yes.text(),
            no=no.text(),
            default_is_no=box.defaultButton() is no,
            escape_is_no=box.escapeButton() is no,
        )
        QTest.keyClick(box, Qt.Key.Key_Escape)

    seen = _answer_with(inspect)

    assert confirm(parent, "確認刪除", "確定要刪除嗎？") is False, "Esc 要是否"
    assert seen, "對話框沒有出現"
    assert (found["yes"], found["no"]) == ("是", "否"), found
    assert found["default_is_no"] and found["escape_is_no"], found


def test_the_restore_confirmation_tells_the_truth_about_the_backup(
    window: Any, answer_confirmations: Any
) -> None:
    """「還原前先建立備份」**預設沒勾**，以前確認框卻一律說「還原前會先備份目前資料」。

    沒勾的時候要明講救不回來；勾了才說會先備份。兩種都要念出是哪一份。
    """
    page = window.system_settings.maintenance
    backup = Path(window.controller.create_backup())
    page.refresh()
    asked = answer_confirmations(False, False)

    assert page.protect_restore.isChecked() is False, "前提：預設是沒勾的"
    page._restore(backup)
    page.protect_restore.setChecked(True)
    page._restore(backup)

    assert len(asked) == 2, asked
    unprotected, protected = asked
    assert "救不回來" in unprotected and "先把目前的資料備份" not in unprotected, unprotected
    assert "先把目前的資料備份" in protected and "救不回來" not in protected, protected
    assert str(backup) in unprotected and str(backup) in protected, "要念出是哪一份"
