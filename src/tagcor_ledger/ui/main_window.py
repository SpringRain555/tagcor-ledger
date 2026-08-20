"""主視窗：側邊欄、頁面堆疊，以及頁面之間所有的連動。

**頁面之間的連動只寫在這裡。** 每一頁只管自己，做完事情就發訊號；「存了一筆交易之後
要重刷交易列表與餘額盤點」這種跨頁規則集中在下面幾個 `_..._changed` 方法裡，這樣要
知道某個動作會影響誰，只需要讀這一個檔案。

**導覽用 `PageId`，不用顯示文字。** 以前是 `show_page("快速記帳")` ——
改一個字就會噴 `KeyError`。頁面身分與顯示文字現在分開，見 `ui/navigation.py`。
"""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.navigation import ALL_PAGES, PageId
from tagcor_ledger.ui.pages.balance_snapshot import BalanceSnapshotPage
from tagcor_ledger.ui.pages.operation_settings import OperationSettingsPage
from tagcor_ledger.ui.pages.pending import PendingPage
from tagcor_ledger.ui.pages.quick_entry import QuickEntryPage
from tagcor_ledger.ui.pages.reference import ReferencePage
from tagcor_ledger.ui.pages.system_settings import SystemSettingsPage
from tagcor_ledger.ui.pages.transactions import TransactionsPage
from tagcor_ledger.ui.theme import apply_dark_theme
from tagcor_ledger.ui.widgets.sidebar import Sidebar


class MainWindow(QMainWindow):
    def __init__(self, paths: AppPaths) -> None:
        super().__init__()
        self.controller = LedgerController(paths)
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

        self._page_widgets: dict[PageId, QWidget] = {
            PageId.ENTRY: self.quick,
            PageId.INBOX: self.pending,
            PageId.TRANSACTIONS: self.transactions,
            PageId.BALANCE: self.balance,
            PageId.REFERENCE: self.reference,
            PageId.OPERATION_SETTINGS: self.operation_settings,
            PageId.SYSTEM_SETTINGS: self.system_settings,
        }
        self.pages.setObjectName("contentStack")
        for page in ALL_PAGES:
            widget = self._page_widgets[page]
            widget.setObjectName("pageSurface")
            self.pages.addWidget(widget)

        # 側邊欄要在 apply_dark_theme 之後才建 —— 它的高度是照 QSS 的項目內距算出來的。
        self.sidebar = Sidebar()
        self.sidebar.setFixedWidth(184)
        self.sidebar.page_selected.connect(self._navigate)

        layout = QHBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(16)
        layout.addWidget(self.sidebar)
        layout.addWidget(self.pages, 1)
        content = QWidget()
        content.setObjectName("appShell")
        content.setLayout(layout)
        self.setCentralWidget(content)
        self.show_page(PageId.ENTRY)
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

    def _navigate(self, page_value: str) -> None:
        self.pages.setCurrentWidget(self._page_widgets[PageId(page_value)])

    def show_page(self, page: PageId) -> None:
        """跳到某一頁。走側邊欄，讓選取狀態與畫面永遠是同一個真相。"""
        self.sidebar.select(page)
        self._navigate(str(page))

    def _focus_new(self) -> None:
        self.show_page(PageId.ENTRY)
        self.quick.amount.setFocus()

    def _prefill_quick(self, draft: dict[str, Any]) -> None:
        self.quick.apply_draft(draft)
        self.show_page(PageId.ENTRY)

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
        """待確認的數字直接畫在側邊欄右側，不必點進去才知道有沒有事情要處理。"""
        self.sidebar.set_badge(PageId.INBOX, len(self.controller.list_pending()))

    def _show_balance_snapshot_reminder(self) -> None:
        if self.controller.refresh_balance_snapshot_reminder_due():
            self.statusBar().showMessage(
                "提醒：今天尚未記錄預設帳戶的目前金額，可到「餘額盤點」新增盤點。",
                10000,
            )
