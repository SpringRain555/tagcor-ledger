"""待確認：定存到期與領息產生的草稿，確認之後才成為交易。

## 這一頁回答什麼問題

**「有哪些草稿等我確認？」** ——就這一件。

## 它以前有兩個來源

v0.23.0 之前定期收支與定存都往這裡丟草稿，所以每一列帶一個 `source`，還多一欄
「來源」告訴使用者那一列的「類型」該怎麼讀（一邊是收入／支出／轉帳，一邊是到期／
領息／存入）。定期收支移除之後
（[ADR-0011](../../../../docs/decisions/ADR-0011-drop-recurring-schedules.md)）
只剩定存，跟著一起消失的有：

| 消失的東西 | 為什麼它是定期收支獨有的 |
|---|---|
| 「來源」欄 | 只剩一種來源，每一列印同一個字 |
| 「全部確認」 | `batch_confirm_valid()` 只處理定期收支。**定存刻意不批次** —— 權威金額在存摺上，批次套用試算值等於替使用者決定一個他沒看過的數字 |
| 「繼續產生」與漏期提示 | 「一次最多 366 期」是排程獨有的上限。定存只看未來 7 天，一次做完而且冪等 |
| `InboxEditDialog` | 它編的是 `scheduled_occurrences`。定存只問一個實際金額 |

**「待確認」這個名字沒有跟著改。** 它問的是「有哪些草稿等我確認」，今天剛好只由
定存供應 —— 換成「定存到期」就等於把頁面的身分綁在目前唯一的來源上。

## 空的時候整頁說明自己

沒有待確認項目時，表格與按鈕整組收起來，換成一段說明。空表格加兩顆停用的按鈕
說不出任何事情；那段文字才是「這一頁是做什麼的」的答案。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableView,
    QWidget,
)

from tagcor_ledger.domain.money import Money, MoneyError
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import (
    deposit_event_values,
    error_text,
    minor_text,
    result_message,
)
from tagcor_ledger.ui.widgets.layout import TABLE_WIDTH, page_layout
from tagcor_ledger.ui.widgets.simple_form import DateField, TextField, ask_form
from tagcor_ledger.ui.widgets.table import (
    RowsModel,
    bind_selection,
    set_button_role,
    setup_table,
)

EMPTY_MESSAGE = (
    "目前沒有待確認項目。\n\n"
    "定存到期與每月領息會在這裡產生草稿，你確認之後才會變成交易。\n"
    "程式不會自己記帳。\n\n"
    "要新增定存合約：操作設定 → 定存"
)
"""空狀態的文字。**這一段就是「這一頁是做什麼的」的答案**，不要簡化成「沒有資料」。"""

AMOUNT_HINT = "金額一律以存摺為準 —— 表格上的建議值只是程式試算。"
"""表格上方那一行。

