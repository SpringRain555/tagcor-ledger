"""定存：合約與每一期。

這一頁只管**記錄與檢視**。到期要做什麼一律走「待確認」頁 —— 定存不會有自己的入帳按鈕，
否則就會出現兩個地方都能入帳、兩邊行為還不一樣的老問題。

「修改所選期」是**查到牌告利率之後回來補**的路徑。go-live runbook 叫使用者先留空利率，
沒有這顆按鈕那句話就是做不到的。
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
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
)
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import (
    deposit_contract_values,
    deposit_term_values,
    minor_text,
    result_message,
)
from tagcor_ledger.ui.widgets.forms import fill_combo, select_data
from tagcor_ledger.ui.widgets.table import RowsModel, set_button_role, setup_table


def rate_to_ppm(text: str) -> int | None:
    """「1.6」→ 16000 ppm。空字串回 `None`；格式不對丟 `InvalidOperation`。

    走 `Decimal` 不走 float —— 這個專案的金額與利率都不碰二進位浮點數。
    """
    clean = text.strip().rstrip("%").strip()
    if not clean:
        return None
    return int((Decimal(clean) / Decimal(100) * Decimal(1_000_000)).to_integral_value())


def ppm_to_rate_text(ppm: object) -> str:
    if ppm is None:
        return ""
    whole, fraction = divmod(int(ppm), 10_000)  # type: ignore[call-overload]
    return f"{whole}.{fraction:04d}".rstrip("0").rstrip(".")


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
            ["期", "起存日", "到期日", "本金", "年利率", "實際利息", "狀態"],
            deposit_term_values,
        )
        self._build()
        self.refresh()

    def _build(self) -> None:
        title = QLabel("定存")
        title.setObjectName("pageTitle")
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

        setup_table(self.contracts, self.contract_model)
        setup_table(self.terms, self.term_model)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addLayout(row)
        layout.addWidget(QLabel("合約"))
        layout.addWidget(self.contracts)
        layout.addWidget(QLabel("每一期（續存會產生新的一期，舊的不會被改寫）"))
        layout.addLayout(term_row)
        layout.addWidget(self.terms)

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
                note=dialog.values.get("note", ""),
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
        self.start_date = QDateEdit(QDate.currentDate())
        self.principal = QLineEdit()
        self.monthly_deposit = QLineEdit()
        self.annual_rate = QLineEdit()
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
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("yyyy/MM/dd")
        self.principal.setPlaceholderText("例如：100000")
        self.monthly_deposit.setPlaceholderText("只有零存整付需要")
        self.annual_rate.setPlaceholderText("例如：1.6；不確定就留空，到期照存摺填")
        self.error.setObjectName("errorLabel")
        self.error.setWordWrap(True)

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
                self.start_date,
                self.principal,
                self.monthly_deposit,
                self.annual_rate,
            ):
                widget.setEnabled(False)

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
        """在這個對話框裡直接開一個定存帳戶，省得中途跳去「帳戶」分頁再回來。"""
        name, accepted = QInputDialog.getText(self, "新增帳戶", "帳戶名稱", text="郵局定存")
        if not accepted or not name.strip():
            return
        balance, accepted = QInputDialog.getText(
            self, "新增帳戶", "期初餘額（TWD）", text="0"
        )
        if not accepted:
            return
        result = self.controller.create_account(name.strip(), balance.strip() or "0")
        if not result.success:
            QMessageBox.warning(self, "無法新增帳戶", result_message(result))
            return
        self._reload_accounts()
        for index in range(self.account.count()):
            if self.account.itemText(index) == name.strip():
                self.account.setCurrentIndex(index)
                break

    def _sync_fields(self) -> None:
        """只顯示這個組合真的需要的欄位。"""
        installment = self.interest_method.currentData() == str(
            InterestMethod.INSTALLMENT_SAVINGS
        )
        self.form.setRowVisible(self.monthly_deposit, installment)

        # 本息續存時利息留在定存帳戶，不需要指定轉入帳戶。
        keeps_interest = self.maturity_action.currentData() == str(
            MaturityAction.RENEW_PRINCIPAL_AND_INTEREST
        )
        self.form.setRowVisible(self.interest_destination, not keeps_interest)

        # 機動利率不預先填數字 —— 存的當下填的值到期時多半已經不是那個值了。
        floating = self.rate_type.currentData() == str(RateType.FLOATING)
        self.form.setRowVisible(self.annual_rate, not floating)

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
        self.start_date = QDateEdit()
        self.maturity_date = QDateEdit()
        self.principal = QLineEdit(minor_text(term["principal_minor"]))
        self.monthly_deposit = QLineEdit(
            minor_text(term["monthly_deposit_minor"])
            if term.get("monthly_deposit_minor") is not None
            else ""
        )
        self.annual_rate = QLineEdit(ppm_to_rate_text(term.get("annual_rate_ppm")))
        self.error = QLabel()
        self._build()

    def _build(self) -> None:
        self.setWindowTitle(f"修改第 {self.term['sequence']} 期")
        for widget, value in (
            (self.start_date, str(self.term["start_date"])),
            (self.maturity_date, str(self.term["maturity_date"])),
        ):
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("yyyy/MM/dd")
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
