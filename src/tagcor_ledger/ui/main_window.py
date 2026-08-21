"""主視窗：側邊欄、頁面堆疊，以及頁面之間所有的連動。

**頁面之間的連動只寫在這裡。** 每一頁只管自己，做完事情就發訊號；「存了一筆交易之後
要重刷交易列表與餘額盤點」這種跨頁規則集中在下面幾個 `_..._changed` 方法裡，這樣要
知道某個動作會影響誰，只需要讀這一個檔案。

**導覽用 `PageId`，不用顯示文字。** 以前是 `show_page("快速記帳")` ——
改一個字就會噴 `KeyError`。頁面身分與顯示文字現在分開，見 `ui/navigation.py`。

**資產總覽是唯一的例外**：它不靠 `_..._changed` 通知，而是**切過去就重算**。
它讀的東西橫跨帳戶、定存、定期收支與盤點，要在每個 `_..._changed` 各記一筆的話，
遲早會漏掉一項 —— 而漏掉的症狀是總資產停在舊數字，看起來像算錯帳。
"""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from tagcor_ledger.app import window_state
from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.app.window_state import WindowGeometry, load_geometry, save_geometry
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.navigation import ALL_PAGES, LANDING_PAGE, PageId
from tagcor_ledger.ui.pages.balance_snapshot import BalanceSnapshotPage
from tagcor_ledger.ui.pages.operation_settings import OperationSettingsPage
from tagcor_ledger.ui.pages.inbox import InboxPage
from tagcor_ledger.ui.pages.overview import OverviewPage
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
        # **主題要在任何 widget 建出來之前套用。** `apply_dark_theme` 換掉的是整個
        # application 的字體，而頁面裡的表格在**建構當下**就會量自己該多寬
        # （`setup_table` → `fit_to_contents`）。順序反了，量到的是預設字體下的寬度，
        # 之後套上 12pt 中文字體，欄位變寬而上限沒跟著變 —— 帳戶表因此被夾在 187 px
        # （實際需要 279），「目前餘額（TWD）」被切掉還冒出橫向捲軸。
        self._apply_theme()
        self.pages = QStackedWidget()
        self.overview = OverviewPage(self.controller)
        self.quick = QuickEntryPage(self.controller)
        self.balance = BalanceSnapshotPage(self.controller)
        self.inbox = InboxPage(self.controller)
        self.transactions = TransactionsPage(self.controller)
        self.operation_settings = OperationSettingsPage(self.controller)
        self.reference = ReferencePage(self.controller)
        self.system_settings = SystemSettingsPage(self.controller, paths)
        self._build(paths)
        self.refresh_pending_badge()

    @staticmethod
    def _apply_theme() -> None:
        app = QApplication.instance()
        if app is not None:
            apply_dark_theme(cast(QApplication, app))

    def _build(self, paths: AppPaths) -> None:
        self.setWindowTitle("TagCor Ledger")
        self._restore_geometry()

        self._page_widgets: dict[PageId, QWidget] = {
            PageId.OVERVIEW: self.overview,
            PageId.ENTRY: self.quick,
            PageId.INBOX: self.inbox,
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

        # 側邊欄的高度是照 QSS 的項目內距算出來的，所以要在主題套用之後才建 ——
        # 現在整個 `__init__` 都在主題之後，這條自然成立（見 `_apply_theme` 那段說明）。
        self.sidebar = Sidebar()
        self.sidebar.adapt_to(self.width())
        self.sidebar.page_selected.connect(self._navigate)

        # 外框不留邊，側邊欄的右框線才會是一條**通到底**的分隔線；內容自己的外距
        # 由 `page_layout` 負責。間距也是 0 —— 那條線就是分隔，不需要再空一段。
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.sidebar)
        layout.addWidget(self.pages, 1)
        content = QWidget()
        content.setObjectName("appShell")
        content.setLayout(layout)
        self.setCentralWidget(content)
        self.show_page(LANDING_PAGE)

        self.overview.inbox_requested.connect(lambda: self.show_page(PageId.INBOX))
        self.overview.balance_requested.connect(lambda: self.show_page(PageId.BALANCE))
        self.quick.saved.connect(self._transaction_changed)
        self.balance.changed.connect(self._balance_changed)
        self.balance.record_transaction_requested.connect(self._focus_new)
        self.transactions.duplicate_requested.connect(self._prefill_quick)
        self.operation_settings.apply_requested.connect(self._prefill_quick)
        self.operation_settings.changed.connect(self._catalog_changed)
        self.inbox.changed.connect(self.refresh_pending_badge)
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

    # --- 視窗幾何 -------------------------------------------------------------

    def _restore_geometry(self) -> None:
        """回到上次的大小與位置。讀不到就用預設值 —— 這個檔案壞掉不該讓程式開不起來。"""
        saved = load_geometry(self.controller.paths.config_dir)
        if saved is None:
            self.resize(window_state.DEFAULT_WIDTH, window_state.DEFAULT_HEIGHT)
            return
        self.setGeometry(saved.x, saved.y, saved.width, saved.height)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        geometry = self.normalGeometry() if self.isMaximized() else self.geometry()
        save_geometry(
            self.controller.paths.config_dir,
            WindowGeometry(
                x=geometry.x(),
                y=geometry.y(),
                width=geometry.width(),
                height=geometry.height(),
            ),
        )
        super().closeEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.sidebar.adapt_to(event.size().width())

    # --- 導覽 -----------------------------------------------------------------

    def _navigate(self, page_value: str) -> None:
        page = PageId(page_value)
        if page is PageId.OVERVIEW:
            # **切過去就重算**，不在每個 `_..._changed` 各記一筆 —— 那種清單一定會漏掉
            # 一項，而漏掉的症狀是總資產停在舊數字，看起來像算錯帳。
            self.overview.refresh()
        self.pages.setCurrentWidget(self._page_widgets[page])

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
        self.inbox.refresh()

    def _automation_changed(self) -> None:
        self.operation_settings.refresh()
        self.inbox.refresh()

    def _settings_changed(self) -> None:
        self.quick.apply_defaults()
        self.transactions.first_page()
        self.balance.reload_accounts()

    def _restored(self) -> None:
        # 狀態列只放**暫時**訊息。資料庫路徑常駐在這裡吃掉一整行，而它是一年看兩次的
        # 東西 —— 現在住在「系統設定 → 資料路徑」。
        self.statusBar().showMessage("資料庫已重新載入。", 6000)
        self.quick.reload_options()
        self.quick.apply_defaults()
        self.balance.reload_accounts()
        self.transactions.reload_filters()
        self.transactions.first_page()
        self.operation_settings.refresh()
        self.inbox.refresh()
        self.system_settings.reload()

    def refresh_pending_badge(self) -> None:
        """待確認的數字直接畫在側邊欄右側，不必點進去才知道有沒有事情要處理。

        走 `controller.inbox_count()`，與資產總覽同一個來源 —— 兩邊各自算就會出現
        「側邊欄說 2、總覽說 3」，而使用者沒有辦法知道哪一個才對。
        """
        self.sidebar.set_badge(PageId.INBOX, self.controller.inbox_count())
