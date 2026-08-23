"""模板的編輯對話框。

這個檔案以前叫 `draft_dialog.py`，而 `DraftDialog` 用一個 `schedule: bool` 同時服務
模板與定期收支 —— 差別是**多出四列週期欄位**（週期、間隔倍數、開始日期、結束日期）。
v0.23.0 移除定期收支之後那個旗標永遠是 `False`
（[ADR-0011](../../../../docs/decisions/ADR-0011-drop-recurring-schedules.md)），
留著它就是留一個永遠不會走的分支，而那正是下一個人要花時間讀懂再刪掉的東西。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.domain.money import Money, MoneyError
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import ENTRY_NAMES, error_text, minor_text
from tagcor_ledger.ui.widgets.forms import fill_combo, select_data


class TemplateDialog(QDialog):
    NAME_LABEL = "模板名稱"
    """第一格的標籤。

    **不要用「名稱」。** 這張表單裡的每一列都是某個東西的名稱（帳戶、類別、項目），
    所以「名稱」等於沒說 —— 使用者要往上看視窗標題才知道在填哪一個的名字。
    `CatalogPage.NAME_LABEL` 三個子類各自說自己的話，就是同一條。
    """

    def __init__(
        self,
        controller: LedgerController,
        *,
        current: dict[str, Any] | None,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.current = current
        self.name = QLineEdit()
        self.flow = QComboBox()
        self.account = QComboBox()
        self.destination = QComboBox()
        self.category = QComboBox()
        self.detail = QComboBox()
        self.amount = QLineEdit()
        self.description = QLineEdit()
        self.error = QLabel()
        self.saved_value: Any = None
        self._build()
        self._load()

    def _build(self) -> None:
        self.setWindowTitle("模板")
        for key in ("expense", "income", "transfer"):
            self.flow.addItem(ENTRY_NAMES[key], key)
        self.error.setObjectName("errorLabel")
        # 同 EntryPage：留參考給 _sync_flow 用 setRowVisible 一起收掉標籤。
        self.form = QFormLayout()
        form = self.form
        form.addRow(self.NAME_LABEL, self.name)
        form.addRow("流向", self.flow)
        form.addRow("帳戶", self.account)
        form.addRow("轉入帳戶", self.destination)
        form.addRow("類別", self.category)
        form.addRow("項目", self.detail)
        form.addRow("金額（可留空）", self.amount)
        form.addRow("備註", self.description)
        form.addRow("", self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("儲存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.flow.currentIndexChanged.connect(self._sync_flow)
        self.category.currentIndexChanged.connect(self._reload_details)

    def _load(self) -> None:
        accounts = self.controller.account_options()
        fill_combo(self.account, accounts, "name", "account_id")
        fill_combo(self.destination, accounts, "name", "account_id")
        fill_combo(
            self.category,
            self.controller.category_options(),
            "name",
            "category_id",
        )
        self._reload_details()
        if self.current:
            self.name.setText(str(self.current["name"]))
            select_data(self.flow, self.current["entry_type"])
            select_data(self.account, self.current["account_id"])
            select_data(self.destination, self.current.get("destination_account_id"))
            self._select_category(self.current.get("category_id"))
            if self.current.get("amount_minor") is not None:
                self.amount.setText(minor_text(int(self.current["amount_minor"])))
            self.description.setText(str(self.current.get("description", "")))
        self._sync_flow()

    def save(self) -> None:
        """把表單組成一個 `TransactionTemplate` 放進 `saved_value`，由呼叫端寫入。

        ## `replace()` 為什麼一定要帶 `status`

        `new_template()` 把 `status` 寫死成 `"active"`（它的用途是「建一個新的」），
        而 `save_template()` 是 UPSERT 且會寫 `status = excluded.status`。
        **編輯一筆已封存的模板因此會靜悄悄把它變回使用中** —— 這條路在 v0.22.0
        之前走不到，因為模板頁根本不列封存的；列出來的那一刻它就成立了。

        `sort_order` 同理：自訂順序不該因為改了個名字就跳回 100。
        沒帶回去的欄位都要問一次「新建的預設值蓋掉舊值，對嗎」。
        """
        try:
            amount_minor = (
                Money.from_decimal_string(self.amount.text().strip()).amount_minor
                if self.amount.text().strip()
                else None
            )
            template = self.controller.new_template(
                name=self.name.text().strip(),
                entry_type=str(self.flow.currentData()),
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
                amount_minor=amount_minor,
                description=self.description.text().strip(),
            )
            if self.current:
                template = replace(
                    template,
                    template_id=str(self.current["template_id"]),
                    sort_order=int(self.current["sort_order"]),
                    status=str(self.current["status"]),
                )
            self.saved_value = template
            self.accept()
        except (MoneyError, ValueError) as exc:
            self.error.setText(error_text(exc, fallback="請檢查輸入內容。"))

    def _sync_flow(self) -> None:
        transfer = self.flow.currentData() == "transfer"
        self.form.setRowVisible(self.destination, transfer)
        self.form.setRowVisible(self.category, not transfer)
        self.form.setRowVisible(self.detail, not transfer)

    def _reload_details(self) -> None:
        parent_id = self.category.currentData()
        children = (
            self.controller.category_options(str(parent_id))
            if isinstance(parent_id, str)
            else []
        )
        fill_combo(self.detail, children, "name", "category_id")

    def _select_category(self, category_id: object) -> None:
        if not isinstance(category_id, str):
            return
        for index in range(self.category.count()):
            parent_id = str(self.category.itemData(index))
            children = self.controller.category_options(parent_id)
            if any(str(item["category_id"]) == category_id for item in children):
                self.category.setCurrentIndex(index)
                self._reload_details()
                select_data(self.detail, category_id)
                return
