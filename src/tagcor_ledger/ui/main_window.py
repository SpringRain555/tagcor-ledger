"""Main PyQt window for the Phase 2 MVP."""

from __future__ import annotations

from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMainWindow,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.app.resources import read_text_resource
from tagcor_ledger.ui.controllers import LedgerUiController
from tagcor_ledger.ui.transaction_panel import TransactionPanel


class MainWindow(QMainWindow):
    def __init__(self, paths: AppPaths) -> None:
        super().__init__()
        self.paths = paths
        self.controller = LedgerUiController(paths)
        self.transaction_panel = TransactionPanel(self.controller.load_tag_catalog())
        self.recent_table = QTableWidget(0, 6)
        self._build_ui()
        self._connect_actions()
        self.refresh_recent()

    def _build_ui(self) -> None:
        self.setWindowTitle("TagCor Ledger")
        self.resize(980, 640)
        try:
            self.setStyleSheet(read_text_resource("styles.qss"))
        except FileNotFoundError:
            pass

        self.recent_table.setHorizontalHeaderLabels(["時間", "類型", "金額", "幣別", "標籤", "描述"])
        self.recent_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.recent_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        content = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(self.transaction_panel)
        layout.addWidget(self.recent_table)
        content.setLayout(layout)
        self.setCentralWidget(content)
        self.statusBar().showMessage(f"資料目錄：{self.paths.data_dir}")

    def _connect_actions(self) -> None:
        submit_action = QAction("Submit", self)
        submit_action.setShortcut(QKeySequence("Ctrl+S"))
        submit_action.triggered.connect(self.submit_transaction)
        self.addAction(submit_action)
        self.transaction_panel.submitted.connect(self.submit_transaction)

    def submit_transaction(self) -> None:
        result = self.controller.submit_transaction(
            occurred_at=self.transaction_panel.occurred_at(),
            entry_type=self.transaction_panel.entry_type(),
            amount=self.transaction_panel.amount(),
            tag_path=self.transaction_panel.tag_path(),
            description=self.transaction_panel.description(),
        )
        if result.success:
            self.transaction_panel.reset_after_submit()
            self.refresh_recent()
            self.statusBar().showMessage(f"{result.message} {result.correlation_id}")
            return
        QMessageBox.warning(self, "交易無法儲存", f"{result.message}\n追蹤碼：{result.correlation_id}")

    def refresh_recent(self) -> None:
        result = self.controller.recent_transactions()
        if not result.success:
            self.statusBar().showMessage(f"{result.message} {result.correlation_id}")
            return
        transactions = result.details.get("transactions", [])
        self.recent_table.setRowCount(len(transactions))
        for row_index, transaction in enumerate(transactions):
            values = [
                transaction["occurred_at"],
                transaction["entry_type"],
                transaction["amount"],
                transaction["currency"],
                transaction["tag_path_name"],
                transaction["description"],
            ]
            for column_index, value in enumerate(values):
                self.recent_table.setItem(row_index, column_index, QTableWidgetItem(str(value)))
