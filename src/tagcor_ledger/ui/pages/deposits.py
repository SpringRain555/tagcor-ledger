"""定存：合約與每一期。

這一頁只管**記錄與檢視**。到期要做什麼一律走「待確認」頁 —— 定存不會有自己的入帳按鈕，
否則就會出現兩個地方都能入帳、兩邊行為還不一樣的老問題。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
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
    InterestMethod,
    MaturityAction,
)
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import (
    deposit_contract_values,
    deposit_term_values,
    result_message,
)
from tagcor_ledger.ui.widgets.forms import fill_combo
from tagcor_ledger.ui.widgets.table import RowsModel, set_button_role, setup_table


class DepositsPage(QWidget):
    changed = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.contracts = QTableView()
        self.contract_model = RowsModel(
            ["名稱", "帳戶", "計息方式", "到期轉存方式", "期長", "狀態"],
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
            "定存到期與每月領息都只會產生「待確認」項目，"
            "**程式不會自動入帳** —— 確認之後才會變成交易。"
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)

        add_button = QPushButton("新增定存合約")
        refresh_button = QPushButton("重新整理")
        set_button_role(add_button, "primary")
        row = QHBoxLayout()
        row.addWidget(add_button)
        row.addWidget(refresh_button)
        row.addStretch()

        setup_table(self.contracts, self.contract_model)
        setup_table(self.terms, self.term_model)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addLayout(row)
        layout.addWidget(QLabel("合約"))
        layout.addWidget(self.contracts)
        layout.addWidget(QLabel("每一期（續存會產生新的一期，舊的不會被改寫）"))
        layout.addWidget(self.terms)

        add_button.clicked.connect(self.add_contract)
        refresh_button.clicked.connect(self.refresh)
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
        result = self.controller.create_deposit_contract(**dialog.values)
        if not result.success:
            QMessageBox.warning(self, "無法建立定存合約", result_message(result))
            return
        self.refresh()
        self.changed.emit()


class DepositContractDialog(QDialog):
    def __init__(self, controller: LedgerController, parent: QWidget) -> None:
        super().__init__(parent)
        self.controller = controller
        self.values: dict[str, Any] = {}
        self.name = QLineEdit("郵局定存")
        self.account = QComboBox()
        self.interest_destination = QComboBox()
        self.interest_method = QComboBox()
        self.maturity_action = QComboBox()
        self.term_months = QSpinBox()
        self.start_date = QDateEdit(QDate.currentDate())
        self.principal = QLineEdit()
        self.monthly_deposit = QLineEdit()
        self.annual_rate = QLineEdit()
        self.error = QLabel()
        self._build()
        self._load()

    def _build(self) -> None:
        self.setWindowTitle("新增定存合約")
        for method in InterestMethod:
            self.interest_method.addItem(INTEREST_METHOD_NAMES[method], str(method))
        for action in MaturityAction:
            self.maturity_action.addItem(MATURITY_ACTION_NAMES[action], str(action))
        self.term_months.setRange(1, 600)
        self.term_months.setValue(12)
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("yyyy/MM/dd")
        self.principal.setPlaceholderText("例如：100000")
        self.monthly_deposit.setPlaceholderText("只有零存整付需要")
        self.annual_rate.setPlaceholderText("例如：1.6，查到再填也可以")
        self.error.setObjectName("errorLabel")
        self.error.setWordWrap(True)

        self.form = QFormLayout()
        self.form.addRow("名稱", self.name)
        self.form.addRow("定存帳戶", self.account)
        self.form.addRow("計息方式", self.interest_method)
        self.form.addRow("到期轉存方式", self.maturity_action)
        self.form.addRow("利息轉入帳戶", self.interest_destination)
        self.form.addRow("期長（月）", self.term_months)
        self.form.addRow("起存日", self.start_date)
        self.form.addRow("本金（TWD）", self.principal)
        self.form.addRow("每月存入（TWD）", self.monthly_deposit)
        self.form.addRow("年利率（%）", self.annual_rate)
        self.form.addRow("", self.error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("建立")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(buttons)

        self.interest_method.currentIndexChanged.connect(self._sync_method)
        self.maturity_action.currentIndexChanged.connect(self._sync_method)
        self._sync_method()

    def _load(self) -> None:
        accounts = self.controller.account_options()
        fill_combo(self.account, accounts, "name", "account_id")
        fill_combo(self.interest_destination, accounts, "name", "account_id")

    def _sync_method(self) -> None:
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

    def save(self) -> None:
        rate_text = self.annual_rate.text().strip()
        annual_rate_ppm: int | None = None
        if rate_text:
            try:
                # 1.6（%）→ 16000 ppm。用字串位移而不是浮點乘法，避免二進位誤差。
                from decimal import Decimal

                annual_rate_ppm = int(
                    (Decimal(rate_text) / Decimal(100) * Decimal(1_000_000)).to_integral_value()
                )
            except Exception:  # noqa: BLE001
                self.error.setText("年利率格式不正確，例如 1.6。")
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
            "term_months": self.term_months.value(),
            "start_date": self.start_date.date().toString("yyyy-MM-dd"),
            "principal": self.principal.text().strip() or "0",
            "annual_rate_ppm": annual_rate_ppm,
            "monthly_deposit": self.monthly_deposit.text().strip() or None,
        }
        self.accept()
