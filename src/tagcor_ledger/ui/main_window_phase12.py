"""Traditional Chinese PySide6 interface for Phase 1–2."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, cast

from PySide6.QtCore import (
    QAbstractTableModel,
    QDate,
    QDateTime,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.domain.models import ApplicationSettings
from tagcor_ledger.domain.money import Money, MoneyError
from tagcor_ledger.infrastructure.clock import TAIPEI
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.theme import apply_dark_theme


ENTRY_NAMES = {"expense": "支出", "income": "收入", "transfer": "轉帳"}
STATUS_NAMES = {"active": "有效", "voided": "已作廢"}
FREQUENCY_NAMES = {
    "daily": "日",
    "weekly": "週",
    "monthly": "月",
    "yearly": "年",
}


class RowsModel(QAbstractTableModel):
    def __init__(
        self,
        headers: list[str],
        mapper: Callable[[dict[str, Any]], list[str]],
    ) -> None:
        super().__init__()
        self.headers = headers
        self.mapper = mapper
        self.items: list[dict[str, Any]] = []

    def replace_rows(self, items: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self.items = items
        self.endResetModel()

    def selected_item(self, table: QTableView) -> dict[str, Any] | None:
        rows = table.selectionModel().selectedRows()
        return self.items[rows[0].row()] if rows else None

    def rowCount(  # noqa: N802
        self,
        parent: QModelIndex | QPersistentModelIndex = QModelIndex(),
    ) -> int:
        return 0 if parent.isValid() else len(self.items)

    def columnCount(  # noqa: N802
        self,
        parent: QModelIndex | QPersistentModelIndex = QModelIndex(),
    ) -> int:
        return 0 if parent.isValid() else len(self.headers)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self.items):
            return None
        if role == Qt.ItemDataRole.UserRole:
            return self.items[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return self.mapper(self.items[index.row()])[index.column()]
        return None

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return super().headerData(section, orientation, role)


def _setup_table(table: QTableView, model: RowsModel) -> None:
    table.setModel(model)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.horizontalHeader().setStretchLastSection(True)
    table.setAlternatingRowColors(True)


def _set_button_role(button: QPushButton, role: str) -> QPushButton:
    button.setObjectName(f"{role}Button")
    return button


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
        _set_button_role(self.save_button, "primary")
        for key in ("expense", "income", "transfer"):
            self.flow.addItem(ENTRY_NAMES[key], key)
        self.occurred_at.setCalendarPopup(True)
        self.occurred_at.setDisplayFormat("yyyy/MM/dd HH:mm")
        self.amount.setPlaceholderText("例如：120")
        self.description.setPlaceholderText("可留空")
        self.error.setObjectName("errorLabel")
        self.error.setWordWrap(True)

        form = QFormLayout()
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
        _fill_combo(self.account, self.controller.account_options(), "name", "account_id")
        _fill_combo(self.destination, self.controller.account_options(), "name", "account_id")
        _fill_combo(self.category, self.controller.category_options(), "name", "category_id")
        self._reload_details()

    def apply_defaults(self) -> None:
        settings = self.controller.get_settings()
        _select_data(self.account, settings.default_account_id)
        _select_data(self.flow, settings.default_entry_type)
        self._sync_flow()

    def apply_draft(self, draft: dict[str, Any], *, use_current_time: bool = True) -> None:
        _select_data(self.flow, draft.get("entry_type"))
        _select_data(self.account, draft.get("account_id"))
        _select_data(self.destination, draft.get("destination_account_id"))
        self._select_category(draft.get("category_id"))
        amount_minor = draft.get("amount_minor")
        self.amount.setText(_minor_text(amount_minor) if amount_minor is not None else "")
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
            occurred_at=_iso_datetime(self.occurred_at),
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
        self.error.setText(_result_message(result))

    def _sync_flow(self) -> None:
        transfer = self.flow.currentData() == "transfer"
        self.destination.setVisible(transfer)
        self.category.setVisible(not transfer)
        self.detail.setVisible(not transfer)

    def _reload_details(self) -> None:
        parent_id = self.category.currentData()
        items = (
            self.controller.category_options(str(parent_id))
            if isinstance(parent_id, str)
            else []
        )
        _fill_combo(self.detail, items, "name", "category_id")

    def _select_category(self, category_id: object) -> None:
        if not isinstance(category_id, str):
            return
        for parent_index in range(self.category.count()):
            parent_id = str(self.category.itemData(parent_index))
            children = self.controller.category_options(parent_id)
            if any(str(item["category_id"]) == category_id for item in children):
                self.category.setCurrentIndex(parent_index)
                self._reload_details()
                _select_data(self.detail, category_id)
                return
        _select_data(self.category, category_id)


class BalanceSnapshotPage(QWidget):
    changed = Signal()
    record_transaction_requested = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.account = QComboBox()
        self.status = QComboBox()
        self.observed_at = QDateTimeEdit(QDateTime.currentDateTime())
        self.amount = QLineEdit()
        self.note = QLineEdit()
        self.result = QLabel()
        self.summary = QLabel()
        self.table = QTableView()
        self.model = RowsModel(
            ["盤點時間", "帳戶", "實際金額", "預期金額", "未解釋差額", "備註", "狀態"],
            _balance_gap_values,
        )
        self.transactions = QTableView()
        self.transactions_model = RowsModel(
            ["時間", "類型", "帳戶", "類別／項目", "金額"],
            _transaction_values,
        )
        self._build()
        self.reload_accounts()

    def _build(self) -> None:
        title = QLabel("餘額盤點")
        title.setObjectName("pageTitle")
        help_text = QLabel(
            "盤點只記錄實際看到的帳戶金額，不會直接入帳。"
            "補記兩次盤點之間的交易後，未解釋差額會自動重新計算。"
        )
        help_text.setObjectName("hintLabel")
        help_text.setWordWrap(True)
        self.observed_at.setCalendarPopup(True)
        self.observed_at.setDisplayFormat("yyyy/MM/dd HH:mm")
        self.amount.setPlaceholderText("例如：1200，可填 0")
        self.note.setPlaceholderText("可留空，例如：開啟程式時盤點")
        self.result.setObjectName("errorLabel")
        self.result.setWordWrap(True)
        self.summary.setObjectName("hintLabel")
        self.summary.setWordWrap(True)
        for label, value in (("有效", "active"), ("已作廢", "voided"), ("全部", "all")):
            self.status.addItem(label, value)

        create_button = QPushButton("新增盤點")
        update_button = QPushButton("更新所選盤點")
        void_button = QPushButton("作廢所選盤點")
        export_button = QPushButton("匯出盤點 CSV")
        refresh_button = QPushButton("重新整理")
        quick_button = QPushButton("補記交易")
        _set_button_role(create_button, "primary")
        _set_button_role(void_button, "danger")

        form = QFormLayout()
        form.addRow("帳戶", self.account)
        form.addRow("盤點時間", self.observed_at)
        form.addRow("目前金額（TWD）", self.amount)
        form.addRow("備註", self.note)
        form.addRow("列表狀態", self.status)
        form.addRow("", self.result)

        actions = QHBoxLayout()
        for button in (
            create_button,
            update_button,
            void_button,
            export_button,
            refresh_button,
            quick_button,
        ):
            actions.addWidget(button)
        actions.addStretch()

        _setup_table(self.table, self.model)
        _setup_table(self.transactions, self.transactions_model)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(help_text)
        layout.addLayout(form)
        layout.addLayout(actions)
        layout.addWidget(self.summary)
        layout.addWidget(QLabel("盤點紀錄"))
        layout.addWidget(self.table)
        layout.addWidget(QLabel("最近盤點差額期間內的交易"))
        layout.addWidget(self.transactions)

        self.account.currentIndexChanged.connect(self.refresh)
        self.status.currentIndexChanged.connect(self.refresh)
        create_button.clicked.connect(self.create_snapshot)
        update_button.clicked.connect(self.update_selected)
        void_button.clicked.connect(self.void_selected)
        export_button.clicked.connect(self.export_csv)
        refresh_button.clicked.connect(self.refresh)
        quick_button.clicked.connect(lambda: self.record_transaction_requested.emit())
        self.table.selectionModel().selectionChanged.connect(lambda *_: self.load_selected())

    def reload_accounts(self) -> None:
        _fill_combo(self.account, self.controller.account_options(), "name", "account_id")
        self.refresh()

    def refresh(self) -> None:
        account_id = self._account_id()
        if account_id is None:
            self.model.replace_rows([])
            self.transactions_model.replace_rows([])
            self.summary.setText("尚未建立帳戶。")
            return
        gaps = self.controller.list_balance_snapshots(
            account_id=account_id,
            status=str(self.status.currentData()),
            limit=50,
        )
        self.model.replace_rows(gaps)
        latest = self.controller.latest_balance_gap(account_id)
        if latest is None:
            self.summary.setText("此帳戶尚未盤點。可先輸入目前金額，之後再慢慢補記交易。")
            self.transactions_model.replace_rows([])
            return
        difference = int(latest["difference_minor"])
        sign_text = "完全吻合" if difference == 0 else latest["difference"]
        self.summary.setText(
            "最近盤點："
            f"{_display_datetime(str(latest['observed_at']))}；"
            f"實際 {latest['actual_balance']} TWD，"
            f"預期 {latest['expected_balance']} TWD，"
            f"未解釋差額 {sign_text} TWD。"
        )
        self.transactions_model.replace_rows(
            self.controller.list_balance_gap_transactions(
                account_id=account_id,
                period_start=cast(str | None, latest.get("period_start")),
                period_end=str(latest["period_end"]),
            )
        )

    def create_snapshot(self) -> None:
        account_id = self._account_id()
        if account_id is None:
            self.result.setText("請先建立帳戶。")
            return
        result = self.controller.create_balance_snapshot(
            account_id=account_id,
            observed_at=_iso_datetime(self.observed_at),
            actual_balance=self.amount.text().strip(),
            note=self.note.text().strip(),
        )
        self.result.setText(_result_message(result))
        if result.success:
            self.amount.clear()
            self.note.clear()
            self.observed_at.setDateTime(QDateTime.currentDateTime())
            self.changed.emit()
            self.refresh()

    def update_selected(self) -> None:
        item = self.model.selected_item(self.table)
        account_id = self._account_id()
        if item is None or account_id is None:
            self.result.setText("請先選擇要更新的盤點。")
            return
        result = self.controller.update_balance_snapshot(
            str(item["snapshot_id"]),
            account_id=account_id,
            observed_at=_iso_datetime(self.observed_at),
            actual_balance=self.amount.text().strip(),
            note=self.note.text().strip(),
        )
        self.result.setText(_result_message(result))
        if result.success:
            self.changed.emit()
            self.refresh()

    def void_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None or item["status"] != "active":
            return
        answer = QMessageBox.question(self, "確認作廢", "確定要作廢所選餘額盤點嗎？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        result = self.controller.void_balance_snapshot(str(item["snapshot_id"]))
        self.result.setText(_result_message(result))
        if result.success:
            self.changed.emit()
            self.refresh()

    def load_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None:
            return
        _select_data(self.account, item.get("account_id"))
        try:
            observed = datetime.fromisoformat(str(item["observed_at"])).astimezone(TAIPEI)
            self.observed_at.setDateTime(
                QDateTime.fromString(observed.strftime("%Y/%m/%d %H:%M"), "yyyy/MM/dd HH:mm")
            )
        except ValueError:
            pass
        self.amount.setText(_minor_text(item["actual_balance_minor"]))
        self.note.setText(str(item.get("note", "")))

    def export_csv(self) -> None:
        result = self.controller.export_balance_snapshots_csv()
        if result.success:
            self.result.setText(f"餘額盤點 CSV 已匯出：{result.details.get('path')}")
        else:
            self.result.setText(_result_message(result))

    def _account_id(self) -> str | None:
        value = self.account.currentData()
        return str(value) if isinstance(value, str) else None


class TransactionsPage(QWidget):
    duplicate_requested = Signal(dict)

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.table = QTableView()
        self.model = RowsModel(
            ["時間", "類型", "帳戶", "類別／項目", "金額", "備註", "狀態"],
            _transaction_values,
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
        _set_button_role(apply_button, "primary")
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
        _setup_table(self.table, self.model)
        edit_button = QPushButton("編輯／替換")
        duplicate_button = QPushButton("複製到快速記帳")
        void_button = QPushButton("作廢")
        _set_button_role(edit_button, "primary")
        _set_button_role(void_button, "danger")
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
        _fill_combo(
            self.account,
            self.controller.account_options(),
            "name",
            "account_id",
            first=("全部帳戶", None),
        )
        _fill_combo(
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
            QMessageBox.warning(self, "交易無法載入", _result_message(result))
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
            QMessageBox.warning(self, "無法作廢", _result_message(result))


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
        _fill_combo(self.account, accounts, "name", "account_id")
        _fill_combo(self.destination, accounts, "name", "account_id")
        _select_data(self.account, self.transaction["account_id"])
        _select_data(self.destination, self.transaction["destination_account_id"])
        if self.transaction["entry_type"] != "transfer":
            _fill_combo(
                self.category,
                self.controller.category_options(),
                "name",
                "category_id",
            )
            _select_data(self.category, self.transaction["category_id"])
            self._load_details()
            _select_data(self.detail, self.transaction["subcategory_id"])

    def _load_details(self) -> None:
        parent_id = self.category.currentData()
        children = (
            self.controller.category_options(str(parent_id))
            if isinstance(parent_id, str)
            else []
        )
        _fill_combo(self.detail, children, "name", "category_id")

    def save(self) -> None:
        common = {
            "occurred_at": _iso_datetime(self.occurred_at),
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
            self.error.setText(_result_message(result))


class CatalogPage(QWidget):
    changed = Signal()

    def __init__(self, controller: LedgerController, kind: str) -> None:
        super().__init__()
        self.controller = controller
        self.kind = kind
        headers = (
            ["帳戶", "類型", "幣別", "目前餘額", "狀態"]
            if kind == "account"
            else ["類別", "項目", "狀態"]
        )
        mapper = _account_values if kind == "account" else _category_values
        self.model = RowsModel(headers, mapper)
        self.table = QTableView()
        self._build()
        self.refresh()

    def _build(self) -> None:
        title = QLabel("帳戶" if self.kind == "account" else "類別／項目")
        title.setObjectName("pageTitle")
        add_button = QPushButton("新增帳戶" if self.kind == "account" else "新增類別")
        add_child = QPushButton("新增項目")
        rename = QPushButton("重新命名")
        toggle = QPushButton("封存／恢復所選項目")
        delete_button = QPushButton("刪除未使用")
        _set_button_role(add_button, "primary")
        _set_button_role(add_child, "primary")
        _set_button_role(delete_button, "danger")
        row = QHBoxLayout()
        row.addWidget(add_button)
        if self.kind == "category":
            row.addWidget(add_child)
        row.addWidget(rename)
        row.addWidget(toggle)
        row.addWidget(delete_button)
        row.addStretch()
        _setup_table(self.table, self.model)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addLayout(row)
        layout.addWidget(self.table)
        add_button.clicked.connect(self.add_item)
        add_child.clicked.connect(self.add_child)
        rename.clicked.connect(self.rename_selected)
        toggle.clicked.connect(self.toggle_selected)
        delete_button.clicked.connect(self.delete_selected)

    def refresh(self) -> None:
        if self.kind == "account":
            self.model.replace_rows(self.controller.account_options(include_archived=True))
            return
        rows: list[dict[str, Any]] = []
        parents = self.controller.category_options(include_archived=True)
        for parent in parents:
            children = self.controller.category_options(
                str(parent["category_id"]),
                include_archived=True,
            )
            if not children:
                rows.append({**parent, "parent_name": parent["name"]})
            for child in children:
                rows.append({**child, "parent_name": parent["name"]})
        self.model.replace_rows(rows)

    def add_item(self) -> None:
        name, accepted = QInputDialog.getText(
            self,
            "新增帳戶" if self.kind == "account" else "新增類別",
            "名稱",
        )
        if not accepted:
            return
        if self.kind == "account":
            balance, accepted = QInputDialog.getText(
                self,
                "新增帳戶",
                "期初餘額（TWD）",
                text="0",
            )
            if not accepted:
                return
            result = self.controller.create_account(name, balance)
        else:
            result = self.controller.create_category(name)
        self._finish(result)

    def add_child(self) -> None:
        parents = self.controller.category_options()
        if not parents:
            return
        labels = [str(item["name"]) for item in parents]
        selected, accepted = QInputDialog.getItem(
            self,
            "新增項目",
            "上層類別",
            labels,
            editable=False,
        )
        if not accepted:
            return
        name, accepted = QInputDialog.getText(self, "新增項目", "項目名稱")
        if accepted:
            parent_id = str(parents[labels.index(selected)]["category_id"])
            self._finish(self.controller.create_category(name, parent_id))

    def rename_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None or item["status"] != "active":
            return
        name, accepted = QInputDialog.getText(
            self,
            "重新命名",
            "名稱",
            text=str(item["name"]),
        )
        if not accepted:
            return
        result = (
            self.controller.rename_account(str(item["account_id"]), name)
            if self.kind == "account"
            else self.controller.rename_category(str(item["category_id"]), name)
        )
        self._finish(result)

    def toggle_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None:
            return
        active = item["status"] == "active"
        if self.kind == "account":
            result = (
                self.controller.archive_account(str(item["account_id"]))
                if active
                else self.controller.restore_account(str(item["account_id"]))
            )
        else:
            result = (
                self.controller.archive_category(str(item["category_id"]))
                if active
                else self.controller.restore_category(str(item["category_id"]))
            )
        self._finish(result)

    def delete_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None:
            return
        answer = QMessageBox.question(
            self,
            "確認刪除",
            "只會刪除完全未使用的設定項；已有歷史資料者請改用封存。是否繼續？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        result = (
            self.controller.delete_account(str(item["account_id"]))
            if self.kind == "account"
            else self.controller.delete_category(str(item["category_id"]))
        )
        self._finish(result)

    def _finish(self, result: Any) -> None:
        if not result.success:
            QMessageBox.warning(self, "操作失敗", _result_message(result))
            return
        self.refresh()
        self.changed.emit()


class MaintenancePage(QWidget):
    restored = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.list = QListWidget()
        self.result = QLabel()
        self.protect_restore = QCheckBox("還原前先建立備份")
        self._build()
        self.refresh()

    def _build(self) -> None:
        title = QLabel("備份與匯出")
        title.setObjectName("pageTitle")
        self.list.setObjectName("backupList")
        create = QPushButton("建立完整備份")
        validate = QPushButton("驗證所選備份")
        restore = QPushButton("還原所選備份")
        external = QPushButton("選擇外部備份資料夾")
        export = QPushButton("匯出交易 CSV")
        _set_button_role(create, "primary")
        _set_button_role(restore, "danger")
        buttons = QHBoxLayout()
        for widget in (create, validate, restore, external, export):
            buttons.addWidget(widget)
        self.result.setWordWrap(True)
        self.result.setObjectName("hintLabel")
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addLayout(buttons)
        layout.addWidget(self.protect_restore)
        layout.addWidget(self.list)
        layout.addWidget(self.result)
        create.clicked.connect(self.create_backup)
        validate.clicked.connect(self.validate_selected)
        restore.clicked.connect(self.restore_selected)
        external.clicked.connect(self.restore_external)
        export.clicked.connect(self.export_csv)

    def refresh(self) -> None:
        self.list.clear()
        for backup in self.controller.list_backups():
            state = "可用" if backup["valid"] else f"無效：{backup['error_code']}"
            item_text = f"{backup.get('created_at', '')}｜{state}｜{backup['path']}"
            self.list.addItem(item_text)
            self.list.item(self.list.count() - 1).setData(
                Qt.ItemDataRole.UserRole,
                backup["path"],
            )

    def create_backup(self) -> None:
        try:
            path = self.controller.create_backup()
            self.result.setText(f"備份已建立：{path}")
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "備份失敗", str(exc))

    def validate_selected(self) -> None:
        path = self._selected_path()
        if path is None:
            return
        result = self.controller.validate_backup(path)
        self.result.setText(
            "備份驗證通過。"
            if result["valid"]
            else f"備份不可用：{result['error_code']}"
        )

    def restore_selected(self) -> None:
        path = self._selected_path()
        if path is not None:
            self._restore(path)

    def restore_external(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "選擇含 manifest 的備份資料夾")
        if selected:
            self._restore(Path(selected))

    def _restore(self, path: Path) -> None:
        validation = self.controller.validate_backup(path)
        if not validation["valid"]:
            QMessageBox.warning(self, "無法還原", str(validation["error_code"]))
            return
        answer = QMessageBox.question(
            self,
            "確認還原",
            "還原前會先備份目前資料。確定繼續嗎？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.controller.restore_backup(
                path,
                create_backup_first=self.protect_restore.isChecked(),
            )
            self.result.setText("備份已還原。")
            self.restored.emit()
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "還原失敗", str(exc))

    def export_csv(self) -> None:
        try:
            self.result.setText(f"CSV 已匯出：{self.controller.export_csv()}")
        except Exception as exc:
            QMessageBox.warning(self, "匯出失敗", str(exc))

    def _selected_path(self) -> Path | None:
        item = self.list.currentItem()
        return Path(str(item.data(Qt.ItemDataRole.UserRole))) if item else None


class SettingsPage(QWidget):
    saved = Signal()

    def __init__(self, controller: LedgerController, paths: AppPaths) -> None:
        super().__init__()
        self.controller = controller
        self.paths = paths
        self.account = QComboBox()
        self.flow = QComboBox()
        self.page_size = QComboBox()
        self.balance_snapshot_reminder = QCheckBox("每日提醒記錄預設帳戶目前金額")
        self.result = QLabel()
        self._build()
        self.reload()

    def _build(self) -> None:
        title = QLabel("一般設定")
        title.setObjectName("pageTitle")
        for key in ("expense", "income", "transfer"):
            self.flow.addItem(ENTRY_NAMES[key], key)
        for size in (20, 50, 100):
            self.page_size.addItem(f"{size} 筆", size)
        save = QPushButton("儲存設定")
        _set_button_role(save, "primary")
        form = QFormLayout()
        form.addRow("預設帳戶", self.account)
        form.addRow("預設流向", self.flow)
        form.addRow("交易列表每頁", self.page_size)
        form.addRow("餘額盤點提醒", self.balance_snapshot_reminder)
        form.addRow("固定幣別", QLabel("TWD"))
        form.addRow("固定時區", QLabel("Asia/Taipei"))
        form.addRow("資料庫", QLabel(str(self.paths.database_path)))
        form.addRow("", save)
        form.addRow("", self.result)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addLayout(form)
        layout.addStretch()
        save.clicked.connect(self.save)

    def reload(self) -> None:
        _fill_combo(
            self.account,
            self.controller.account_options(),
            "name",
            "account_id",
        )
        settings = self.controller.get_settings()
        _select_data(self.account, settings.default_account_id)
        _select_data(self.flow, settings.default_entry_type)
        _select_data(self.page_size, settings.transactions_page_size)
        self.balance_snapshot_reminder.setChecked(settings.balance_snapshot_reminder)

    def save(self) -> None:
        result = self.controller.save_settings(
            ApplicationSettings(
                default_account_id=str(self.account.currentData()),
                default_entry_type=str(self.flow.currentData()),
                transactions_page_size=int(self.page_size.currentData()),
                balance_snapshot_reminder=self.balance_snapshot_reminder.isChecked(),
            )
        )
        self.result.setText(_result_message(result))
        if result.success:
            self.saved.emit()


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
        form = QFormLayout()
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
        _fill_combo(self.account, accounts, "name", "account_id")
        _fill_combo(self.destination, accounts, "name", "account_id")
        _fill_combo(
            self.category,
            self.controller.category_options(),
            "name",
            "category_id",
        )
        self._reload_details()
        if self.current:
            self.name.setText(str(self.current["name"]))
            _select_data(self.flow, self.current["entry_type"])
            _select_data(self.account, self.current["account_id"])
            _select_data(self.destination, self.current.get("destination_account_id"))
            self._select_category(self.current.get("category_id"))
            if self.current.get("amount_minor") is not None:
                self.amount.setText(_minor_text(int(self.current["amount_minor"])))
            self.description.setText(str(self.current.get("description", "")))
            if self.schedule:
                _select_data(self.frequency, self.current["frequency"])
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
        self.destination.setVisible(transfer)
        self.category.setVisible(not transfer)
        self.detail.setVisible(not transfer)

    def _reload_details(self) -> None:
        parent_id = self.category.currentData()
        children = (
            self.controller.category_options(str(parent_id))
            if isinstance(parent_id, str)
            else []
        )
        _fill_combo(self.detail, children, "name", "category_id")

    def _select_category(self, category_id: object) -> None:
        if not isinstance(category_id, str):
            return
        for index in range(self.category.count()):
            parent_id = str(self.category.itemData(index))
            children = self.controller.category_options(parent_id)
            if any(str(item["category_id"]) == category_id for item in children):
                self.category.setCurrentIndex(index)
                self._reload_details()
                _select_data(self.detail, category_id)
                return


class AutomationPage(QWidget):
    apply_requested = Signal(dict)
    changed = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.templates = QTableView()
        self.template_model = RowsModel(
            ["名稱", "類型", "金額", "備註"],
            _template_values,
        )
        self.schedules = QTableView()
        self.schedule_model = RowsModel(
            ["名稱", "類型", "週期", "下次日期", "結束日期"],
            _schedule_values,
        )
        self._build()
        self.refresh()

    def _build(self) -> None:
        title = QLabel("模板與排程")
        title.setObjectName("pageTitle")
        tabs = QTabWidget()
        tabs.setObjectName("contentTabs")
        template_tab = QWidget()
        template_buttons = QHBoxLayout()
        for label, handler in (
            ("新增模板", lambda: self.edit_template(None)),
            ("編輯模板", self.edit_selected_template),
            ("套用到快速記帳", self.apply_template),
            ("封存模板", self.archive_template),
        ):
            button = QPushButton(label)
            if label.startswith(("新增", "套用")):
                _set_button_role(button, "primary")
            if label.startswith("封存"):
                _set_button_role(button, "danger")
            button.clicked.connect(handler)
            template_buttons.addWidget(button)
        _setup_table(self.templates, self.template_model)
        template_layout = QVBoxLayout(template_tab)
        template_layout.addLayout(template_buttons)
        template_layout.addWidget(self.templates)

        schedule_tab = QWidget()
        schedule_buttons = QHBoxLayout()
        for label, handler in (
            ("新增排程", lambda: self.edit_schedule(None)),
            ("編輯排程", self.edit_selected_schedule),
            ("封存排程", self.archive_schedule),
            ("產生到期待確認項目", self.generate_due),
        ):
            button = QPushButton(label)
            if label.startswith(("新增", "產生")):
                _set_button_role(button, "primary")
            if label.startswith("封存"):
                _set_button_role(button, "danger")
            button.clicked.connect(handler)
            schedule_buttons.addWidget(button)
        _setup_table(self.schedules, self.schedule_model)
        schedule_layout = QVBoxLayout(schedule_tab)
        schedule_layout.addLayout(schedule_buttons)
        schedule_layout.addWidget(self.schedules)
        tabs.addTab(template_tab, "模板")
        tabs.addTab(schedule_tab, "週期排程")
        layout = QVBoxLayout(self)
        layout.addWidget(title)
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
            QMessageBox.warning(self, "產生失敗", _result_message(result))

    def _finish(self, result: Any) -> None:
        if not result.success:
            QMessageBox.warning(self, "操作失敗", _result_message(result))
            return
        self.refresh()
        self.changed.emit()


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
            _minor_text(item["amount_minor"]) if item.get("amount_minor") is not None else ""
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
        _fill_combo(self.account, accounts, "name", "account_id")
        _fill_combo(self.destination, accounts, "name", "account_id")
        _select_data(self.account, self.item["account_id"])
        _select_data(self.destination, self.item.get("destination_account_id"))
        if self.item["entry_type"] != "transfer":
            _fill_combo(
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
            _select_data(self.detail, self.item.get("category_id"))

    def _reload_details(self) -> None:
        parent_id = self.category.currentData()
        children = (
            self.controller.category_options(str(parent_id))
            if isinstance(parent_id, str)
            else []
        )
        _fill_combo(self.detail, children, "name", "category_id")

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
            self.error.setText(_result_message(result))
            return
        confirmed = self.controller.confirm_occurrence(str(self.item["occurrence_id"]))
        if confirmed.success:
            self.accept()
        else:
            self.error.setText(_result_message(confirmed))


class PendingPage(QWidget):
    changed = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.table = QTableView()
        self.model = RowsModel(
            ["到期日", "排程", "類型", "金額", "狀態說明"],
            _occurrence_values,
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
        _set_button_role(edit_confirm, "primary")
        _set_button_role(batch, "primary")
        _set_button_role(generate, "primary")
        row = QHBoxLayout()
        for widget in (edit_confirm, skip, batch, generate):
            row.addWidget(widget)
        row.addStretch()
        _setup_table(self.table, self.model)
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
            QMessageBox.warning(self, "無法略過", _result_message(result))

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
            QMessageBox.warning(self, "產生失敗", _result_message(result))
            return
        generated = int(result.details.get("generated", 0))
        message = f"已產生 {generated} 期。"
        if result.details.get("has_more"):
            message += "仍有更多漏期，請再次按下繼續產生。"
        QMessageBox.information(self, "產生完成", message)
        self.refresh()


class PathSettingsPage(QWidget):
    changed = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.ledger_dir = QLineEdit()
        self.backup_dir = QLineEdit()
        self.result = QLabel()
        self._build()
        self.reload()

    def _build(self) -> None:
        title = QLabel("資料路徑")
        title.setObjectName("pageTitle")
        self.result.setWordWrap(True)
        self.result.setObjectName("hintLabel")
        browse_ledger = QPushButton("選擇記帳資料路徑")
        browse_backup = QPushButton("選擇備份路徑")
        switch_button = QPushButton("切換到既有資料")
        move_button = QPushButton("搬移目前資料")
        _set_button_role(switch_button, "primary")
        _set_button_role(move_button, "primary")

        form = QFormLayout()
        form.addRow("記帳資料路徑", self.ledger_dir)
        form.addRow("", browse_ledger)
        form.addRow("備份路徑", self.backup_dir)
        form.addRow("", browse_backup)
        actions = QHBoxLayout()
        actions.addWidget(switch_button)
        actions.addWidget(move_button)
        actions.addStretch()

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addLayout(form)
        layout.addLayout(actions)
        hint = QLabel("記帳資料會存放 ledger.sqlite3；備份會建立在獨立備份路徑下。備份路徑不可與資料路徑相同或互相包含。")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addWidget(self.result)
        layout.addStretch()

        browse_ledger.clicked.connect(lambda: self._choose(self.ledger_dir))
        browse_backup.clicked.connect(lambda: self._choose(self.backup_dir))
        switch_button.clicked.connect(lambda: self._save(move_current=False))
        move_button.clicked.connect(lambda: self._save(move_current=True))

    def reload(self) -> None:
        settings = self.controller.get_path_settings()
        self.ledger_dir.setText(str(settings.ledger_dir))
        self.backup_dir.setText(str(settings.backup_dir))

    def _choose(self, target: QLineEdit) -> None:
        selected = QFileDialog.getExistingDirectory(self, "選擇資料夾")
        if selected:
            target.setText(selected)

    def _save(self, *, move_current: bool) -> None:
        result = self.controller.save_path_settings(
            ledger_dir=Path(self.ledger_dir.text().strip()),
            backup_dir=Path(self.backup_dir.text().strip()),
            move_current=move_current,
        )
        self.result.setText(_result_message(result))
        if result.success:
            self.reload()
            self.changed.emit()


class ResetPage(QWidget):
    reset_done = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.backup_first = QCheckBox("重製前先建立備份")
        self.result = QLabel()
        self._build()

    def _build(self) -> None:
        title = QLabel("重製與還原")
        title.setObjectName("pageTitle")
        reset_button = QPushButton("重製目前記帳資料")
        _set_button_role(reset_button, "danger")
        self.result.setWordWrap(True)
        self.result.setObjectName("hintLabel")
        hint = QLabel("重製會移除目前記帳資料庫並重新建立預設帳戶與類別；不會刪除備份資料夾。")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.backup_first)
        layout.addWidget(reset_button)
        layout.addWidget(self.result)
        layout.addStretch()
        reset_button.clicked.connect(self.reset)

    def reset(self) -> None:
        answer = QMessageBox.question(
            self,
            "確認重製",
            "這會清空目前記帳資料並重新初始化。是否繼續？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.controller.reset_ledger(
                create_backup_first=self.backup_first.isChecked()
            )
            self.result.setText("記帳資料已重製。")
            self.reset_done.emit()
        except Exception as exc:
            QMessageBox.warning(self, "重製失敗", str(exc))


class OperationSettingsPage(QWidget):
    apply_requested = Signal(dict)
    changed = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.accounts = CatalogPage(controller, "account")
        self.categories = CatalogPage(controller, "category")
        self.automation = AutomationPage(controller)
        self._build()

    def _build(self) -> None:
        tabs = QTabWidget()
        tabs.setObjectName("settingsTabs")
        tabs.addTab(self.accounts, "帳戶")
        tabs.addTab(self.categories, "類別")
        tabs.addTab(self.automation, "模板與週期排程")
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        self.accounts.changed.connect(self.changed.emit)
        self.categories.changed.connect(self.changed.emit)
        self.automation.changed.connect(self.changed.emit)
        self.automation.apply_requested.connect(self.apply_requested.emit)

    def refresh(self) -> None:
        self.accounts.refresh()
        self.categories.refresh()
        self.automation.refresh()


class SystemSettingsPage(QWidget):
    saved = Signal()
    restored = Signal()
    paths_changed = Signal()

    def __init__(self, controller: LedgerController, paths: AppPaths) -> None:
        super().__init__()
        self.general = SettingsPage(controller, paths)
        self.paths = PathSettingsPage(controller)
        self.maintenance = MaintenancePage(controller)
        self.reset = ResetPage(controller)
        self._build()

    def _build(self) -> None:
        tabs = QTabWidget()
        tabs.setObjectName("settingsTabs")
        tabs.addTab(self.general, "一般設定")
        tabs.addTab(self.paths, "資料路徑")
        tabs.addTab(self.maintenance, "備份與還原")
        tabs.addTab(self.reset, "重製與還原")
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        self.general.saved.connect(self.saved.emit)
        self.paths.changed.connect(self.paths_changed.emit)
        self.maintenance.restored.connect(self.restored.emit)
        self.reset.reset_done.connect(self.restored.emit)

    def reload(self) -> None:
        self.general.reload()
        self.paths.reload()
        self.maintenance.refresh()


class MainWindow(QMainWindow):
    def __init__(self, paths: AppPaths) -> None:
        super().__init__()
        self.controller = LedgerController(paths)
        self.navigation = QListWidget()
        self.pages = QStackedWidget()
        self.quick = QuickEntryPage(self.controller)
        self.balance = BalanceSnapshotPage(self.controller)
        self.pending = PendingPage(self.controller)
        self.transactions = TransactionsPage(self.controller)
        self.operation_settings = OperationSettingsPage(self.controller)
        self.system_settings = SystemSettingsPage(self.controller, paths)
        self._build(paths)
        self.refresh_pending_badge()
        self._show_balance_snapshot_reminder()

    def _build(self, paths: AppPaths) -> None:
        self.setWindowTitle("TagCor Ledger")
        self.resize(1280, 760)
        app = QApplication.instance()
        if app is not None:
            apply_dark_theme(cast(QApplication, app))
        labels = [
            "快速記帳",
            "餘額盤點",
            "待確認",
            "交易紀錄",
            "操作設定",
            "系統設定",
        ]
        widgets: list[QWidget] = [
            self.quick,
            self.balance,
            self.pending,
            self.transactions,
            self.operation_settings,
            self.system_settings,
        ]
        self.navigation.setObjectName("sidebarNavigation")
        self.pages.setObjectName("contentStack")
        self.navigation.addItems(labels)
        for page in widgets:
            page.setObjectName("pageSurface")
            self.pages.addWidget(page)
        self.navigation.setFixedWidth(180)
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.setCurrentRow(0)
        layout = QHBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(16)
        layout.addWidget(self.navigation)
        layout.addWidget(self.pages, 1)
        content = QWidget()
        content.setObjectName("appShell")
        content.setLayout(layout)
        self.setCentralWidget(content)
        self.statusBar().showMessage(f"資料庫：{paths.database_path}")

        self.quick.saved.connect(self._transaction_changed)
        self.balance.changed.connect(self._balance_changed)
        self.balance.record_transaction_requested.connect(self._focus_new)
        self.transactions.duplicate_requested.connect(self._prefill_quick)
        self.operation_settings.apply_requested.connect(self._prefill_quick)
        self.operation_settings.changed.connect(self._catalog_changed)
        self.pending.changed.connect(self.refresh_pending_badge)
        self.system_settings.restored.connect(self._restored)
        self.system_settings.saved.connect(self._settings_changed)
        self.system_settings.paths_changed.connect(self._restored)
        self._add_shortcuts()

    def _add_shortcuts(self) -> None:
        new_action = QAction("新增交易", self)
        new_action.setShortcut(QKeySequence("Ctrl+N"))
        new_action.triggered.connect(self._focus_new)
        save_action = QAction("儲存交易", self)
        save_action.setShortcut(QKeySequence("Ctrl+S"))
        save_action.triggered.connect(self.quick.submit)
        clear_action = QAction("清除", self)
        clear_action.setShortcut(QKeySequence("Esc"))
        clear_action.triggered.connect(self.quick.clear_form)
        self.addActions([new_action, save_action, clear_action])

    def _focus_new(self) -> None:
        self.navigation.setCurrentRow(0)
        self.quick.amount.setFocus()

    def _prefill_quick(self, draft: dict[str, Any]) -> None:
        self.quick.apply_draft(draft)
        self.navigation.setCurrentRow(0)

    def _transaction_changed(self) -> None:
        self.transactions.first_page()
        self.balance.refresh()

    def _balance_changed(self) -> None:
        self.balance.refresh()

    def _catalog_changed(self) -> None:
        self.quick.reload_options()
        self.balance.reload_accounts()
        self.transactions.reload_filters()
        self.system_settings.reload()
        self.operation_settings.refresh()
        self.pending.refresh()

    def _automation_changed(self) -> None:
        self.operation_settings.refresh()
        self.pending.refresh()

    def _settings_changed(self) -> None:
        self.quick.apply_defaults()
        self.transactions.first_page()
        self.balance.reload_accounts()
        self._show_balance_snapshot_reminder()

    def _restored(self) -> None:
        self.statusBar().showMessage(f"資料庫位置：{self.controller.paths.database_path}")
        self.quick.reload_options()
        self.quick.apply_defaults()
        self.balance.reload_accounts()
        self.transactions.reload_filters()
        self.transactions.first_page()
        self.operation_settings.refresh()
        self.pending.refresh()
        self.system_settings.reload()

    def refresh_pending_badge(self) -> None:
        count = len(self.controller.list_pending())
        item = self.navigation.item(2)
        if item is not None:
            item.setText(f"待確認（{count}）")

    def _show_balance_snapshot_reminder(self) -> None:
        if self.controller.refresh_balance_snapshot_reminder_due():
            self.statusBar().showMessage(
                "提醒：今天尚未記錄預設帳戶的目前金額，可到「餘額盤點」新增盤點。",
                10000,
            )


def _fill_combo(
    combo: QComboBox,
    items: list[dict[str, Any]],
    label_key: str,
    value_key: str,
    *,
    first: tuple[str, Any] | None = None,
) -> None:
    current = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    if first is not None:
        combo.addItem(first[0], first[1])
    for item in items:
        combo.addItem(str(item[label_key]), item[value_key])
    _select_data(combo, current)
    combo.blockSignals(False)


def _select_data(combo: QComboBox, value: object) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)


def _iso_datetime(widget: QDateTimeEdit) -> str:
    value = cast(datetime, widget.dateTime().toPython())
    if value.tzinfo is None:
        value = value.replace(tzinfo=TAIPEI)
    return value.astimezone(TAIPEI).isoformat(timespec="seconds")


def _minor_text(value: int | str) -> str:
    return str(int(value))


def _result_message(result: Any) -> str:
    reason = str(result.details.get("reason", "")).strip()
    return f"{result.message}{'（' + reason + '）' if reason else ''}"


def _display_datetime(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%Y/%m/%d %H:%M")
    except ValueError:
        return value


def _balance_gap_values(item: dict[str, Any]) -> list[str]:
    return [
        _display_datetime(str(item["observed_at"])),
        str(item["account_name"]),
        f"{item['actual_balance']} {item['currency']}",
        f"{item['expected_balance']} {item['currency']}",
        f"{item['difference']} {item['currency']}",
        str(item["note"]),
        STATUS_NAMES.get(str(item["status"]), str(item["status"])),
    ]


def _transaction_values(item: dict[str, Any]) -> list[str]:
    category = " / ".join(
        str(part)
        for part in (item.get("category_name"), item.get("subcategory_name"))
        if part
    )
    account = str(item["account_name"])
    if item["entry_type"] == "transfer":
        account += f" → {item.get('destination_account_name') or ''}"
    return [
        _display_datetime(str(item["occurred_at"])),
        str(item["entry_type_name"]),
        account,
        category,
        f"{item['amount']} {item['currency']}",
        str(item["description"]),
        STATUS_NAMES.get(str(item["status"]), str(item["status"])),
    ]


def _account_values(item: dict[str, Any]) -> list[str]:
    return [
        str(item["name"]),
        str(item["account_type"]),
        str(item["currency"]),
        _minor_text(item["balance_minor"]),
        "使用中" if item["status"] == "active" else "已封存",
    ]


def _category_values(item: dict[str, Any]) -> list[str]:
    return [
        str(item.get("parent_name", "")),
        str(item["name"]) if int(item["level"]) == 2 else "",
        "使用中" if item["status"] == "active" else "已封存",
    ]


def _template_values(item: dict[str, Any]) -> list[str]:
    amount = (
        _minor_text(item["amount_minor"])
        if item.get("amount_minor") is not None
        else "套用時輸入"
    )
    return [
        str(item["name"]),
        ENTRY_NAMES.get(str(item["entry_type"]), str(item["entry_type"])),
        amount,
        str(item["description"]),
    ]


def _schedule_values(item: dict[str, Any]) -> list[str]:
    interval = int(item["interval_count"])
    frequency = FREQUENCY_NAMES.get(str(item["frequency"]), str(item["frequency"]))
    return [
        str(item["name"]),
        ENTRY_NAMES.get(str(item["entry_type"]), str(item["entry_type"])),
        f"每 {interval} {frequency}",
        str(item["next_due_date"]),
        str(item.get("end_date") or "無"),
    ]


def _occurrence_values(item: dict[str, Any]) -> list[str]:
    amount = (
        _minor_text(item["amount_minor"])
        if item.get("amount_minor") is not None
        else "尚未填寫"
    )
    return [
        str(item["due_date"]),
        str(item["schedule_name"]),
        ENTRY_NAMES.get(str(item["entry_type"]), str(item["entry_type"])),
        amount,
        str(item.get("invalid_reason") or "可確認"),
    ]
