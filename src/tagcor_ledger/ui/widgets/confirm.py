"""「確定嗎？」對話框。**畫面上每一個確認框都走這裡。**

## 預設按鈕一律是「否」

`QMessageBox.question()` 不指定預設按鈕時，Qt 不會替你挑「否」：「是」的角色是 `YesRole`、
不是 `AcceptRole`，於是沒有任何按鈕被設成預設，焦點落在排第一個的「是」上 —— 2026-10-09
實測：對話框一出來按 Enter，回傳的就是「是」。而這種對話框最常見的誤觸，正是順手按 Enter。

以前只有「重製」與「刪除備份」兩處記得指定「否」：這條規則寫在 `reset.py` 一處的 docstring 裡，
另外六個確認框（交易、盤點、名冊、模板、定存合約、還原）都沒跟上。**規則只寫在一個呼叫端，
就只保護得到那一個呼叫端。** 所以它現在住在這個函式裡，`tests/unit/test_architecture.py`
擋住直接呼叫 `QMessageBox.question`。

## 按鈕寫「是」「否」，所以自己建對話框

靜態的 `question()` 用的是 Qt 的標準按鈕文字，而這個程式沒有載入 Qt 自己的翻譯 ——
全中文的確認框底下是英文的「Yes／No」（2026-10-09 截圖時發現，從第一天就這樣）。
靜態函式改不了按鈕上的字，所以這裡自己建 `QMessageBox`：標準按鈕照用（Enter、Esc、
回傳值都照 Qt 的規則走），只換掉上面的字。**刻意不加 `&Y`／`&N` 助記鍵**：
加了的話單按一個 Y 鍵就等於按「是」，那正是預設「否」想擋掉的那種順手。

測試攔的是 `QMessageBox.exec`（`tests/ui/conftest.py` 的 `dialog_stub` 與 `answer_confirmations`），
不是 `question` —— 這裡已經不呼叫它了。提示框（只有一顆「確定」）在 `notice.py`，同一個做法。
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

YES_TEXT = "是"
NO_TEXT = "否"


def confirm(parent: QWidget, title: str, text: str) -> bool:
    """問一次「確定嗎？」。**只有按了「是」才回傳 True** —— Enter、Esc、關掉視窗都是否。

    `text` 要講出**要動的是哪一個**與**之後救不救得回來**；只問「確定嗎」的確認框，
    使用者按下去的時候並不知道自己在確定什麼。
    """
    box = QMessageBox(
        QMessageBox.Icon.Question,
        title,
        text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        parent,
    )
    box.button(QMessageBox.StandardButton.Yes).setText(YES_TEXT)
    box.button(QMessageBox.StandardButton.No).setText(NO_TEXT)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    box.setEscapeButton(QMessageBox.StandardButton.No)
    return QMessageBox.StandardButton(box.exec()) == QMessageBox.StandardButton.Yes
