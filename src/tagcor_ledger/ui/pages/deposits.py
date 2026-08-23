"""定存：合約與每一期。

這一頁只管**記錄與檢視**。到期要做什麼一律走「待確認」頁 —— 定存不會有自己的入帳按鈕，
否則就會出現兩個地方都能入帳、兩邊行為還不一樣的老問題。

**中途解約是唯一的例外，而它不是「到期」。** 提前解約沒有到期事件可以確認（那一期
根本還沒到期），金額也不是程式算得出來的 —— 那條路只能從這裡走。

「修改所選期」是**查到牌告利率之後回來補**的路徑。go-live runbook 叫使用者先留空利率，
沒有這顆按鈕那句話就是做不到的。

## 三顆按鈕的界線

| | 動到錢嗎 | 什麼時候用 |
|---|---|---|
| **結束合約** | 不 | 這份定存已經沒有存續中的期了（到期結清過），只是還掛在清單上 |
| **中途解約** | 會 | 還在存續中就要提前解約，錢當場回到指定帳戶 |
| **刪除所選合約** | 不 | **記錯了**。只有從未入帳過的才刪得掉 |

對話框在 `ui/widgets/deposit_dialog.py`。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.domain.deposits import DepositTermStatus
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import (
    deposit_contract_values,
    deposit_term_values,
    result_message,
)
from tagcor_ledger.ui.widgets.deposit_dialog import (
    DepositContractDialog,
    DepositTermDialog,
    TerminateTermDialog,
)
from tagcor_ledger.ui.widgets.table import (
    SETTINGS_TABLE_ROWS,
    RowsModel,
    bind_selection,
    set_button_role,
    setup_table,
)


class DepositsPage(QWidget):
    changed = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.contracts = QTableView()
        self.contract_model = RowsModel(
            [
                "名稱",
                "帳戶",
                "計息方式",
                "到期及轉存方式",
                "利率類型",
                "期長",
                "首次起存日",
                "狀態",
            ],
            deposit_contract_values,
        )
        self.terms = QTableView()
        self.term_model = RowsModel(
            ["期", "起存日", "到期日", "本金（TWD）", "年利率", "實際利息", "狀態"],
            deposit_term_values,
            amount_column=3,
        )
        self.show_closed = QCheckBox("顯示已結束的合約")
        self._build()
        self.refresh()

    def _build(self) -> None:
        hint = QLabel(
            "定存到期與每月領息都只會產生「待確認」項目，程式不會自動入帳 —— "
            "確認之後才會變成交易。機動利率請把年利率留空，到期照存摺輸入實際利息即可，"
            "程式會反推出這一期實際的年利率。\n"
            # **QLabel 不吃 markdown。** 這段字第一版寫成 `**…**`，實機截圖上印出來的
            # 就是兩個星號（2026-08-23）。要強調只能靠斷句與位置。
            "建檔之前就到期的期數不會產生待確認項目，那段歷史已經含在帳戶的期初餘額裡。"
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)

        add_button = QPushButton("新增定存合約")
        edit_button = QPushButton("修改所選合約")
        self.close_button = QPushButton("結束合約")
        delete_button = QPushButton("刪除所選合約")
        refresh_button = QPushButton("重新整理")
        self.generate_button = QPushButton("產生到期與領息項目")
        set_button_role(add_button, "primary")
        set_button_role(self.generate_button, "primary")
        set_button_role(delete_button, "danger")
        row = QHBoxLayout()
        for widget in (
            add_button,
            edit_button,
            self.close_button,
            delete_button,
            self.generate_button,
            refresh_button,
        ):
            row.addWidget(widget)
        row.addStretch()

        edit_term_button = QPushButton("修改所選期（補利率用）")
        self.terminate_button = QPushButton("中途解約")
        set_button_role(edit_term_button, "primary")
        # **中途解約不是 danger。** 紅色在這個程式裡留給不可逆的破壞（刪除）；
        # 解約會產生交易，而交易作廢得掉。
        term_row = QHBoxLayout()
        term_row.addWidget(edit_term_button)
        term_row.addWidget(self.terminate_button)
        term_row.addStretch()

        setup_table(self.contracts, self.contract_model, fit_content=True, fit_rows=SETTINGS_TABLE_ROWS)
        setup_table(self.terms, self.term_model, fit_content=True, fit_rows=SETTINGS_TABLE_ROWS)
        bind_selection(self.contracts, edit_button, self.close_button, delete_button)
        bind_selection(self.terms, edit_term_button, self.terminate_button)

        contracts_title = QLabel("合約")
        contracts_title.setObjectName("sectionTitle")
        terms_title = QLabel("每一期（續存會產生新的一期，舊的不會被改寫）")
        terms_title.setObjectName("sectionTitle")
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(row)
        layout.addWidget(contracts_title)
        layout.addWidget(self.show_closed)
        layout.addWidget(self.contracts)
        layout.addWidget(terms_title)
        layout.addLayout(term_row)
        layout.addWidget(self.terms)
        # 表格現在是固定高度（`fit_rows`），沒有這一行的話 QVBoxLayout 會把多餘的
        # 高度平均塞進每個 widget 之間 —— 按鈕與表格會浮在分頁中間。
        layout.addStretch()

        add_button.clicked.connect(self.add_contract)
        edit_button.clicked.connect(self.edit_contract)
        self.close_button.clicked.connect(self.close_contract)
        delete_button.clicked.connect(self.delete_contract)
        refresh_button.clicked.connect(self.refresh)
        self.generate_button.clicked.connect(self.generate_events)
        edit_term_button.clicked.connect(self.edit_term)
        self.terminate_button.clicked.connect(self.terminate_term)
        self.show_closed.toggled.connect(lambda *_: self.refresh())
        self.contracts.selectionModel().selectionChanged.connect(lambda *_: self.reload_terms())

    def generate_events(self) -> None:
        """把到期與領息放進待確認。**只產生草稿，不建立任何交易。**

        啟動時本來就會跑一次，所以這顆按鈕平常按下去不會多出東西 —— 它是給
        「程式開著的時候剛建了一份合約」用的。重複按沒有副作用（`deposit_events`
        有 `UNIQUE (term_id, event_type, due_date)`），所以不必先問「還有幾件」。
        """
        result = self.controller.generate_deposit_events()
        if not result.success:
            QMessageBox.warning(self, "產生失敗", result_message(result))
            return
        QMessageBox.information(
            self,
            "產生完成",
            f"已產生 {int(result.details.get('generated', 0))} 件待確認項目。\n\n"
            "它們不會自動入帳 —— 到「待確認」按確認並照存摺輸入金額。",
        )
        self.changed.emit()

    def refresh(self) -> None:
        self.contract_model.replace_rows(
            self.controller.list_deposit_contracts(include_closed=self.show_closed.isChecked())
        )
        self.reload_terms()

    def reload_terms(self) -> None:
        selected = self.contract_model.selected_item(self.contracts)
        contract_id = str(selected["contract_id"]) if selected else None
        self.term_model.replace_rows(self.controller.list_deposit_terms(contract_id))

    def add_contract(self) -> None:
        dialog = DepositContractDialog(self.controller, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._finish(self.controller.create_deposit_contract(**dialog.values), "無法建立定存合約")

    def edit_contract(self) -> None:
        item = self.contract_model.selected_item(self.contracts)
        if item is None:
            return
        dialog = DepositContractDialog(self.controller, self, current=item)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._finish(
            self.controller.update_deposit_contract(
                str(item["contract_id"]),
                name=dialog.values["name"],
                maturity_action=dialog.values["maturity_action"],
                interest_destination_account_id=dialog.values[
                    "interest_destination_account_id"
                ],
                # **不傳 note。** 這個對話框沒有備註欄位，以前傳的
                # `dialog.values.get("note", "")` 讀的是它從不寫入的 key，
                # 看起來像有保留、實際上每次修改都把備註寫成空字串。
            ),
            "無法修改定存合約",
        )

    def close_contract(self) -> None:
        """結束一份定存關係。**不動任何錢。**

        `DEPOSIT_CONTRACT_IN_USE` 從 v0.9.0 就叫使用者「改用結束合約」，而這顆按鈕
        到 v0.24.0 才存在 —— 在那之前那句建議指向的是一件做不到的事。
        """
        item = self.contract_model.selected_item(self.contracts)
        if item is None:
            return
        answer = QMessageBox.question(
            self,
            "確認結束",
            f"要結束「{item['name']}」嗎？\n"
            "已經記過的交易與每一期的紀錄都留著，只是它不會再產生待確認項目，"
            "清單上也會收起來（勾「顯示已結束的合約」還看得到）。\n"
            "還有存續中的期時不能結束 —— 那種情況請用「中途解約」。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._finish(
            self.controller.close_deposit_contract(str(item["contract_id"])), "無法結束"
        )

    def delete_contract(self) -> None:
        item = self.contract_model.selected_item(self.contracts)
        if item is None:
            return
        answer = QMessageBox.question(
            self,
            "確認刪除",
            f"要刪除「{item['name']}」嗎？\n"
            "只有從未入帳過的定存可以刪除；已經有入帳紀錄的請改用「結束合約」。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._finish(
            self.controller.delete_deposit_contract(str(item["contract_id"])), "無法刪除"
        )

    def edit_term(self) -> None:
        item = self.term_model.selected_item(self.terms)
        if item is None:
            return
        dialog = DepositTermDialog(item, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._finish(
            self.controller.update_deposit_term(str(item["term_id"]), **dialog.values),
            "無法修改這一期",
        )

    def terminate_term(self) -> None:
        """提前解約。**這是這一頁唯一會產生交易的動作**，見模組說明。"""
        item = self.term_model.selected_item(self.terms)
        if item is None:
            return
        if str(item["status"]) != DepositTermStatus.ACTIVE:
            QMessageBox.warning(
                self,
                "無法解約",
                "只有「存續中」的期可以中途解約。這一期已經結清、續約或解約過了。",
            )
            return
        contract = self.contract_model.selected_item(self.contracts)
        name = str(contract["name"]) if contract else "這份定存"
        dialog = TerminateTermDialog(item, name, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._finish(
            self.controller.terminate_deposit_term(str(item["term_id"]), **dialog.values),
            "無法解約",
        )

    def _finish(self, result: Any, failure_title: str) -> None:
        if not result.success:
            QMessageBox.warning(self, failure_title, result_message(result))
            return
        self.refresh()
        self.changed.emit()
