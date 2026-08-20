"""模板與週期排程。

**排程不會自動入帳。** 「產生到期待確認項目」只是把到期的期次放進待確認頁，要不要成
為交易由使用者按下確認決定。`DraftDialog` 同時服務模板與排程，差別只在多出週期欄位。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QCheckBox,
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
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.domain.money import Money, MoneyError
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import (
    ENTRY_NAMES,
    FREQUENCY_NAMES,
    minor_text,
    result_message,
    schedule_values,
    template_values,
)
from tagcor_ledger.ui.widgets.forms import fill_combo, select_data
from tagcor_ledger.ui.widgets.table import (
    RowsModel,
    bind_selection,
    set_button_role,
    setup_table,
)


class AutomationPage(QWidget):
    apply_requested = Signal(dict)
    changed = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.templates = QTableView()
        self.template_model = RowsModel(
            ["名稱", "類型", "金額（TWD）", "備註"],
            template_values,
            amount_column=2,
        )
        self.schedules = QTableView()
        self.schedule_model = RowsModel(
            ["名稱", "類型", "週期", "下次日期", "結束日期"],
            schedule_values,
        )
        self._build()
        self.refresh()

    def _build(self) -> None:
        tabs = QTabWidget()
        tabs.setObjectName("contentTabs")
        template_tab = QWidget()
        template_buttons = QHBoxLayout()
        needs_template_selection: list[QPushButton] = []
        for label, handler in (
            ("新增模板", lambda: self.edit_template(None)),
            ("編輯模板", self.edit_selected_template),
            ("套用到記帳", self.apply_template),
            ("封存模板", self.archive_template),
        ):
            button = QPushButton(label)
            if label.startswith(("新增", "套用")):
                set_button_role(button, "primary")
            if label.startswith("封存"):
                set_button_role(button, "danger")
            if not label.startswith("新增"):
                needs_template_selection.append(button)
            button.clicked.connect(handler)
            template_buttons.addWidget(button)
        template_buttons.addStretch()
        setup_table(self.templates, self.template_model, stretch_column=3)
        bind_selection(self.templates, *needs_template_selection)
        template_layout = QVBoxLayout(template_tab)
        template_layout.addLayout(template_buttons)
        template_layout.addWidget(self.templates)

        schedule_tab = QWidget()
        schedule_buttons = QHBoxLayout()
        needs_schedule_selection: list[QPushButton] = []
        for label, handler in (
            ("新增排程", lambda: self.edit_schedule(None)),
            ("編輯排程", self.edit_selected_schedule),
            ("封存排程", self.archive_schedule),
            ("產生到期待確認項目", self.generate_due),
        ):
            button = QPushButton(label)
            if label.startswith(("新增", "產生")):
                set_button_role(button, "primary")
            if label.startswith("封存"):
                set_button_role(button, "danger")
            if label.startswith(("編輯", "封存")):
                needs_schedule_selection.append(button)
            button.clicked.connect(handler)
            schedule_buttons.addWidget(button)
        schedule_buttons.addStretch()
        setup_table(self.schedules, self.schedule_model)
        bind_selection(self.schedules, *needs_schedule_selection)
        schedule_layout = QVBoxLayout(schedule_tab)
        schedule_layout.addLayout(schedule_buttons)
        schedule_layout.addWidget(self.schedules)
        tabs.addTab(template_tab, "模板")
        tabs.addTab(schedule_tab, "週期排程")
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)

    def refresh(self) -> None:
        self.template_model.replace_rows(self.controller.list_templates())
        self.schedule_model.replace_rows(self.controller.list_schedules())

    def edit_selected_template(self) -> None:
        self.edit_template(self.template_model.selected_item(self.templates))

    def edit_template(self, item: dict[str, Any] | None) -> None:
        dialog = DraftDialog(
            self.controller,
            schedule=False,
            current=item,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        result = self.controller.save_template(dialog.saved_value)
        self._finish(result)

    def apply_template(self) -> None:
        item = self.template_model.selected_item(self.templates)
        if item is not None:
            self.apply_requested.emit(item)

    def archive_template(self) -> None:
        item = self.template_model.selected_item(self.templates)
        if item is not None:
            self._finish(self.controller.archive_template(str(item["template_id"])))

    def edit_selected_schedule(self) -> None:
        self.edit_schedule(self.schedule_model.selected_item(self.schedules))

    def edit_schedule(self, item: dict[str, Any] | None) -> None:
        dialog = DraftDialog(
            self.controller,
            schedule=True,
            current=item,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        result = self.controller.save_schedule(dialog.saved_value)
        self._finish(result)

    def archive_schedule(self) -> None:
        item = self.schedule_model.selected_item(self.schedules)
        if item is not None:
            self._finish(self.controller.archive_schedule(str(item["schedule_id"])))

    def generate_due(self) -> None:
        result = self.controller.generate_due()
        if result.success:
            generated = int(result.details.get("generated", 0))
            suffix = "，仍有更多漏期可繼續產生" if result.details.get("has_more") else ""
            QMessageBox.information(self, "產生完成", f"已產生 {generated} 期待確認項目{suffix}。")
            self.changed.emit()
        else:
            QMessageBox.warning(self, "產生失敗", result_message(result))

    def _finish(self, result: Any) -> None:
        if not result.success:
            QMessageBox.warning(self, "操作失敗", result_message(result))
            return
        self.refresh()
        self.changed.emit()


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
        self.setWindowTitle("排程" if self.schedule else "模板")
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
        # 同 QuickEntryPage：留參考給 _sync_flow 用 setRowVisible 一起收掉標籤。
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
