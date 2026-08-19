"""主視窗：側邊欄、頁面堆疊，以及頁面之間所有的連動。

**頁面之間的連動只寫在這裡。** 每一頁只管自己，做完事情就發訊號；「存了一筆交易之後
要重刷交易列表與餘額盤點」這種跨頁規則集中在下面幾個 `_..._changed` 方法裡，這樣要
知道某個動作會影響誰，只需要讀這一個檔案。
"""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.pages.balance_snapshot import BalanceSnapshotPage
from tagcor_ledger.ui.pages.operation_settings import OperationSettingsPage
from tagcor_ledger.ui.pages.pending import PendingPage
from tagcor_ledger.ui.pages.quick_entry import QuickEntryPage
from tagcor_ledger.ui.pages.reference import ReferencePage
from tagcor_ledger.ui.pages.system_settings import SystemSettingsPage
from tagcor_ledger.ui.pages.transactions import TransactionsPage
from tagcor_ledger.ui.theme import apply_dark_theme


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
        self.reference = ReferencePage(self.controller)
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
        # 側邊欄分成「每天用」與「設定與查閱」兩組。原本七項平鋪，而且「法規參考」
        # 卡在兩個設定頁中間 —— 每天要用的四頁跟一年動兩次的設定看起來一樣重要。
        sections: list[tuple[str, list[tuple[str, QWidget]]]] = [
            (
                "每天用",
                [
                    ("快速記帳", self.quick),
                    ("待確認", self.pending),
                    ("交易紀錄", self.transactions),
                    ("餘額盤點", self.balance),
                ],
            ),
            (
                "設定與查閱",
                [
                    ("法規參考", self.reference),
                    ("操作設定", self.operation_settings),
                    ("系統設定", self.system_settings),
                ],
            ),
        ]
        self.navigation.setObjectName("sidebarNavigation")
        self.pages.setObjectName("contentStack")
        self._page_rows: dict[str, int] = {}
        self._row_to_page: dict[int, int] = {}
        for section_title, entries in sections:
            header = QListWidgetItem(section_title)
            # 分組標題不可選、不可聚焦 —— 它是標籤，不是一頁。
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            self.navigation.addItem(header)
            for label, page in entries:
                row = self.navigation.count()
                self._page_rows[label] = row
                self._row_to_page[row] = self.pages.count()
                self.navigation.addItem(QListWidgetItem(label))
                page.setObjectName("pageSurface")
                self.pages.addWidget(page)
        self.navigation.setFixedWidth(184)
        self.navigation.currentRowChanged.connect(self._navigate)
        self.navigation.setCurrentRow(self._page_rows["快速記帳"])
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

    def _navigate(self, row: int) -> None:
        """側邊欄有分組標題，所以列號不等於頁面編號。"""
        page_index = self._row_to_page.get(row)
        if page_index is not None:
            self.pages.setCurrentIndex(page_index)

    def show_page(self, label: str) -> None:
        self.navigation.setCurrentRow(self._page_rows[label])

    def _focus_new(self) -> None:
        self.show_page("快速記帳")
        self.quick.amount.setFocus()

    def _prefill_quick(self, draft: dict[str, Any]) -> None:
        self.quick.apply_draft(draft)
        self.show_page("快速記帳")

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
        """待確認的數字直接寫在側邊欄，不必點進去才知道有沒有事情要處理。"""
        count = len(self.controller.list_pending())
        item = self.navigation.item(self._page_rows["待確認"])
        if item is not None:
            item.setText(f"待確認（{count}）" if count else "待確認")

    def _show_balance_snapshot_reminder(self) -> None:
        if self.controller.refresh_balance_snapshot_reminder_due():
            self.statusBar().showMessage(
                "提醒：今天尚未記錄預設帳戶的目前金額，可到「餘額盤點」新增盤點。",
                10000,
            )
