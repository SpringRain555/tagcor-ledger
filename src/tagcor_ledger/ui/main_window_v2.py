"""Traditional Chinese PySide6 desktop interface."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from PySide6.QtCore import (
    QAbstractTableModel,
    QDateTime,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.app.resources import read_text_resource
from tagcor_ledger.ui.ledger_controller import LedgerController


HEADERS = ["時間", "類型", "帳戶", "分類", "對象／商家", "金額", "備註", "狀態"]


class TransactionTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict[str, Any]] = []

    def replace_rows(self, rows: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(  # noqa: N802
        self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()
    ) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(  # noqa: N802
        self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()
    ) -> int:
        return 0 if parent.isValid() else len(HEADERS)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row = self.rows[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return row
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        category = " / ".join(
            part for part in (row.get("category_name"), row.get("subcategory_name")) if part
        )
        values = [
            _display_datetime(str(row["occurred_at"])),
            row["entry_type_name"],
            (
                f"{row['account_name']} → {row.get('destination_account_name') or ''}"
                if row["entry_type"] == "transfer"
                else row["account_name"]
            ),
            category,
            row["payee_name"],
            f"{row['amount']} {row['currency']}",
            row["description"],
            "有效" if row["status"] == "active" else "已作廢",
        ]
        return values[index.column()]

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[section]
        return super().headerData(section, orientation, role)


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
        self.payee = QLineEdit()
        self.description = QLineEdit()
        self.error_label = QLabel()
        self.save_button = QPushButton("儲存交易")
        self._build()
        self.reload_options()

    def _build(self) -> None:
        title = QLabel("快速記帳")
        title.setObjectName("pageTitle")
        self.flow.addItem("支出", "expense")
        self.flow.addItem("收入", "income")
        self.flow.addItem("轉帳", "transfer")
        self.occurred_at.setCalendarPopup(True)
        self.occurred_at.setDisplayFormat("yyyy/MM/dd HH:mm")
        self.amount.setPlaceholderText("例如：120")
        self.payee.setPlaceholderText("例如：便利商店")
        self.description.setPlaceholderText("可留空")
        self.error_label.setObjectName("errorLabel")
        self.error_label.setWordWrap(True)

        form = QFormLayout()
        form.addRow("流向", self.flow)
        form.addRow("帳戶", self.account)
        form.addRow("轉入帳戶", self.destination)
        form.addRow("分類", self.category)
        form.addRow("細項", self.detail)
        form.addRow("時間", self.occurred_at)
        form.addRow("對象／商家", self.payee)
        form.addRow("金額（TWD）", self.amount)
        form.addRow("備註", self.description)
        form.addRow("", self.error_label)
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
        accounts = self.controller.account_options()
        for combo in (self.account, self.destination):
            current = combo.currentData()
            combo.clear()
            for account in accounts:
                combo.addItem(str(account["name"]), str(account["account_id"]))
            index = combo.findData(current)
            if index >= 0:
                combo.setCurrentIndex(index)
        self.category.clear()
        for category in self.controller.category_options():
            self.category.addItem(str(category["name"]), str(category["category_id"]))
        self._reload_details()

    def clear_form(self) -> None:
        self.occurred_at.setDateTime(QDateTime.currentDateTime())
        self.amount.clear()
        self.payee.clear()
        self.description.clear()
        self.error_label.clear()
        self.amount.setFocus()

    def submit(self) -> None:
        result = self.controller.submit(
            occurred_at=cast(datetime, self.occurred_at.dateTime().toPython()).astimezone().isoformat(
                timespec="seconds"
            ),
            entry_type=str(self.flow.currentData()),
            amount=self.amount.text().strip(),
            account_id=str(self.account.currentData()),
            destination_account_id=(
                str(self.destination.currentData()) if self.destination.isVisible() else None
            ),
            category_id=(str(self.detail.currentData()) if self.detail.isVisible() else None),
            payee_name=self.payee.text().strip(),
            description=self.description.text().strip(),
        )
        if result.success:
            self.error_label.setText("交易已儲存。")
            self.clear_form()
            self.saved.emit()
            return
        reason = str(result.details.get("reason", "")).strip()
        self.error_label.setText(f"{result.message}{'（' + reason + '）' if reason else ''}")

    def _sync_flow(self) -> None:
        transfer = self.flow.currentData() == "transfer"
        self.destination.setVisible(transfer)
        self.category.setVisible(not transfer)
        self.detail.setVisible(not transfer)
        labels = self.findChildren(QLabel)
        for label in labels:
            if label.text() == "轉入帳戶":
                label.setVisible(transfer)
            if label.text() in {"分類", "細項"}:
                label.setVisible(not transfer)

    def _reload_details(self) -> None:
        parent_id = self.category.currentData()
        self.detail.clear()
        if isinstance(parent_id, str):
            for category in self.controller.category_options(parent_id):
                self.detail.addItem(str(category["name"]), str(category["category_id"]))


class TransactionsPage(QWidget):
    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.model = TransactionTableModel()
        self.table = QTableView()
        self.search = QLineEdit()
        self.next_button = QPushButton("下一頁")
        self.edit_button = QPushButton("編輯所選交易")
        self.void_button = QPushButton("作廢所選交易")
        self.page_cursor: dict[str, str] | None = None
        self._build()
        self.refresh()

    def _build(self) -> None:
        title = QLabel("交易紀錄")
        title.setObjectName("pageTitle")
        self.search.setPlaceholderText("搜尋對象、備註、分類或帳戶")
        search_button = QPushButton("搜尋")
        search_row = QHBoxLayout()
        search_row.addWidget(self.search)
        search_row.addWidget(search_button)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        button_row = QHBoxLayout()
        button_row.addWidget(self.edit_button)
        button_row.addWidget(self.void_button)
        button_row.addStretch()
        button_row.addWidget(self.next_button)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addLayout(search_row)
        layout.addWidget(self.table)
        layout.addLayout(button_row)
        search_button.clicked.connect(self.search_first_page)
        self.search.returnPressed.connect(self.search_first_page)
        self.next_button.clicked.connect(self.next_page)
        self.edit_button.clicked.connect(self.edit_selected)
        self.void_button.clicked.connect(self.void_selected)

    def search_first_page(self) -> None:
        self.page_cursor = None
        self.refresh()

    def next_page(self) -> None:
        if self.page_cursor is not None:
            self.refresh()

    def refresh(self) -> None:
        result = self.controller.list_transactions(
            search=self.search.text().strip(),
            cursor=self.page_cursor,
        )
        if not result.success:
            QMessageBox.warning(self, "交易無法載入", result.message)
            return
        self.model.replace_rows(list(result.details.get("transactions", [])))
        next_cursor = result.details.get("next_cursor")
        self.page_cursor = dict(next_cursor) if isinstance(next_cursor, dict) else None
        self.next_button.setEnabled(self.page_cursor is not None)

    def void_selected(self) -> None:
        selection = self.table.selectionModel().selectedRows()
        if not selection:
            return
        row = self.model.rows[selection[0].row()]
        if QMessageBox.question(self, "確認作廢", "確定要作廢所選交易嗎？") != QMessageBox.StandardButton.Yes:
            return
        result = self.controller.void_transaction(str(row["transaction_id"]))
        if not result.success:
            QMessageBox.warning(self, "無法作廢", result.message)
            return
        self.search_first_page()

    def edit_selected(self) -> None:
        selection = self.table.selectionModel().selectedRows()
        if not selection:
            return
        row = self.model.rows[selection[0].row()]
        if row["entry_type"] == "transfer":
            QMessageBox.information(
                self,
                "轉帳編輯",
                "首輪請先作廢轉帳，再重新建立正確交易。",
            )
            return
        dialog = EditTransactionDialog(self.controller, row, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.search_first_page()


class EditTransactionDialog(QDialog):
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
        self.category = QComboBox()
        self.detail = QComboBox()
        self.occurred_at = QDateTimeEdit()
        self.amount = QLineEdit(str(transaction["amount"]))
        self.payee = QLineEdit(str(transaction["payee_name"]))
        self.description = QLineEdit(str(transaction["description"]))
        self.error = QLabel()
        self._build()
        self._load_options()

    def _build(self) -> None:
        self.setWindowTitle("編輯交易")
        self.occurred_at.setCalendarPopup(True)
        self.occurred_at.setDisplayFormat("yyyy/MM/dd HH:mm")
        self.occurred_at.setDateTime(
            QDateTime.fromString(
                str(self.transaction["occurred_at"]),
                Qt.DateFormat.ISODate,
            )
        )
        self.error.setObjectName("errorLabel")
        form = QFormLayout()
        form.addRow("帳戶", self.account)
        form.addRow("分類", self.category)
        form.addRow("細項", self.detail)
        form.addRow("時間", self.occurred_at)
        form.addRow("對象／商家", self.payee)
        form.addRow("金額（TWD）", self.amount)
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
        self.category.currentIndexChanged.connect(self._load_details)

    def _load_options(self) -> None:
        for account in self.controller.account_options():
            self.account.addItem(str(account["name"]), str(account["account_id"]))
        account_index = self.account.findData(self.transaction["account_id"])
        if account_index >= 0:
            self.account.setCurrentIndex(account_index)
        for category in self.controller.category_options():
            self.category.addItem(str(category["name"]), str(category["category_id"]))
        category_index = self.category.findData(self.transaction["category_id"])
        if category_index >= 0:
            self.category.setCurrentIndex(category_index)
        self._load_details()
        detail_index = self.detail.findData(self.transaction["subcategory_id"])
        if detail_index >= 0:
            self.detail.setCurrentIndex(detail_index)

    def _load_details(self) -> None:
        current = self.detail.currentData()
        self.detail.clear()
        parent_id = self.category.currentData()
        if isinstance(parent_id, str):
            for detail in self.controller.category_options(parent_id):
                self.detail.addItem(str(detail["name"]), str(detail["category_id"]))
        current_index = self.detail.findData(current)
        if current_index >= 0:
            self.detail.setCurrentIndex(current_index)

    def save(self) -> None:
        result = self.controller.update_transaction(
            transaction_id=str(self.transaction["transaction_id"]),
            expected_revision=int(self.transaction["revision"]),
            occurred_at=cast(datetime, self.occurred_at.dateTime().toPython())
            .astimezone()
            .isoformat(timespec="seconds"),
            amount=self.amount.text().strip(),
            account_id=str(self.account.currentData()),
            category_id=str(self.detail.currentData()),
            payee_name=self.payee.text().strip(),
            description=self.description.text().strip(),
        )
        if result.success:
            self.accept()
            return
        self.error.setText(result.message)


class AccountsPage(QWidget):
    changed = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.table = QTableView()
        self.model = SimpleRowsModel(["帳戶", "類型", "幣別", "目前餘額", "狀態"])
        self._build()
        self.refresh()

    def _build(self) -> None:
        title = QLabel("帳戶")
        title.setObjectName("pageTitle")
        add_button = QPushButton("新增帳戶")
        rename_button = QPushButton("重新命名")
        archive_button = QPushButton("封存所選帳戶")
        row = QHBoxLayout()
        row.addWidget(add_button)
        row.addWidget(rename_button)
        row.addWidget(archive_button)
        row.addStretch()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addLayout(row)
        layout.addWidget(self.table)
        add_button.clicked.connect(self.add_account)
        rename_button.clicked.connect(self.rename_selected)
        archive_button.clicked.connect(self.archive_selected)

    def refresh(self) -> None:
        result = self.controller.accounts.list(include_archived=True)
        rows = list(result.details.get("accounts", []))
        self.model.replace_rows(
            rows,
            lambda item: [
                item["name"],
                item["account_type"],
                item["currency"],
                str(item["balance_minor"]),
                "使用中" if item["status"] == "active" else "已封存",
            ],
        )

    def add_account(self) -> None:
        name, accepted = QInputDialog.getText(self, "新增帳戶", "帳戶名稱")
        if not accepted:
            return
        balance, accepted = QInputDialog.getText(self, "新增帳戶", "期初餘額（TWD）", text="0")
        if not accepted:
            return
        result = self.controller.create_account(name, balance)
        if not result.success:
            QMessageBox.warning(self, "無法新增帳戶", result.message)
            return
        self.refresh()
        self.changed.emit()

    def archive_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None:
            return
        result = self.controller.archive_account(str(item["account_id"]))
        if not result.success:
            QMessageBox.warning(self, "無法封存帳戶", result.message)
            return
        self.refresh()
        self.changed.emit()

    def rename_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None:
            return
        name, accepted = QInputDialog.getText(
            self,
            "重新命名帳戶",
            "帳戶名稱",
            text=str(item["name"]),
        )
        if not accepted:
            return
        result = self.controller.rename_account(str(item["account_id"]), name)
        if not result.success:
            QMessageBox.warning(self, "無法重新命名", result.message)
            return
        self.refresh()
        self.changed.emit()


class CategoriesPage(QWidget):
    changed = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.table = QTableView()
        self.model = SimpleRowsModel(["分類", "細項", "狀態"])
        self._build()
        self.refresh()

    def _build(self) -> None:
        title = QLabel("分類")
        title.setObjectName("pageTitle")
        add_parent = QPushButton("新增分類")
        add_child = QPushButton("新增細項")
        rename_button = QPushButton("重新命名")
        archive_button = QPushButton("封存所選項目")
        row = QHBoxLayout()
        row.addWidget(add_parent)
        row.addWidget(add_child)
        row.addWidget(rename_button)
        row.addWidget(archive_button)
        row.addStretch()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addLayout(row)
        layout.addWidget(self.table)
        add_parent.clicked.connect(lambda: self.add_category(None))
        add_child.clicked.connect(self.add_detail)
        rename_button.clicked.connect(self.rename_selected)
        archive_button.clicked.connect(self.archive_selected)

    def refresh(self) -> None:
        rows: list[dict[str, Any]] = []
        for parent in self.controller.categories.list(include_archived=True).details.get(
            "categories", []
        ):
            children = self.controller.categories.list(
                parent_id=str(parent["category_id"]),
                include_archived=True,
            ).details.get("categories", [])
            if children:
                for child in children:
                    rows.append(
                        {
                            **child,
                            "parent_name": parent["name"],
                            "parent_id": parent["category_id"],
                        }
                    )
            else:
                rows.append({**parent, "parent_name": parent["name"], "detail_name": ""})
        self.model.replace_rows(
            rows,
            lambda item: [
                item.get("parent_name", ""),
                item["name"] if item.get("level") == 2 else item.get("detail_name", ""),
                "使用中" if item["status"] == "active" else "已封存",
            ],
        )

    def add_category(self, parent_id: str | None) -> None:
        label = "細項名稱" if parent_id else "分類名稱"
        name, accepted = QInputDialog.getText(self, "新增分類", label)
        if not accepted:
            return
        result = self.controller.create_category(name, parent_id)
        if not result.success:
            QMessageBox.warning(self, "無法新增分類", result.message)
            return
        self.refresh()
        self.changed.emit()

    def add_detail(self) -> None:
        parents = self.controller.category_options()
        if not parents:
            return
        names = [str(parent["name"]) for parent in parents]
        selected, accepted = QInputDialog.getItem(
            self,
            "新增細項",
            "上層分類",
            names,
            editable=False,
        )
        if not accepted:
            return
        parent_id = str(parents[names.index(selected)]["category_id"])
        self.add_category(parent_id)

    def archive_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None:
            return
        result = self.controller.archive_category(str(item["category_id"]))
        if not result.success:
            QMessageBox.warning(self, "無法封存分類", result.message)
            return
        self.refresh()
        self.changed.emit()

    def rename_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None:
            return
        name, accepted = QInputDialog.getText(
            self,
            "重新命名分類",
            "名稱",
            text=str(item["name"]),
        )
        if not accepted:
            return
        result = self.controller.rename_category(str(item["category_id"]), name)
        if not result.success:
            QMessageBox.warning(self, "無法重新命名", result.message)
            return
        self.refresh()
        self.changed.emit()


class SimpleRowsModel(QAbstractTableModel):
    def __init__(self, headers: list[str]) -> None:
        super().__init__()
        self.headers = headers
        self.items: list[dict[str, Any]] = []
        self.values: list[list[str]] = []

    def replace_rows(
        self,
        items: list[dict[str, Any]],
        mapper: Any,
    ) -> None:
        self.beginResetModel()
        self.items = items
        self.values = [list(map(str, mapper(item))) for item in items]
        self.endResetModel()

    def selected_item(self, table: QTableView) -> dict[str, Any] | None:
        selection = table.selectionModel().selectedRows()
        return self.items[selection[0].row()] if selection else None

    def rowCount(  # noqa: N802
        self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()
    ) -> int:
        return 0 if parent.isValid() else len(self.values)

    def columnCount(  # noqa: N802
        self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()
    ) -> int:
        return 0 if parent.isValid() else len(self.headers)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and index.isValid():
            return self.values[index.row()][index.column()]
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


class MaintenancePage(QWidget):
    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        title = QLabel("備份與匯出")
        title.setObjectName("pageTitle")
        backup = QPushButton("建立完整備份")
        export = QPushButton("匯出交易 CSV")
        self.result = QLabel()
        self.result.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(backup)
        layout.addWidget(export)
        layout.addWidget(self.result)
        layout.addStretch()
        backup.clicked.connect(self.create_backup)
        export.clicked.connect(self.export_csv)

    def create_backup(self) -> None:
        try:
            path = self.controller.create_backup()
            self.result.setText(f"備份已建立：{path}")
        except Exception as exc:
            QMessageBox.warning(self, "備份失敗", str(exc))

    def export_csv(self) -> None:
        try:
            path = self.controller.export_csv()
            self.result.setText(f"CSV 已匯出：{path}")
        except Exception as exc:
            QMessageBox.warning(self, "匯出失敗", str(exc))


class SettingsPage(QWidget):
    def __init__(self, paths: AppPaths) -> None:
        super().__init__()
        title = QLabel("設定")
        title.setObjectName("pageTitle")
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(QLabel("預設幣別：TWD"))
        layout.addWidget(QLabel("時區：Asia/Taipei"))
        layout.addWidget(QLabel(f"資料庫：{paths.database_path}"))
        layout.addStretch()


class MainWindow(QMainWindow):
    def __init__(self, paths: AppPaths) -> None:
        super().__init__()
        self.controller = LedgerController(paths)
        self.navigation = QListWidget()
        self.pages = QStackedWidget()
        self.quick_page = QuickEntryPage(self.controller)
        self.transactions_page = TransactionsPage(self.controller)
        self.accounts_page = AccountsPage(self.controller)
        self.categories_page = CategoriesPage(self.controller)
        self._build(paths)

    def _build(self, paths: AppPaths) -> None:
        self.setWindowTitle("TagCor Ledger")
        self.resize(1180, 720)
        try:
            self.setStyleSheet(read_text_resource("styles.qss"))
        except FileNotFoundError:
            pass
        labels = ["快速記帳", "交易紀錄", "帳戶", "分類", "備份與匯出", "設定"]
        pages = [
            self.quick_page,
            self.transactions_page,
            self.accounts_page,
            self.categories_page,
            MaintenancePage(self.controller),
            SettingsPage(paths),
        ]
        self.navigation.addItems(labels)
        for page in pages:
            self.pages.addWidget(page)
        self.navigation.setFixedWidth(160)
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.setCurrentRow(0)
        layout = QHBoxLayout()
        layout.addWidget(self.navigation)
        layout.addWidget(self.pages, 1)
        content = QWidget()
        content.setLayout(layout)
        self.setCentralWidget(content)
        self.statusBar().showMessage(f"資料庫：{paths.database_path}")

        self.quick_page.saved.connect(self.transactions_page.search_first_page)
        self.accounts_page.changed.connect(self.quick_page.reload_options)
        self.categories_page.changed.connect(self.quick_page.reload_options)
        self._add_shortcuts()

    def _add_shortcuts(self) -> None:
        new_action = QAction("新增交易", self)
        new_action.setShortcut(QKeySequence("Ctrl+N"))
        new_action.triggered.connect(self._focus_new)
        save_action = QAction("儲存交易", self)
        save_action.setShortcut(QKeySequence("Ctrl+S"))
        save_action.triggered.connect(self.quick_page.submit)
        clear_action = QAction("清除", self)
        clear_action.setShortcut(QKeySequence("Esc"))
        clear_action.triggered.connect(self.quick_page.clear_form)
        self.addActions([new_action, save_action, clear_action])

    def _focus_new(self) -> None:
        self.navigation.setCurrentRow(0)
        self.quick_page.amount.setFocus()


def _display_datetime(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%Y/%m/%d %H:%M")
    except ValueError:
        return value
