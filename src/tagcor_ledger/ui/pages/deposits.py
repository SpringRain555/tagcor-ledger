"""定存：合約與每一期。

這一頁只管**記錄與檢視**。到期要做什麼一律走「待確認」頁 —— 定存不會有自己的入帳按鈕，
否則就會出現兩個地方都能入帳、兩邊行為還不一樣的老問題。

「修改所選期」是**查到牌告利率之後回來補**的路徑。go-live runbook 叫使用者先留空利率，
沒有這顆按鈕那句話就是做不到的。
"""

from __future__ import annotations

from decimal import InvalidOperation
from typing import Any

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.domain.deposits import (
    INTEREST_METHOD_NAMES,
    MATURITY_ACTION_NAMES,
    RATE_TYPE_NAMES,
    InterestMethod,
    MaturityAction,
    RateType,
    rate_to_ppm,
)
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import (
    deposit_contract_values,
    deposit_term_values,
    minor_text,
    rate_input_text,
    result_message,
)
from tagcor_ledger.ui.widgets.forms import date_field, fill_combo, select_data
from tagcor_ledger.ui.widgets.simple_form import TextField, ask_form
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
            ["名稱", "帳戶", "計息方式", "到期轉存方式", "利率類型", "期長", "狀態"],
            deposit_contract_values,
        )
        self.terms = QTableView()
        self.term_model = RowsModel(
            ["期", "起存日", "到期日", "本金（TWD）", "年利率", "實際利息", "狀態"],
            deposit_term_values,
            amount_column=3,
        )
        self._build()
        self.refresh()

    def _build(self) -> None:
        hint = QLabel(
            "定存到期與每月領息都只會產生「待確認」項目，程式不會自動入帳 —— "
            "確認之後才會變成交易。機動利率請把年利率留空，到期照存摺輸入實際利息即可，"
            "程式會反推出這一期實際的年利率。"
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)

        add_button = QPushButton("新增定存合約")
        edit_button = QPushButton("修改所選合約")
        delete_button = QPushButton("刪除所選合約")
        refresh_button = QPushButton("重新整理")
        set_button_role(add_button, "primary")
        set_button_role(delete_button, "danger")
        row = QHBoxLayout()
        for widget in (add_button, edit_button, delete_button, refresh_button):
            row.addWidget(widget)
        row.addStretch()

        edit_term_button = QPushButton("修改所選期（補利率用）")
        set_button_role(edit_term_button, "primary")
        term_row = QHBoxLayout()
        term_row.addWidget(edit_term_button)
        term_row.addStretch()

        setup_table(self.contracts, self.contract_model, fit_content=True, fit_rows=SETTINGS_TABLE_ROWS)
        setup_table(self.terms, self.term_model, fit_content=True, fit_rows=SETTINGS_TABLE_ROWS)
        bind_selection(self.contracts, edit_button, delete_button)
        bind_selection(self.terms, edit_term_button)

        contracts_title = QLabel("合約")
        contracts_title.setObjectName("sectionTitle")
        terms_title = QLabel("每一期（續存會產生新的一期，舊的不會被改寫）")
        terms_title.setObjectName("sectionTitle")
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(row)
        layout.addWidget(contracts_title)
        layout.addWidget(self.contracts)
        layout.addWidget(terms_title)
        layout.addLayout(term_row)
        layout.addWidget(self.terms)
        # 表格現在是固定高度（`fit_rows`），沒有這一行的話 QVBoxLayout 會把多餘的
        # 高度平均塞進每個 widget 之間 —— 按鈕與表格會浮在分頁中間。
        layout.addStretch()

        add_button.clicked.connect(self.add_contract)
        edit_button.clicked.connect(self.edit_contract)
        delete_button.clicked.connect(self.delete_contract)
        refresh_button.clicked.connect(self.refresh)
        edit_term_button.clicked.connect(self.edit_term)
        self.contracts.selectionModel().selectionChanged.connect(lambda *_: self.reload_terms())

    def refresh(self) -> None:
        self.contract_model.replace_rows(self.controller.list_deposit_contracts())
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

    def delete_contract(self) -> None:
        item = self.contract_model.selected_item(self.contracts)
        if item is None:
            return
        answer = QMessageBox.question(
            self,
            "確認刪除",
            f"要刪除「{item['name']}」嗎？\n"
            "只有從未入帳過的定存可以刪除；已經有入帳紀錄的請改用結束合約。",
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

    def _finish(self, result: Any, failure_title: str) -> None:
        if not result.success:
            QMessageBox.warning(self, failure_title, result_message(result))
            return
        self.refresh()
        self.changed.emit()


class DepositContractDialog(QDialog):
    """新增與修改共用。修改時**計息方式與期長是唯讀的** —— 它們決定了已產生事件的形狀。"""

    def __init__(
        self,
        controller: LedgerController,
        parent: QWidget,
        *,
        current: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.current = current
        self.values: dict[str, Any] = {}
        self.name = QLineEdit("郵局定存")
        self.account = QComboBox()
        self.new_account_button = QPushButton("新增帳戶…")
        self.interest_destination = QComboBox()
        self.interest_method = QComboBox()
        self.maturity_action = QComboBox()
        self.rate_type = QComboBox()
        self.term_months = QSpinBox()
        self.start_date = date_field()
        self.principal = QLineEdit()
        self.monthly_deposit = QLineEdit()
        self.annual_rate = QLineEdit()
        self.term_hint = QLabel()
        self.error = QLabel()
        self._build()
        self._load()

    def _build(self) -> None:
        editing = self.current is not None
        self.setWindowTitle("修改定存合約" if editing else "新增定存合約")
        for method in InterestMethod:
            self.interest_method.addItem(INTEREST_METHOD_NAMES[method], str(method))
        for action in MaturityAction:
            self.maturity_action.addItem(MATURITY_ACTION_NAMES[action], str(action))
        for kind in RateType:
            self.rate_type.addItem(RATE_TYPE_NAMES[kind], str(kind))
        self.term_months.setRange(1, 600)
        self.term_months.setValue(12)
        self.principal.setPlaceholderText("例如：100000")
        self.monthly_deposit.setPlaceholderText("只有零存整付需要")
        self.annual_rate.setPlaceholderText("例如：1.6；不確定就留空，到期照存摺填")
        self.error.setObjectName("errorLabel")
        self.error.setWordWrap(True)
        self.term_hint.setObjectName("hintLabel")
        self.term_hint.setWordWrap(True)
        self.term_hint.setVisible(False)

        account_row = QWidget()
        account_layout = QHBoxLayout(account_row)
        account_layout.setContentsMargins(0, 0, 0, 0)
        account_layout.addWidget(self.account, 1)
        account_layout.addWidget(self.new_account_button)

        self.form = QFormLayout()
        self.form.addRow("名稱", self.name)
        self.form.addRow("定存帳戶", account_row)
        self.form.addRow("計息方式", self.interest_method)
        self.form.addRow("到期轉存方式", self.maturity_action)
        self.form.addRow("利息轉入帳戶", self.interest_destination)
        self.form.addRow("利率類型", self.rate_type)
        self.form.addRow("期長（月）", self.term_months)
        self.form.addRow("起存日", self.start_date)
        self.form.addRow("本金（TWD）", self.principal)
        self.form.addRow("每月存入（TWD）", self.monthly_deposit)
        self.form.addRow("年利率（%）", self.annual_rate)
        self.form.addRow("", self.term_hint)
        self.form.addRow("", self.error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(
            "儲存" if editing else "建立"
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(buttons)

        self.new_account_button.clicked.connect(self.add_account)
        self.interest_method.currentIndexChanged.connect(self._sync_fields)
        self.maturity_action.currentIndexChanged.connect(self._sync_fields)
        self.rate_type.currentIndexChanged.connect(self._sync_fields)

        if editing:
            # 修改時只開放名稱、到期轉存方式、利息轉入帳戶。其餘欄位改了會讓已產生的
            # 期與事件對不上，要換就結束合約、開新的。
            for widget in (
                self.account,
                self.new_account_button,
                self.interest_method,
                self.rate_type,
                self.term_months,
            ):
                widget.setEnabled(False)
            # **起存日與本金整列收起來，不是停用。**
            #
            # 它們是「期」的欄位，不是合約的欄位（`_contract_view()` 根本沒有這幾個
            # key），所以修改合約時沒有值可以回填 —— 停用之後畫面上顯示的是**建立
            # 用的預設值**：起存日＝今天、本金＝空白。一個灰掉但寫著今天的「起存日」
            # 比沒有那一列更糟，它看起來像事實。
            #
            # 續存過的合約更沒有單一答案：每一期的本金與利率都不同。要改那些東西的
            # 正確入口是這一頁的「修改所選期」。
            for widget in (self.start_date, self.principal):
                self.form.setRowVisible(widget, False)
            self.term_hint.setText(
                "起存日、本金與年利率屬於「期」而不是合約，"
                "要改請關掉這個視窗，在下面的「每一期」選一列按「修改所選期」。"
            )
            self.term_hint.setVisible(True)

    def _load(self) -> None:
        self._reload_accounts()
        if self.current is None:
            self._sync_fields()
            return
        self.name.setText(str(self.current["name"]))
        select_data(self.account, self.current["account_id"])
        select_data(self.interest_method, self.current["interest_method"])
        select_data(self.maturity_action, self.current["maturity_action"])
        select_data(self.rate_type, self.current.get("rate_type", "fixed"))
        select_data(
            self.interest_destination, self.current.get("interest_destination_account_id")
        )
        self.term_months.setValue(int(self.current["term_months"]))
        self._sync_fields()

    def _reload_accounts(self) -> None:
        accounts = self.controller.account_options()
        fill_combo(self.account, accounts, "name", "account_id")
        fill_combo(self.interest_destination, accounts, "name", "account_id")

    def add_account(self) -> None:
        """在這個對話框裡直接開一個定存帳戶，省得中途跳去「帳戶」分頁再回來。

        **打到已經存在的名字不是錯誤，是「你要的就是那一個」。** 預設值是「郵局定存」，
        而那正是最可能已經開過的名字 —— 第二次按下去必然撞名。舊版在這裡丟一個
        警告框（還附著 SQLite 原文），使用者只能自己去猜要改什麼。現在直接把那個帳戶
        選起來，因為那就是他按這顆按鈕想達成的事。
        """
        values = ask_form(
            self,
            "新增帳戶",
            [
                TextField("name", "帳戶名稱", default="郵局定存"),
                TextField("balance", "期初餘額（TWD）", default="0"),
            ],
        )
        if values is None:
            return
        cleaned = str(values["name"]).strip()
        if not cleaned:
            return

        if self._select_account_named(cleaned):
            QMessageBox.information(
                self,
                "已經有這個帳戶",
                f"「{cleaned}」已經在清單裡了，已經幫你選起來。",
            )
            return

        result = self.controller.create_account(cleaned, str(values["balance"]).strip() or "0")
        if not result.success:
            QMessageBox.warning(self, "無法新增帳戶", result_message(result))
            return
        self._reload_accounts()
        self._select_account_named(cleaned)

    def _select_account_named(self, name: str) -> bool:
        """名稱對得上就把它選起來，回傳有沒有找到。

        比對用 `casefold()` —— `accounts.name` 是 `COLLATE NOCASE`，
        資料庫眼中「post」與「POST」是同一個名字，畫面上的判斷不能比它寬鬆。
        """
        for index in range(self.account.count()):
            if self.account.itemText(index).casefold() == name.casefold():
                self.account.setCurrentIndex(index)
                return True
        return False

    def _sync_fields(self) -> None:
        """只顯示這個組合真的需要的欄位。

        **修改模式下「每月存入」與「年利率」一律不顯示** —— 理由同 `_build()` 裡
        起存日與本金那一段：它們是「期」的欄位，這裡沒有值可以回填。
        """
        editing = self.current is not None
        installment = self.interest_method.currentData() == str(
            InterestMethod.INSTALLMENT_SAVINGS
        )
        self.form.setRowVisible(self.monthly_deposit, installment and not editing)

        # 本息續存時利息留在定存帳戶，不需要指定轉入帳戶。
        keeps_interest = self.maturity_action.currentData() == str(
            MaturityAction.RENEW_PRINCIPAL_AND_INTEREST
        )
        self.form.setRowVisible(self.interest_destination, not keeps_interest)

        # 機動利率不預先填數字 —— 存的當下填的值到期時多半已經不是那個值了。
        floating = self.rate_type.currentData() == str(RateType.FLOATING)
        self.form.setRowVisible(self.annual_rate, not floating and not editing)

    def save(self) -> None:
        try:
            annual_rate_ppm = rate_to_ppm(self.annual_rate.text())
        except (InvalidOperation, ValueError):
            self.error.setText("年利率格式不正確，例如 1.6。不確定就留空。")
            return

        keeps_interest = self.maturity_action.currentData() == str(
            MaturityAction.RENEW_PRINCIPAL_AND_INTEREST
        )
        self.values = {
            "account_id": str(self.account.currentData()),
            "name": self.name.text().strip(),
            "interest_method": str(self.interest_method.currentData()),
            "maturity_action": str(self.maturity_action.currentData()),
            "interest_destination_account_id": (
                None if keeps_interest else str(self.interest_destination.currentData())
            ),
            "rate_type": str(self.rate_type.currentData()),
            "term_months": self.term_months.value(),
            "start_date": self.start_date.date().toString("yyyy-MM-dd"),
            "principal": self.principal.text().strip() or "0",
            "annual_rate_ppm": annual_rate_ppm,
            "monthly_deposit": self.monthly_deposit.text().strip() or None,
        }
        self.accept()


class DepositTermDialog(QDialog):
    """修改一期。**主要用途是查到牌告利率之後回來補。**"""

    def __init__(self, term: dict[str, Any], parent: QWidget) -> None:
        super().__init__(parent)
        self.term = term
        self.values: dict[str, Any] = {}
        self.start_date = date_field()
        self.maturity_date = date_field()
        self.principal = QLineEdit(minor_text(term["principal_minor"]))
        self.monthly_deposit = QLineEdit(
            minor_text(term["monthly_deposit_minor"])
            if term.get("monthly_deposit_minor") is not None
            else ""
        )
        self.annual_rate = QLineEdit(rate_input_text(term.get("annual_rate_ppm")))
        self.error = QLabel()
        self._build()

    def _build(self) -> None:
        self.setWindowTitle(f"修改第 {self.term['sequence']} 期")
        for widget, value in (
            (self.start_date, str(self.term["start_date"])),
            (self.maturity_date, str(self.term["maturity_date"])),
        ):
            widget.setDate(QDate.fromString(value, "yyyy-MM-dd"))
        self.annual_rate.setPlaceholderText("查到牌告利率再填；機動利率請留空")
        self.error.setObjectName("errorLabel")
        self.error.setWordWrap(True)

        hint = QLabel(
            "只有「存續中」的期可以修改。已續約或已結清的期已經產生過交易，改了會對不起帳。"
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)

        form = QFormLayout()
        form.addRow("起存日", self.start_date)
        form.addRow("到期日", self.maturity_date)
        form.addRow("本金（TWD）", self.principal)
        form.addRow("每月存入（TWD）", self.monthly_deposit)
        form.addRow("年利率（%）", self.annual_rate)
        form.addRow("", self.error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("儲存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def save(self) -> None:
        try:
            annual_rate_ppm = rate_to_ppm(self.annual_rate.text())
        except (InvalidOperation, ValueError):
            self.error.setText("年利率格式不正確，例如 1.6。不確定就留空。")
            return
        self.values = {
            "start_date": self.start_date.date().toString("yyyy-MM-dd"),
            "maturity_date": self.maturity_date.date().toString("yyyy-MM-dd"),
            "principal": self.principal.text().strip() or "0",
            "annual_rate_ppm": annual_rate_ppm,
            "monthly_deposit": self.monthly_deposit.text().strip() or None,
        }
        self.accept()
