"""快速記帳：每天最常用的那一頁。"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QDateTime, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import ENTRY_NAMES, minor_text, result_message
from tagcor_ledger.ui.widgets.forms import fill_combo, iso_datetime, select_data
from tagcor_ledger.ui.widgets.table import set_button_role


class QuickEntryPage(QWidget):
    saved = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.flow = QComboBox()
        self.account = QComboBox()
        self.destination = QComboBox()
        self.category = QComboBox()
        self.detail = QComboBox()
        self.occurred_at = QDateTimeEdit(QDateTime.currentDateTime())
        self.amount = QLineEdit()
        self.description = QLineEdit()
        self.error = QLabel()
        self.save_button = QPushButton("儲存交易")
        self._build()
        self.reload_options()
        self.apply_defaults()

    def _build(self) -> None:
        title = QLabel("快速記帳")
        title.setObjectName("pageTitle")
        set_button_role(self.save_button, "primary")
        for key in ("expense", "income", "transfer"):
            self.flow.addItem(ENTRY_NAMES[key], key)
        self.occurred_at.setCalendarPopup(True)
        self.occurred_at.setDisplayFormat("yyyy/MM/dd HH:mm")
        self.amount.setPlaceholderText("例如：120")
        self.description.setPlaceholderText("可留空")
        self.error.setObjectName("errorLabel")
        self.error.setWordWrap(True)

        # 留著這個參考是為了 _sync_flow 能用 setRowVisible 一起收掉標籤，
        # 只對欄位 setVisible 會留下一個沒有內容的「轉入帳戶」標籤。
        self.form = QFormLayout()
        form = self.form
        form.addRow("流向", self.flow)
        form.addRow("帳戶", self.account)
        form.addRow("轉入帳戶", self.destination)
        form.addRow("類別", self.category)
        form.addRow("項目", self.detail)
        form.addRow("時間", self.occurred_at)
        form.addRow("金額（TWD）", self.amount)
        form.addRow("備註", self.description)
        form.addRow("", self.error)
        form.addRow("", self.save_button)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addLayout(form)
        layout.addStretch()

        self.flow.currentIndexChanged.connect(self._sync_flow)
        self.category.currentIndexChanged.connect(self._reload_details)
        self.save_button.clicked.connect(self.submit)
        self.amount.returnPressed.connect(self.submit)
        self.description.returnPressed.connect(self.submit)
        self._sync_flow()

    def reload_options(self) -> None:
        fill_combo(self.account, self.controller.account_options(), "name", "account_id")
        fill_combo(self.destination, self.controller.account_options(), "name", "account_id")
        fill_combo(self.category, self.controller.category_options(), "name", "category_id")
        self._reload_details()

    def apply_defaults(self) -> None:
        settings = self.controller.get_settings()
        select_data(self.account, settings.default_account_id)
        select_data(self.flow, settings.default_entry_type)
        self._sync_flow()

    def apply_draft(self, draft: dict[str, Any], *, use_current_time: bool = True) -> None:
        select_data(self.flow, draft.get("entry_type"))
        select_data(self.account, draft.get("account_id"))
        select_data(self.destination, draft.get("destination_account_id"))
        self._select_category(draft.get("category_id"))
        amount_minor = draft.get("amount_minor")
        self.amount.setText(minor_text(amount_minor) if amount_minor is not None else "")
        self.description.setText(str(draft.get("description", "")))
        if use_current_time:
            self.occurred_at.setDateTime(QDateTime.currentDateTime())
        self.error.setText("內容已帶入，確認後再儲存。")
        self.amount.setFocus()

    def clear_form(self) -> None:
        self.occurred_at.setDateTime(QDateTime.currentDateTime())
        self.amount.clear()
        self.description.clear()
        self.error.clear()
        self.amount.setFocus()

    def submit(self) -> None:
        result = self.controller.submit(
            occurred_at=iso_datetime(self.occurred_at),
            entry_type=str(self.flow.currentData()),
            amount=self.amount.text().strip(),
            account_id=str(self.account.currentData()),
            destination_account_id=(
                str(self.destination.currentData())
                if self.flow.currentData() == "transfer"
                else None
            ),
            category_id=(
                str(self.detail.currentData())
                if self.flow.currentData() != "transfer"
                else None
            ),
            description=self.description.text().strip(),
        )
        if result.success:
            self.clear_form()
            self.error.setText("交易已儲存。")
            self.saved.emit()
            return
        self.error.setText(result_message(result))

    def _sync_flow(self) -> None:
        """轉帳沒有類別／項目，非轉帳沒有轉入帳戶 —— 用不到的整列收起來。

        必須用 `setRowVisible` 而不是對欄位 `setVisible`：QFormLayout 的標籤是獨立的
        widget，只藏欄位會留下一個沒有內容的標籤浮在畫面上。
        """
        transfer = self.flow.currentData() == "transfer"
        self.form.setRowVisible(self.destination, transfer)
        self.form.setRowVisible(self.category, not transfer)
        self.form.setRowVisible(self.detail, not transfer)

    def _reload_details(self) -> None:
        parent_id = self.category.currentData()
        items = (
            self.controller.category_options(str(parent_id))
            if isinstance(parent_id, str)
            else []
        )
        fill_combo(self.detail, items, "name", "category_id")

    def _select_category(self, category_id: object) -> None:
        if not isinstance(category_id, str):
            return
        for parent_index in range(self.category.count()):
            parent_id = str(self.category.itemData(parent_index))
            children = self.controller.category_options(parent_id)
            if any(str(item["category_id"]) == category_id for item in children):
                self.category.setCurrentIndex(parent_index)
                self._reload_details()
                select_data(self.detail, category_id)
                return
        select_data(self.category, category_id)