**以前這句話是每一列的「狀態說明」欄**，而它對每一列都一模一樣 —— 依
`formatting/rows.py` 自己的規則（見 `account_values`：每列同值就是雜訊）
應該只講一次。講在上面而不是整句拿掉，是因為它是這一頁最重要的一條規則。
"""

BAD_AMOUNT_TEXT = "金額只能填數字，不要加逗號、單位或空白。"
"""`MoneyError` 翻不出來時的退路。認得出來的碼（負數、要大於 0）由
`error_text()` 從 `application/failures.py` 那張表取，兩邊講的話才會一致。"""


class InboxPage(QWidget):
    changed = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.table = QTableView()
        # **用 `deposit_event_values`，不另外寫一個 `inbox_values`。**
        # v0.23.0 之前 `inbox_values()` 要處理兩種來源，所以它與定存自己的
        # formatter 是兩份；只剩定存之後兩者一字不差 —— 留兩份就是「同一筆資料
        # 在兩個地方被拼成兩種樣子」的起點。
        self.model = RowsModel(
            ["到期日", "定存合約", "類型", "建議金額（TWD）"],
            deposit_event_values,
            amount_column=3,
        )
        self.empty = QLabel(EMPTY_MESSAGE)
        self.hint = QLabel(AMOUNT_HINT)
        self._build()
        self.refresh()

    def _build(self) -> None:
        title = QLabel("待確認")
        title.setObjectName("pageTitle")
        self.confirm_button = QPushButton("確認入帳")
        self.skip_button = QPushButton("略過")
        set_button_role(self.confirm_button, "primary")

        actions = QHBoxLayout()
        for button in (self.confirm_button, self.skip_button):
            actions.addWidget(button)
        actions.addStretch()

        self.hint.setObjectName("hintLabel")
        self.empty.setObjectName("hintLabel")
        self.empty.setWordWrap(True)
        # 說明文字靠上，但**佔滿剩下的高度** —— 它與表格互為替身，兩者都給 stretch 1，
        # 藏起來的那一個把空間讓給另一個。沒有這個安排的話：留一個 `addStretch()`
        # 會讓表格停在 QTableView 那個沒有意義的預設 sizeHint（約 600 px，底下一片空框），
        # 拿掉 `addStretch()` 又會讓空狀態的那段字被拉到頁面中央。
        self.empty.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self.empty.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        # **四欄用 `fit_content` 收寬，不指定 stretch_column。** 以前是六欄，最後一欄
        # 「狀態說明」吃掉多餘寬度剛好；只剩四欄之後那個 stretch 會在「定存合約」與
        # 「類型」之間拉開一大片空白（2026-08-23 實機截圖）。AGENTS.md 的規則本來
        # 就是「欄位少的表格收到欄寬總和」。
        setup_table(self.table, self.model, fit_content=True)
        # 確認與略過是對所選那一列動作 —— 沒選就停用，不要按了沒反應。
        bind_selection(self.table, self.confirm_button, self.skip_button)

        layout = page_layout(self, width=TABLE_WIDTH)
        layout.addWidget(title)
        layout.addLayout(actions)
        layout.addWidget(self.hint)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.empty, 1)

        self.confirm_button.clicked.connect(self.confirm_selected)
        self.skip_button.clicked.connect(self.skip_selected)

    # --- 畫面狀態 ---------------------------------------------------------------

    def refresh(self) -> None:
        rows = self.controller.list_inbox()
        self.model.replace_rows(rows)
        self._apply_empty_state(bool(rows))
        self.changed.emit()

    def _apply_empty_state(self, has_rows: bool) -> None:
        """空的時候把整組操作收起來，換成說明。

        留一張空表格加兩顆停用的按鈕說不出任何事情 —— 使用者只會看到「這裡什麼都
        沒有」，而不知道這一頁本來會有什麼。
        """
        self.table.setVisible(has_rows)
        self.hint.setVisible(has_rows)
        self.empty.setVisible(not has_rows)
        for button in (self.confirm_button, self.skip_button):
            button.setVisible(has_rows)

    # --- 動作 -------------------------------------------------------------------

    def confirm_selected(self) -> None:
        """只問日期與實際金額。

        **不開一張可以改帳戶與類別的表單。** 定存事件的帳戶、流向與類別都是合約
        當初就決定好的（三種計息方式 × 四種到期及轉存方式），在確認的當下改它們等於
        改一份已經生效的合約 —— 那件事要去「操作設定 → 定存」做。

        **日期欄預設到期日，不是今天。** 到期項目提前七天出現（`MATURITY_LEAD_DAYS`），
        所以「按確認的那一天」跟錢真的動的那一天差得出來 —— v0.24.0 之前交易日期
        寫死成今天，照著提示馬上確認就會早七天。銀行晚一兩天入帳時可以自己改。
        """
        item: dict[str, Any] | None = self.model.selected_item(self.table)
        if item is None:
            return
        suggested = item.get("suggested_amount_minor")
        values = ask_form(
            self,
            "確認定存項目",
            [
                DateField("occurred_on", "入帳日期", default=str(item["due_date"])),
                TextField(
                    "amount",
                    "實際金額（TWD）",
                    default=minor_text(suggested) if suggested is not None else "",
                    placeholder="以存摺為準，建議值只是試算",
                ),
            ],
        )
        if values is None:
            return
        try:
            amount = Money.from_decimal_string(
                str(values["amount"]), allow_zero=True
            ).amount_minor
        except MoneyError as exc:
            QMessageBox.warning(
                self, "金額無效", error_text(exc, fallback=BAD_AMOUNT_TEXT)
            )
            return
        result = self.controller.confirm_deposit_event(
            str(item["event_id"]),
            actual_amount_minor=amount,
            occurred_on=str(values["occurred_on"]),
        )
        if not result.success:
            QMessageBox.warning(self, "無法確認", result_message(result))
            return
        self.refresh()

    def skip_selected(self) -> None:
        """略過 =「我看過，這一期不記」。**到期項目會被擋下來**（見 `deposits/postings.py`）。"""
        item: dict[str, Any] | None = self.model.selected_item(self.table)
        if item is None:
            return
        result = self.controller.skip_deposit_event(str(item["event_id"]))
        if not result.success:
            QMessageBox.warning(self, "無法略過", result_message(result))
            return
        self.refresh()
