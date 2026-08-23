"""資產總覽：開啟程式第一眼看到的那一頁。

## 這一頁回答什麼問題

**「我現在總共有多少錢，還有什麼事沒處理？」** ——就這兩件。它刻意不提供任何操作，
只有兩顆把你送到能處理的地方的按鈕。會在這裡做的事，就不該在這裡做。

## 三個容易做錯的決定

1. **總資產只加總「使用中」帳戶。** 封存的意思是不出現在選單，**不是錢消失了**。
   所以封存帳戶若還有餘額，另外列一行講清楚 —— 否則使用者拿這個數字去對存摺會對不起來。
2. **每次切到這一頁就重新整理。** 不在 `main_window` 的每個 `_..._changed` 各記一筆：
   那種清單一定會漏掉一項，而漏掉的症狀是「總資產停在舊的數字」—— 一個看起來像算錯帳
   的 bug。切頁重算是 O(帳戶數)，不值得為了省它而冒這個險。
3. **提醒放在頁面上，不放狀態列。** 盤點提醒本來是一則 10 秒就消失的狀態列訊息，
   使用者去泡杯茶回來它就不在了。

## 帳戶表右邊的占比圓環

表格回答「每個帳戶有多少」，圓環回答「比重長什麼樣」—— 同一份資料的兩種讀法，
所以並排而不是上下。規則都在 `widgets/asset_share.py`，這一頁只負責擺位置與
把「有負餘額帳戶」那一句話寫出來。

**負餘額不進圓環。** 圓餅圖對負值沒有定義，用絕對值畫則會讓一個把錢吃掉的帳戶
看起來像一份資產。所以那些帳戶另外用一行字交代 —— 與封存帳戶那一行同一個做法：
**不算進去，但也不默默不提。**
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableView,
    QWidget,
)

from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import display_date, group_digits, overview_account_values
from tagcor_ledger.ui.widgets.asset_share import AssetShareChart
from tagcor_ledger.ui.widgets.layout import SUMMARY_WIDTH, page_layout
from tagcor_ledger.ui.widgets.table import RowsModel, setup_table

MAX_ACCOUNT_ROWS = 12
"""帳戶表最多長到幾列。再多就讓它自己捲，不要把定存與待辦推出畫面。"""


class OverviewPage(QWidget):
    inbox_requested = Signal()
    balance_requested = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.total = QLabel("0")
        self.archived_note = QLabel()
        self.negative_note = QLabel()
        self.deposit_note = QLabel()
        self.gap_note = QLabel()
        self.inbox_note = QLabel()
        self.snapshot_note = QLabel()
        self.inbox_button = QPushButton("去處理")
        self.snapshot_button = QPushButton("去盤點")
        self.table = QTableView()
        self.model = RowsModel(
            ["帳戶", "目前餘額（TWD）"],
            overview_account_values,
            amount_column=1,
        )
        self.chart = AssetShareChart()
        self._build()
        self.refresh()

    def _build(self) -> None:
        title = QLabel("資產總覽")
        title.setObjectName("pageTitle")
        total_caption = QLabel("總資產（TWD）")
        total_caption.setObjectName("sectionTitle")
        self.total.setObjectName("totalAmount")
        for label in (
            self.archived_note,
            self.negative_note,
            self.deposit_note,
            self.gap_note,
        ):
            label.setObjectName("hintLabel")
            label.setWordWrap(True)

        # 高度也收到列數：三個帳戶不該佔滿一整塊高度再留一片空白框。
        # 上限 12 是為了不讓帳戶一多就把底下的定存與待辦推出畫面。
        setup_table(self.table, self.model, fit_content=True, fit_rows=MAX_ACCOUNT_ROWS)

        layout = page_layout(self, width=SUMMARY_WIDTH)
        layout.addWidget(title)
        layout.addWidget(total_caption)
        layout.addWidget(self.total)
        layout.addWidget(self.archived_note)

        self.accounts_caption = QLabel("帳戶")
        self.accounts_caption.setObjectName("sectionTitle")
        layout.addWidget(self.accounts_caption)
        layout.addLayout(self._accounts_row())
        layout.addWidget(self.negative_note)

        self.deposit_caption = QLabel("定存")
        self.deposit_caption.setObjectName("sectionTitle")
        layout.addWidget(self.deposit_caption)
        layout.addWidget(self.deposit_note)

        todo_caption = QLabel("待辦")
        todo_caption.setObjectName("sectionTitle")
        layout.addWidget(todo_caption)
        layout.addLayout(self._action_row(self.inbox_note, self.inbox_button))
        layout.addLayout(self._action_row(self.snapshot_note, self.snapshot_button))
        layout.addWidget(self.gap_note)
        layout.addStretch()

        self.inbox_button.clicked.connect(lambda: self.inbox_requested.emit())
        self.snapshot_button.clicked.connect(lambda: self.balance_requested.emit())

    def _accounts_row(self) -> QHBoxLayout:
        """表格在左、占比圓環在右，兩邊都靠上對齊。

        表格已經是 `fit_content=True`（寬度收到欄寬總和）也是 `fit_rows`（高度收到
        列數），所以它不會去搶圓環的空間；靠上對齊是因為兩者高度本來就不一樣 ——
        置中會讓只有兩三個帳戶的時候表格浮在圓環中間。

        頁寬上限是 `SUMMARY_WIDTH` 980：表格約 330、圓環 200、圖例約 320，裝得下。
        """
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.table, 0, Qt.AlignmentFlag.AlignTop)
        row.addSpacing(24)
        # **兩個都不吃剩餘寬度**，多的由這裡的 stretch 收掉。給圓環 stretch 的話
        # 圖例會被拉開，金額與占比跑到頁面最右邊，與名稱之間隔一整片空白。
        row.addWidget(self.chart, 0, Qt.AlignmentFlag.AlignTop)
        row.addStretch()
        return row

    @staticmethod
    def _action_row(label: QLabel, button: QPushButton) -> QHBoxLayout:
        """一句話配一顆按鈕，按鈕靠右對齊成一直行。

        **這裡不能開 `setWordWrap`。** 旁邊有 stretch 時，QLabel 拿到的是它的
        `sizeHint` 寬度，而會換行的 QLabel 的 sizeHint 是一個「大致方形」的啟發值 ——
        於是「今天還沒記錄「現金」的目前金額。」在還有 700 px 空白的情況下斷成兩行
        （2026-08-20 實機截圖）。這兩行本來就只有一句話，不需要換行。
        """
        label.setWordWrap(False)
        row = QHBoxLayout()
        row.addWidget(label)
        row.addStretch()
        row.addWidget(button)
        return row

    def refresh(self) -> None:
        snapshot = self.controller.overview_snapshot()
        self.total.setText(group_digits(int(snapshot["total_minor"])))
        self.model.replace_rows(list(snapshot["accounts"]))
        self._show_chart(list(snapshot["accounts"]))
        self._show_archived(list(snapshot["archived_with_balance"]))
        self._show_deposit(snapshot["deposit"])
        self._show_inbox(int(snapshot["inbox_count"]))
        self._show_snapshot_due(snapshot["snapshot_due_account"])
        self._show_gap(snapshot["latest_gap"])

    def _show_chart(self, accounts: list[dict[str, Any]]) -> None:
        """畫圓環，並把「有帳戶餘額是負的」寫成一句話。

        **一片都畫不出來就整段收起來**（全新的帳本、或所有帳戶都是 0）——
        一個空的圓框看起來像壞掉或還沒載入，與「沒有定存合約就不顯示定存」同一條。

        負餘額那一句沿用封存帳戶那一句的句型：講出是哪幾個、多少錢、為什麼不在圖裡。
        分母不同這件事由 `AssetShareChart` 自己在圖例下方補一行 —— 那句話屬於圖，
        不屬於頁面。
        """
        breakdown = self.chart.set_accounts(accounts)
        self.chart.setVisible(bool(breakdown.shares))
        if not breakdown.negative:
            self.negative_note.setVisible(False)
            return
        total = sum(int(item["balance_minor"]) for item in breakdown.negative)
        names = "、".join(str(item["name"]) for item in breakdown.negative)
        self.negative_note.setText(
            f"另有餘額為負的帳戶（{names}）合計 {group_digits(total)} TWD，"
            "沒有畫進上面的占比圖 —— 圓餅對負數沒有意義。它已經算進總資產了。"
        )
        self.negative_note.setVisible(True)

    def _show_archived(self, archived: list[dict[str, Any]]) -> None:
        if not archived:
            self.archived_note.setVisible(False)
            return
        total = sum(int(item["balance_minor"]) for item in archived)
        names = "、".join(str(item["name"]) for item in archived)
        self.archived_note.setText(
            f"另有已封存的帳戶（{names}）餘額合計 {group_digits(total)} TWD，"
            "沒有算進總資產。封存只是不再出現在選單裡。"
        )
        self.archived_note.setVisible(True)

    def _show_deposit(self, deposit: object) -> None:
        """沒有定存合約時整段不顯示 —— 空的區塊會讓人以為是壞掉或還沒載入。"""
        if not isinstance(deposit, dict):
            self.deposit_caption.setVisible(False)
            self.deposit_note.setVisible(False)
            return
        text = (
            f"{deposit['contract_name']}："
            f"{display_date(str(deposit['maturity_date']))} 到期，"
            f"本金 {group_digits(int(deposit['principal_minor']))} TWD。"
        )
        if int(deposit["contract_count"]) > 1:
            text += (
                f"（存續中共 {deposit['contract_count']} 期，"
                f"本金合計 {group_digits(int(deposit['total_principal_minor']))} TWD）"
            )
        self.deposit_note.setText(text)
        self.deposit_caption.setVisible(True)
        self.deposit_note.setVisible(True)

    def _show_inbox(self, count: int) -> None:
        if count:
            self.inbox_note.setText(f"待確認 {count} 筆。")
            self.inbox_button.setVisible(True)
        else:
            self.inbox_note.setText("沒有待確認項目。")
            self.inbox_button.setVisible(False)

    def _show_snapshot_due(self, account_name: object) -> None:
        if isinstance(account_name, str):
            self.snapshot_note.setText(f"今天還沒記錄「{account_name}」的目前金額。")
            self.snapshot_note.setVisible(True)
            self.snapshot_button.setVisible(True)
            return
        self.snapshot_note.setVisible(False)
        self.snapshot_button.setVisible(False)

    def _show_gap(self, gap: object) -> None:
        """未解釋差額為 0 就不顯示。**「差額 0」不是待辦事項。**"""
        if not isinstance(gap, dict) or int(gap["difference_minor"]) == 0:
            self.gap_note.setVisible(False)
            return
        self.gap_note.setText(
            f"最近一次盤點（{gap['account_name']}，"
            f"{display_date(str(gap['observed_at']))}）"
            f"未解釋差額 {gap['difference']} TWD，可到「餘額盤點」補記交易。"
        )
        self.gap_note.setVisible(True)
