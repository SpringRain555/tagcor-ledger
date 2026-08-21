"""記帳：每天最常用的那一頁。

## 這一頁的三個設計取捨

1. **金額是主角。** 它是唯一每次都必須手打的欄位，所以字級與高度都比其他欄位大一階，
   而且 `Ctrl+N` 直接聚焦到它。其他欄位多半沿用上次或用預設值。
2. **流向用三顆分段按鈕，不是下拉選單。** 下拉要「點開、找、再點」三個動作；
   三顆按鈕一下就好。選項永遠只有三個，不會長出第四個。
3. **成功與失敗共用一個訊息位置，但顏色不同。** 以前成功訊息寫進紅色的 `errorLabel`，
   每天最常做的動作回饋長得像失敗。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import ENTRY_NAMES, minor_text, result_message
from tagcor_ledger.ui.widgets.forms import (
    date_field,
    fill_combo,
    iso_from_date,
    select_data,
    show_status,
    status_label,
)
from tagcor_ledger.ui.widgets.layout import FORM_WIDTH, page_layout
from tagcor_ledger.ui.widgets.table import set_button_role

ENTRY_TYPES = ("expense", "income", "transfer")


class EntryPage(QWidget):
    saved = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.flow_buttons = QButtonGroup(self)
        self.account = QComboBox()
        self.destination = QComboBox()
        self.category = QComboBox()
        self.detail = QComboBox()
        self.occurred_at = date_field()
        self.amount = QLineEdit()
        self.description = QLineEdit()
        self.status = status_label()
        self.save_button = QPushButton("儲存交易")
        self._build()
        self.reload_options()
        self.apply_defaults()

    def _build(self) -> None:
        title = QLabel("記帳")
        title.setObjectName("pageTitle")
        set_button_role(self.save_button, "primary")

        flow_row = QHBoxLayout()
        flow_row.setSpacing(8)
        for index, key in enumerate(ENTRY_TYPES):
            button = QPushButton(ENTRY_NAMES[key])
            button.setObjectName("segmentButton")
            button.setCheckable(True)
            button.setProperty("entry_type", key)
            self.flow_buttons.addButton(button, index)
            flow_row.addWidget(button)
        flow_row.addStretch()
        self.flow_buttons.setExclusive(True)
        self.flow_buttons.button(0).setChecked(True)

        self.amount.setObjectName("amountInput")
        self.amount.setPlaceholderText("0")
        self.description.setPlaceholderText("可留空")

        self.form = QFormLayout()
        form = self.form
        form.setSpacing(10)
        form.addRow("流向", flow_row)
        form.addRow("金額（TWD）", self.amount)
        form.addRow("帳戶", self.account)
        form.addRow("轉入帳戶", self.destination)
        form.addRow("類別", self.category)
        form.addRow("項目", self.detail)
        form.addRow("日期", self.occurred_at)
        form.addRow("備註", self.description)
        form.addRow("", self.status)
        form.addRow("", self.save_button)

        layout = page_layout(self, width=FORM_WIDTH)
        layout.addWidget(title)
        layout.addLayout(form)
        layout.addStretch()

        self.flow_buttons.idToggled.connect(lambda *_: self._sync_flow())
        self.category.currentIndexChanged.connect(self._reload_details)
        self.save_button.clicked.connect(self.submit)
        self.amount.returnPressed.connect(self.submit)
        self.description.returnPressed.connect(self.submit)
        self._sync_flow()

    # --- 流向 -----------------------------------------------------------------

    def current_entry_type(self) -> str:
        button = self.flow_buttons.checkedButton()
        return str(button.property("entry_type")) if button is not None else "expense"

    def select_entry_type(self, entry_type: object) -> None:
        for button in self.flow_buttons.buttons():
            if button.property("entry_type") == entry_type:
                button.setChecked(True)
                return

    # --- 選項 -----------------------------------------------------------------

    def reload_options(self) -> None:
        # 帳戶只查一次填兩個下拉。以前是連呼叫兩次 `account_options()`，
        # 而那個方法會去算每個帳戶的餘額 —— 等於整段成本白付兩遍。
        accounts = self.controller.account_options()
        fill_combo(self.account, accounts, "name", "account_id")
        fill_combo(self.destination, accounts, "name", "account_id")
        fill_combo(self.category, self.controller.category_options(), "name", "category_id")
        self._reload_details()

    def apply_defaults(self) -> None:
        settings = self.controller.get_settings()
        select_data(self.account, settings.default_account_id)
        self.select_entry_type(settings.default_entry_type)
        self._sync_flow()

    def apply_draft(self, draft: dict[str, Any], *, use_current_time: bool = True) -> None:
        self.select_entry_type(draft.get("entry_type"))
        select_data(self.account, draft.get("account_id"))
        select_data(self.destination, draft.get("destination_account_id"))
        self._select_category(draft.get("category_id"))
        amount_minor = draft.get("amount_minor")
        self.amount.setText(minor_text(amount_minor) if amount_minor is not None else "")
        self.description.setText(str(draft.get("description", "")))
        if use_current_time:
            self.occurred_at.setDate(QDate.currentDate())
        show_status(self.status, "內容已帶入，確認後再儲存。")
        self.amount.setFocus()

    def clear_form(self) -> None:
        self.occurred_at.setDate(QDate.currentDate())
        self.amount.clear()
        self.description.clear()
        show_status(self.status, "")
        self.amount.setFocus()

    def submit(self) -> None:
        entry_type = self.current_entry_type()
        result = self.controller.submit(
            occurred_at=iso_from_date(self.occurred_at),
            entry_type=entry_type,
            amount=self.amount.text().strip(),
            account_id=str(self.account.currentData()),
            destination_account_id=(
                str(self.destination.currentData()) if entry_type == "transfer" else None
            ),
            category_id=(
                str(self.detail.currentData()) if entry_type != "transfer" else None
            ),
            description=self.description.text().strip(),
        )
        if result.success:
            self.clear_form()
            show_status(self.status, "交易已儲存。", ok=True)
            self.saved.emit()
            return
        show_status(self.status, result_message(result), ok=False)

    def _sync_flow(self) -> None:
        """轉帳沒有類別／項目，非轉帳沒有轉入帳戶 —— 用不到的整列收起來。

        必須用 `setRowVisible` 而不是對欄位 `setVisible`：QFormLayout 的標籤是獨立的
        widget，只藏欄位會留下一個沒有內容的標籤浮在畫面上。
        """
        transfer = self.current_entry_type() == "transfer"
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
