"""交易紀錄：組合篩選、雙向 keyset 分頁、編輯與作廢。

轉帳沒有「編輯」—— 編輯轉帳實際上是建一筆新的、作廢原本那筆（替換轉帳），所以同一顆
按鈕在轉帳與非轉帳時做的是兩件不同的事，對話框標題也不一樣。
"""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import QDate, QDateTime, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
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

from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import result_message, transaction_values
from tagcor_ledger.ui.widgets.forms import fill_combo, iso_datetime, select_data
from tagcor_ledger.ui.widgets.table import RowsModel, set_button_role, setup_table


class TransactionsPage(QWidget):
    duplicate_requested = Signal(dict)

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.table = QTableView()
        self.model = RowsModel(
            ["時間", "類型", "帳戶", "類別／項目", "金額", "備註", "狀態"],
            transaction_values,
        )
        self.search = QLineEdit()
        self.date_enabled = QCheckBox("日期")
        self.date_from = QDateEdit(QDate.currentDate().addMonths(-1))
        self.date_to = QDateEdit(QDate.currentDate())
        self.account = QComboBox()
        self.category = QComboBox()
        self.status = QComboBox()
        self.previous_button = QPushButton("上一頁")
        self.next_button = QPushButton("下一頁")
        self.cursors: list[dict[str, str] | None] = [None]
        self.page_index = 0
        self.next_cursor: dict[str, str] | None = None
        self._build()
        self.reload_filters()
        self.refresh()

    def _build(self) -> None:
        title = QLabel("交易紀錄")
        title.setObjectName("pageTitle")
        self.search.setPlaceholderText("搜尋備註、類別、項目或帳戶")
        self.date_from.setDisplayFormat("yyyy/MM/dd")
        self.date_to.setDisplayFormat("yyyy/MM/dd")
        for date_widget in (self.date_from, self.date_to):
            date_widget.setCalendarPopup(True)
            date_widget.setEnabled(False)
        self.date_enabled.toggled.connect(self.date_from.setEnabled)
        self.date_enabled.toggled.connect(self.date_to.setEnabled)
        self.status.addItem("有效", "active")
        self.status.addItem("已作廢", "voided")
        self.status.addItem("全部", "all")
        apply_button = QPushButton("套用篩選")
        clear_button = QPushButton("清除篩選")
        set_button_role(apply_button, "primary")
        filters = QHBoxLayout()
        for filter_widget in (
            self.search,
            self.date_enabled,
            self.date_from,
            self.date_to,
            self.account,
            self.category,
            self.status,
            apply_button,
            clear_button,
        ):
            filters.addWidget(filter_widget)
        setup_table(self.table, self.model)
        edit_button = QPushButton("編輯／替換")
        duplicate_button = QPushButton("複製到快速記帳")
        void_button = QPushButton("作廢")
        set_button_role(edit_button, "primary")
        set_button_role(void_button, "danger")
        actions = QHBoxLayout()
        for action_button in (edit_button, duplicate_button, void_button):
            actions.addWidget(action_button)
        actions.addStretch()
        actions.addWidget(self.previous_button)
        actions.addWidget(self.next_button)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addLayout(filters)
        layout.addWidget(self.table)
        layout.addLayout(actions)
        apply_button.clicked.connect(self.first_page)
        clear_button.clicked.connect(self.clear_filters)
        self.search.returnPressed.connect(self.first_page)
        self.previous_button.clicked.connect(self.previous_page)
        self.next_button.clicked.connect(self.next_page)
        edit_button.clicked.connect(self.edit_selected)
        duplicate_button.clicked.connect(self.duplicate_selected)
        void_button.clicked.connect(self.void_selected)

    def reload_filters(self) -> None:
        fill_combo(
            self.account,
            self.controller.account_options(),
            "name",
            "account_id",
            first=("全部帳戶", None),
        )
        fill_combo(
            self.category,
            self.controller.category_options(),
            "name",
            "category_id",
            first=("全部類別", None),
        )

    def first_page(self) -> None:
        self.cursors = [None]
        self.page_index = 0
        self.refresh()

    def clear_filters(self) -> None:
        self.search.clear()
        self.date_enabled.setChecked(False)
        self.account.setCurrentIndex(0)
        self.category.setCurrentIndex(0)
        self.status.setCurrentIndex(0)
        self.first_page()

    def next_page(self) -> None:
        if self.next_cursor is None:
            return
        self.cursors = self.cursors[: self.page_index + 1]
        self.cursors.append(self.next_cursor)
        self.page_index += 1
        self.refresh()

    def previous_page(self) -> None:
        if self.page_index == 0:
            return
        self.page_index -= 1
        self.refresh()

    def refresh(self) -> None:
        result = self.controller.list_transactions(
            search=self.search.text().strip(),
            date_from=(
                self.date_from.date().toString("yyyy-MM-dd") + "T00:00:00+08:00"
                if self.date_enabled.isChecked()
                else None
            ),
            date_to=(
                self.date_to.date().toString("yyyy-MM-dd") + "T23:59:59+08:00"
                if self.date_enabled.isChecked()
                else None
            ),
            account_id=cast(str | None, self.account.currentData()),
            category_id=cast(str | None, self.category.currentData()),
            status=str(self.status.currentData()),
            cursor=self.cursors[self.page_index],
        )
        if not result.success:
            QMessageBox.warning(self, "交易無法載入", result_message(result))
            return
        self.model.replace_rows(list(result.details.get("transactions", [])))
        next_cursor = result.details.get("next_cursor")
        self.next_cursor = dict(next_cursor) if isinstance(next_cursor, dict) else None
        self.previous_button.setEnabled(self.page_index > 0)
        self.next_button.setEnabled(self.next_cursor is not None)

    def duplicate_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is not None:
            self.duplicate_requested.emit(item)

    def edit_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None:
            return
        dialog = TransactionEditDialog(self.controller, item, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.first_page()

    def void_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None or item["status"] != "active":
            return
        answer = QMessageBox.question(self, "確認作廢", "確定要作廢所選交易嗎？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        result = self.controller.void_transaction(str(item["transaction_id"]))
        if result.success:
            self.first_page()
        else:
            QMessageBox.warning(self, "無法作廢", result_message(result))


class TransactionEditDialog(QDialog):
    def __init__(
        self,
        controller: LedgerController,
        transaction: dict[str, Any],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.transaction = transaction
        self.account = QComboBox()
        self.destination = QComboBox()
        self.category = QComboBox()
        self.detail = QComboBox()
        self.occurred_at = QDateTimeEdit()
        self.amount = QLineEdit(str(transaction["amount"]))
        self.description = QLineEdit(str(transaction["description"]))
        self.error = QLabel()
        self._build()
        self._load()

    def _build(self) -> None:
        transfer = self.transaction["entry_type"] == "transfer"
        self.setWindowTitle("替換轉帳" if transfer else "編輯交易")
        self.occurred_at.setCalendarPopup(True)
        self.occurred_at.setDisplayFormat("yyyy/MM/dd HH:mm")
        self.occurred_at.setDateTime(
            QDateTime.fromString(str(self.transaction["occurred_at"]), Qt.DateFormat.ISODate)
        )
        self.error.setObjectName("errorLabel")
        form = QFormLayout()
        form.addRow("帳戶", self.account)
        if transfer:
            form.addRow("轉入帳戶", self.destination)
        else:
            form.addRow("類別", self.category)
            form.addRow("項目", self.detail)
        form.addRow("時間", self.occurred_at)
        form.addRow("金額（TWD）", self.amount)
        form.addRow("備註", self.description)
        form.addRow("", self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(
            "建立新轉帳並作廢原交易" if transfer else "儲存"
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.category.currentIndexChanged.connect(self._load_details)

    def _load(self) -> None:
        accounts = self.controller.account_options()
        fill_combo(self.account, accounts, "name", "account_id")
        fill_combo(self.destination, accounts, "name", "account_id")
        select_data(self.account, self.transaction["account_id"])
        select_data(self.destination, self.transaction["destination_account_id"])
        if self.transaction["entry_type"] != "transfer":
            fill_combo(
                self.category,
                self.controller.category_options(),
                "name",
                "category_id",
            )
            select_data(self.category, self.transaction["category_id"])
            self._load_details()
            select_data(self.detail, self.transaction["subcategory_id"])

    def _load_details(self) -> None:
        parent_id = self.category.currentData()
        children = (
            self.controller.category_options(str(parent_id))
            if isinstance(parent_id, str)
            else []
        )
        fill_combo(self.detail, children, "name", "category_id")

    def save(self) -> None:
        common = {
            "occurred_at": iso_datetime(self.occurred_at),
            "amount": self.amount.text().strip(),
            "description": self.description.text().strip(),
        }
        if self.transaction["entry_type"] == "transfer":
            result = self.controller.replace_transfer(
                original_transaction_id=str(self.transaction["transaction_id"]),
                source_account_id=str(self.account.currentData()),
                destination_account_id=str(self.destination.currentData()),
                **common,
            )
        else:
            result = self.controller.update_transaction(
                transaction_id=str(self.transaction["transaction_id"]),
                expected_revision=int(self.transaction["revision"]),
                account_id=str(self.account.currentData()),
                category_id=str(self.detail.currentData()),
                **common,
            )
        if result.success:
            self.accept()
        else:
            self.error.setText(result_message(result))
