"""待確認：定期收支與定存到期產生的草稿，確認之後才成為交易。

## 這一頁回答什麼問題

**「有哪些草稿等我確認？」** ——就這一件。

以前這一頁上下兩張表（排程一張、定存一張）加六顆按鈕，於是「我還有幾件事要處理」
要自己把兩個數字加起來，按按鈕之前還得先想清楚哪三顆是對上面那張表的。**作者自己
後來也忘了這一頁是設計來做什麼的** —— 那不是記性問題，是那一頁沒有講出自己是誰。

現在是**一張表、三顆按鈕**：來源用一個欄位表示，確認與略過依來源分派。

## 空的時候整頁說明自己

沒有待確認項目時，表格與按鈕整組收起來，換成一段說明。空表格加三顆停用的按鈕
說不出任何事情；那段文字才是「這一頁是做什麼的」的答案。

## 兩個刻意不做的行為

1. **「產生到期項目」不常駐在按鈕列。** 啟動時本來就會產生一次，平常按它什麼都不會
   發生 —— 一顆按了沒反應的按鈕比沒有按鈕更糟。只有真的還有漏期時才浮出一行提示。
2. **「全部確認」不碰定存。** 定存的權威金額在存摺上，建議值只是試算；批次套用試算值
   等於替使用者決定了一個他沒看過的數字。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.domain.money import Money, MoneyError
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import (
    error_text,
    inbox_values,
    minor_text,
    result_message,
)
from tagcor_ledger.ui.widgets.forms import fill_combo, select_data
from tagcor_ledger.ui.widgets.layout import TABLE_WIDTH, page_layout
from tagcor_ledger.ui.widgets.table import (
    RowsModel,
    bind_selection,
    set_button_role,
    setup_table,
)

EMPTY_MESSAGE = (
    "目前沒有待確認項目。\n\n"
    "定期收支（訂閱、房租）與定存到期會在這裡產生草稿，你確認之後才會變成交易。\n"
    "程式不會自己記帳。\n\n"
    "要新增定期收支：操作設定 → 定期收支"
)
"""空狀態的文字。**這一段就是「這一頁是做什麼的」的答案**，不要簡化成「沒有資料」。"""

BAD_AMOUNT_TEXT = "金額只能填數字，不要加逗號、單位或空白。"
"""`MoneyError` 翻不出來時的退路。認得出來的碼（負數、要大於 0）由
`error_text()` 從 `application/failures.py` 那張表取，兩邊講的話才會一致。"""


class InboxPage(QWidget):
    changed = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.table = QTableView()
        self.model = RowsModel(
            ["到期日", "來源", "名稱", "類型", "金額（TWD）", "狀態說明"],
            inbox_values,
            amount_column=4,
        )
        self.empty = QLabel(EMPTY_MESSAGE)
        self.more_hint = QLabel()
        self.more_button = QPushButton("繼續產生")
        self._build()
        self.refresh()

    def _build(self) -> None:
        title = QLabel("待確認")
        title.setObjectName("pageTitle")
        self.confirm_button = QPushButton("確認入帳")
        self.skip_button = QPushButton("略過")
        self.confirm_all_button = QPushButton("全部確認")
        set_button_role(self.confirm_button, "primary")
        set_button_role(self.confirm_all_button, "primary")

        actions = QHBoxLayout()
        for button in (self.confirm_button, self.skip_button):
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(self.confirm_all_button)

        # 「還有更多漏期」是例外狀況，所以是行內提示而不是常駐按鈕。
        self.more_hint.setObjectName("hintLabel")
        more_row = QHBoxLayout()
        more_row.addWidget(self.more_hint)
        more_row.addStretch()
        more_row.addWidget(self.more_button)

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

        setup_table(self.table, self.model, stretch_column=5)
        # 確認與略過是對所選那一列動作 —— 沒選就停用，不要按了沒反應。
        bind_selection(self.table, self.confirm_button, self.skip_button)

        layout = page_layout(self, width=TABLE_WIDTH)
        layout.addWidget(title)
        layout.addLayout(actions)
        layout.addLayout(more_row)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.empty, 1)

        self.confirm_button.clicked.connect(self.confirm_selected)
        self.skip_button.clicked.connect(self.skip_selected)
        self.confirm_all_button.clicked.connect(self.confirm_all)
        self.more_button.clicked.connect(self.generate_more)

    # --- 畫面狀態 ---------------------------------------------------------------

    def refresh(self) -> None:
        rows = self.controller.list_inbox()
        self.model.replace_rows(rows)
        self._apply_empty_state(bool(rows))
        self._apply_more_state()
        self.changed.emit()

    def _apply_empty_state(self, has_rows: bool) -> None:
        """空的時候把整組操作收起來，換成說明。

        留一張空表格加三顆停用的按鈕說不出任何事情 —— 使用者只會看到「這裡什麼都沒有」，
        而不知道這一頁本來會有什麼。
        """
        self.table.setVisible(has_rows)
        self.empty.setVisible(not has_rows)
        for button in (self.confirm_button, self.skip_button, self.confirm_all_button):
            button.setVisible(has_rows)

    def _apply_more_state(self) -> None:
        has_more = bool(self.controller.generation_has_more)
        if has_more:
            self.more_hint.setText(
                "還有更早的漏期沒有產生（一次只補一批，避免一口氣冒出上百筆）。"
            )
        self.more_hint.setVisible(has_more)
        self.more_button.setVisible(has_more)

    # --- 動作 -------------------------------------------------------------------

    def confirm_selected(self) -> None:
        """依來源分派：定期收支開修改對話框，定存問實際金額。

        **分派錯了不會有任何錯誤訊息**，只會開錯一個視窗 —— 所以有一條測試守著。
        """
        item = self.model.selected_item(self.table)
        if item is None:
            return
        if str(item["source"]) == "deposit":
            self._confirm_deposit(item)
            return
        dialog = InboxEditDialog(self.controller, item, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _confirm_deposit(self, item: dict[str, Any]) -> None:
        suggested = item.get("suggested_amount_minor")
        text, accepted = QInputDialog.getText(
            self,
            "確認定存項目",
            "實際金額（TWD）—— 以存摺為準，建議值只是試算：",
            text=minor_text(suggested) if suggested is not None else "",
        )
        if not accepted:
            return
        try:
            amount = Money.from_decimal_string(text.strip(), allow_zero=True).amount_minor
        except MoneyError as exc:
            QMessageBox.warning(
                self, "金額無效", error_text(exc, fallback=BAD_AMOUNT_TEXT)
            )
            return
        result = self.controller.confirm_deposit_event(
            str(item["event_id"]), actual_amount_minor=amount
        )
        if not result.success:
            QMessageBox.warning(self, "無法確認", result_message(result))
            return
        self.refresh()

    def skip_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None:
            return
        if str(item["source"]) == "deposit":
            result = self.controller.skip_deposit_event(str(item["event_id"]))
        else:
            result = self.controller.skip_occurrence(str(item["occurrence_id"]))
        if not result.success:
            QMessageBox.warning(self, "無法略過", result_message(result))
            return
        self.refresh()

    def confirm_all(self) -> None:
        """批次確認**只處理定期收支**。

        定存的權威金額在存摺上，建議值只是試算 —— 批次套用試算值等於替使用者決定了
        一個他沒看過的數字。所以訊息要講清楚剩下幾件定存還在，不要讓人以為漏了。
        """
        deposits = sum(
            1 for item in self.controller.list_inbox() if item["source"] == "deposit"
        )
        result = self.controller.batch_confirm_valid()
        message = (
            f"已入帳 {result.details.get('confirmed', 0)} 筆，"
            f"略過無效或失敗 {result.details.get('failed', 0)} 筆。"
        )
        if deposits:
            message += (
                f"\n\n另有 {deposits} 件定存項目沒有一起確認 —— "
                "它們的金額要照存摺輸入，請逐一按「確認入帳」。"
            )
        QMessageBox.information(self, "全部確認完成", message)
        self.refresh()

    def generate_more(self) -> None:
        result = self.controller.generate_due()
        if not result.success:
            QMessageBox.warning(self, "產生失敗", result_message(result))
            return
        QMessageBox.information(
            self,
            "產生完成",
            f"已產生 {int(result.details.get('generated', 0))} 期。",
        )
        self.refresh()


class InboxEditDialog(QDialog):
    def __init__(
        self,
        controller: LedgerController,
        item: dict[str, Any],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.item = item
        self.account = QComboBox()
        self.destination = QComboBox()
        self.category = QComboBox()
        self.detail = QComboBox()
        self.amount = QLineEdit(
            minor_text(item["amount_minor"]) if item.get("amount_minor") is not None else ""
        )
        self.description = QLineEdit(str(item["description"]))
        self.error = QLabel()
        self._build()
        self._load()

    def _build(self) -> None:
        self.setWindowTitle("確認入帳（可先修改）")
        form = QFormLayout()
        form.addRow("帳戶", self.account)
        if self.item["entry_type"] == "transfer":
            form.addRow("轉入帳戶", self.destination)
        else:
            form.addRow("類別", self.category)
            form.addRow("項目", self.detail)
        form.addRow("金額（TWD）", self.amount)
        form.addRow("備註", self.description)
        form.addRow("", self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("儲存並確認入帳")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.category.currentIndexChanged.connect(self._reload_details)

    def _load(self) -> None:
        accounts = self.controller.account_options()
        fill_combo(self.account, accounts, "name", "account_id")
        fill_combo(self.destination, accounts, "name", "account_id")
        select_data(self.account, self.item["account_id"])
        select_data(self.destination, self.item.get("destination_account_id"))
        if self.item["entry_type"] != "transfer":
            fill_combo(
                self.category,
                self.controller.category_options(),
                "name",
                "category_id",
            )
            for index in range(self.category.count()):
                parent_id = str(self.category.itemData(index))
                children = self.controller.category_options(parent_id)
                if any(
                    str(child["category_id"]) == self.item.get("category_id")
                    for child in children
                ):
                    self.category.setCurrentIndex(index)
                    break
            self._reload_details()
            select_data(self.detail, self.item.get("category_id"))

    def _reload_details(self) -> None:
        parent_id = self.category.currentData()
        children = (
            self.controller.category_options(str(parent_id))
            if isinstance(parent_id, str)
            else []
        )
        fill_combo(self.detail, children, "name", "category_id")

    def save(self) -> None:
        try:
            amount_minor = Money.from_decimal_string(self.amount.text().strip()).amount_minor
        except MoneyError as exc:
            self.error.setText(error_text(exc, fallback=BAD_AMOUNT_TEXT))
            return
        result = self.controller.update_occurrence(
            str(self.item["occurrence_id"]),
            amount_minor=amount_minor,
            account_id=str(self.account.currentData()),
            destination_account_id=(
                str(self.destination.currentData())
                if self.item["entry_type"] == "transfer"
                else None
            ),
            category_id=(
                str(self.detail.currentData())
                if self.item["entry_type"] != "transfer"
                else None
            ),
            description=self.description.text().strip(),
        )
        if not result.success:
            self.error.setText(result_message(result))
            return
        confirmed = self.controller.confirm_occurrence(str(self.item["occurrence_id"]))
        if confirmed.success:
            self.accept()
        else:
            self.error.setText(result_message(confirmed))
