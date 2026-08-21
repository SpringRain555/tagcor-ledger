"""模板與定期收支共用的編輯對話框。

同一份表單服務兩件事，差別只在**多出四列週期欄位**（週期、間隔倍數、開始日期、
結束日期）。兩份幾乎一樣的表單各自維護，遲早會有一邊漏掉某個欄位的驗證。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.domain.money import Money, MoneyError
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import ENTRY_NAMES, FREQUENCY_NAMES, minor_text
from tagcor_ledger.ui.widgets.forms import fill_combo, select_data


class DraftDialog(QDialog):
    def __init__(
        self,
        controller: LedgerController,
        *,
        schedule: bool,
        current: dict[str, Any] | None,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.schedule = schedule
        self.current = current
        self.name = QLineEdit()
        self.flow = QComboBox()
        self.account = QComboBox()
        self.destination = QComboBox()
        self.category = QComboBox()
        self.detail = QComboBox()
        self.amount = QLineEdit()
        self.description = QLineEdit()
        self.frequency = QComboBox()
        self.interval = QSpinBox()
        self.start_date = QDateEdit(QDate.currentDate())
        self.has_end = QCheckBox("設定結束日期")
        self.end_date = QDateEdit(QDate.currentDate().addYears(1))
        self.error = QLabel()
        self.saved_value: Any = None
        self._build()
        self._load()

    def _build(self) -> None:
        self.setWindowTitle("定期收支" if self.schedule else "模板")
        for key in ("expense", "income", "transfer"):
            self.flow.addItem(ENTRY_NAMES[key], key)
        for key in ("daily", "weekly", "monthly", "yearly"):
            self.frequency.addItem(FREQUENCY_NAMES[key], key)
        self.interval.setRange(1, 999)
        self.start_date.setCalendarPopup(True)
        self.end_date.setCalendarPopup(True)
        self.has_end.toggled.connect(self.end_date.setEnabled)
        self.end_date.setEnabled(False)
        self.error.setObjectName("errorLabel")
        # 同 EntryPage：留參考給 _sync_flow 用 setRowVisible 一起收掉標籤。
        self.form = QFormLayout()
        form = self.form
        form.addRow("名稱", self.name)
        form.addRow("流向", self.flow)
        form.addRow("帳戶", self.account)
        form.addRow("轉入帳戶", self.destination)
        form.addRow("類別", self.category)
        form.addRow("項目", self.detail)
        form.addRow("金額（可留空）", self.amount)
        form.addRow("備註", self.description)
        if self.schedule:
            form.addRow("週期", self.frequency)
            form.addRow("間隔倍數", self.interval)
            form.addRow("開始日期", self.start_date)
            form.addRow("", self.has_end)
            form.addRow("結束日期", self.end_date)
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
            if self.schedule:
                select_data(self.frequency, self.current["frequency"])
                self.interval.setValue(int(self.current["interval_count"]))
                self.start_date.setDate(QDate.fromString(self.current["start_date"], "yyyy-MM-dd"))
                if self.current.get("end_date"):
                    self.has_end.setChecked(True)
                    self.end_date.setDate(
                        QDate.fromString(self.current["end_date"], "yyyy-MM-dd")
                    )
        self._sync_flow()

    def save(self) -> None:
        try:
            amount_minor = (
                Money.from_decimal_string(self.amount.text().strip()).amount_minor
                if self.amount.text().strip()
                else None
            )
            values = {
                "name": self.name.text().strip(),
                "entry_type": str(self.flow.currentData()),
                "account_id": str(self.account.currentData()),
                "destination_account_id": (
                    str(self.destination.currentData())
                    if self.flow.currentData() == "transfer"
                    else None
                ),
                "category_id": (
                    str(self.detail.currentData())
                    if self.flow.currentData() != "transfer"
                    else None
                ),
                "amount_minor": amount_minor,
                "description": self.description.text().strip(),
            }
            if self.schedule:
                values.update(
                    {
                        "frequency": str(self.frequency.currentData()),
                        "interval_count": self.interval.value(),
                        "start_date": self.start_date.date().toString("yyyy-MM-dd"),
                        "end_date": (
                            self.end_date.date().toString("yyyy-MM-dd")
                            if self.has_end.isChecked()
                            else None
                        ),
                    }
                )
                schedule_value = self.controller.new_schedule(**values)
                if self.current:
                    schedule_value = replace(
                        schedule_value,
                        schedule_id=str(self.current["schedule_id"]),
                        next_due_date=str(self.current["next_due_date"]),
                    )
                self.saved_value = schedule_value
            else:
                template_value = self.controller.new_template(**values)
                if self.current:
                    template_value = replace(
                        template_value,
                        template_id=str(self.current["template_id"]),
                        sort_order=int(self.current["sort_order"]),
                    )
                self.saved_value = template_value
            self.accept()
        except (MoneyError, ValueError) as exc:
            self.error.setText(f"請檢查輸入內容（{exc}）")

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
