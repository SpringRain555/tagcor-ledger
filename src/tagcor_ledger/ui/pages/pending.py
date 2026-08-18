"""待確認：排程產生的到期項目，確認後才成為交易。

這是**單一收件匣** —— 日後定存到期事件也走這一頁，不要另外開一個「待處理」清單。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
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
    QTableView,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.domain.money import Money, MoneyError
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import minor_text, occurrence_values, result_message
from tagcor_ledger.ui.widgets.forms import fill_combo, select_data
from tagcor_ledger.ui.widgets.table import RowsModel, set_button_role, setup_table


class PendingPage(QWidget):
    changed = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.table = QTableView()
        self.model = RowsModel(
            ["到期日", "排程", "類型", "金額", "狀態說明"],
            occurrence_values,
        )
        self.has_more = False
        self._build()
        self.refresh()

    def _build(self) -> None:
        title = QLabel("待確認")
        title.setObjectName("pageTitle")
        edit_confirm = QPushButton("修改後確認入帳")
        skip = QPushButton("略過")
        batch = QPushButton("批次確認有效項目")
        generate = QPushButton("繼續產生到期項目")
        set_button_role(edit_confirm, "primary")
        set_button_role(batch, "primary")
        set_button_role(generate, "primary")
        row = QHBoxLayout()
        for widget in (edit_confirm, skip, batch, generate):
            row.addWidget(widget)
        row.addStretch()
        setup_table(self.table, self.model)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addLayout(row)
        layout.addWidget(self.table)
        edit_confirm.clicked.connect(self.edit_confirm)
        skip.clicked.connect(self.skip)
        batch.clicked.connect(self.batch_confirm)
        generate.clicked.connect(self.generate)

    def refresh(self) -> None:
        self.model.replace_rows(self.controller.list_pending())
        self.changed.emit()

    def edit_confirm(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None:
            return
        dialog = PendingEditDialog(self.controller, item, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def skip(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None:
            return
        result = self.controller.skip_occurrence(str(item["occurrence_id"]))
        if result.success:
            self.refresh()
        else:
            QMessageBox.warning(self, "無法略過", result_message(result))

    def batch_confirm(self) -> None:
        result = self.controller.batch_confirm_valid()
        QMessageBox.information(
            self,
            "批次確認完成",
            f"已入帳 {result.details.get('confirmed', 0)} 筆，"
            f"略過無效或失敗 {result.details.get('failed', 0)} 筆。",
        )
        self.refresh()

    def generate(self) -> None:
        result = self.controller.generate_due()
        if not result.success:
            QMessageBox.warning(self, "產生失敗", result_message(result))
            return
        generated = int(result.details.get("generated", 0))
        message = f"已產生 {generated} 期。"
        if result.details.get("has_more"):
            message += "仍有更多漏期，請再次按下繼續產生。"
        QMessageBox.information(self, "產生完成", message)
        self.refresh()


class PendingEditDialog(QDialog):
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
        self.setWindowTitle("修改待確認項目")
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
            self.error.setText(f"金額無效（{exc}）")
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
