"""主視窗：側邊欄、頁面堆疊，以及頁面之間所有的連動。

**頁面之間的連動只寫在這裡。** 每一頁只管自己，做完事情就發訊號；「存了一筆交易之後
要重刷交易列表與餘額盤點」這種跨頁規則集中在下面幾個 `_..._changed` 方法裡，這樣要
知道某個動作會影響誰，只需要讀這一個檔案。

**導覽用 `PageId`，不用顯示文字。** 以前是 `show_page("快速記帳")` ——
改一個字就會噴 `KeyError`。頁面身分與顯示文字現在分開，見 `ui/navigation.py`。

**資產總覽是唯一的例外**：它不靠 `_..._changed` 通知，而是**切過去就重算**。
它讀的東西橫跨帳戶、定存、定期收支與盤點，要在每個 `_..._changed` 各記一筆的話，
遲早會漏掉一項 —— 而漏掉的症狀是總資產停在舊數字，看起來像算錯帳。

**窄視窗（< `NARROW_BREAKPOINT`）沒有側邊欄**，換成頂端一顆「☰ 目前頁名」的選單按鈕。
兩者是同一份導覽的兩種外觀：選單裡的項目、分組與待確認的數字都從同一個來源來，
而「現在是哪一頁」的正本仍然是 `Sidebar` —— 它只是藏起來，沒有被拆掉。
"""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtGui import QAction, QKeySequence, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.app import window_state
from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.navigation import (
    ALL_PAGES,
    DAILY_PAGES,
    LABELS,
    LANDING_PAGE,
    PENDING_PAGE,
    SETTINGS_PAGES,
    PageId,
)
from tagcor_ledger.ui.pages.balance_snapshot import BalanceSnapshotPage
from tagcor_ledger.ui.pages.entry import EntryPage
from tagcor_ledger.ui.pages.operation_settings import OperationSettingsPage
from tagcor_ledger.ui.pages.overview import OverviewPage
from tagcor_ledger.ui.pages.reference import ReferencePage
from tagcor_ledger.ui.pages.system_settings import SystemSettingsPage
from tagcor_ledger.ui.pages.transactions import TransactionsPage
from tagcor_ledger.ui.theme import apply_dark_theme
from tagcor_ledger.ui.widgets.layout import NARROW_BREAKPOINT, scrollable, set_page_compact
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
        self.entry = EntryPage(self.controller)
        self.balance = BalanceSnapshotPage(self.controller)
        # 待確認是餘額盤點頁底下的一塊（ADR-0016），不再是一頁。留一個名字指著它，
        # 「待確認在哪」才不必每個地方都知道它住在盤點頁裡。
        self.inbox = self.balance.inbox
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
        # 下限寫死是安全的：每一頁都能捲，內容不會被這個下限擠爛，
        # 而它給了版面測試一個固定的最壞情況。
        self.setMinimumSize(window_state.MINIMUM_WIDTH, window_state.MINIMUM_HEIGHT)
        self._place_at_default_size()

        self._page_widgets: dict[PageId, QWidget] = {
            PageId.OVERVIEW: self.overview,
            PageId.ENTRY: self.entry,
            PageId.TRANSACTIONS: self.transactions,
            PageId.BALANCE: self.balance,
            PageId.REFERENCE: self.reference,
            PageId.OPERATION_SETTINGS: self.operation_settings,
            PageId.SYSTEM_SETTINGS: self.system_settings,
        }
        self.pages.setObjectName("contentStack")
        # 每一頁包自己的捲動區，不要包在堆疊外面 —— 理由見 `widgets/layout.py`。
        self._page_scrolls: dict[PageId, QScrollArea] = {}
        for page in ALL_PAGES:
            widget = self._page_widgets[page]
            widget.setObjectName("pageSurface")
            self._page_scrolls[page] = scrollable(widget)
            self.pages.addWidget(self._page_scrolls[page])

        # 側邊欄的高度是照 QSS 的項目內距算出來的，所以要在主題套用之後才建 ——
        # 現在整個 `__init__` 都在主題之後，這條自然成立（見 `_apply_theme` 那段說明）。
        self.sidebar = Sidebar()
        self.sidebar.adapt_to(self.width())
        self.sidebar.page_selected.connect(self._navigate)

        # 外框不留邊，側邊欄的右框線才會是一條**通到底**的分隔線；內容自己的外距
        # 由 `page_layout` 負責。間距也是 0 —— 那條線就是分隔，不需要再空一段。
        self.narrow_nav = self._build_narrow_nav()

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.narrow_nav)
        column.addWidget(self.pages, 1)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.sidebar)
        layout.addLayout(column, 1)
        content = QWidget()
        content.setObjectName("appShell")
        content.setLayout(layout)
        self.setCentralWidget(content)
        self._narrow: bool | None = None
        self._adapt_to_width(self.width())
        self.show_page(LANDING_PAGE)

        self.overview.inbox_requested.connect(self.show_pending)
        self.overview.balance_requested.connect(lambda: self.show_page(PageId.BALANCE))
        # **每一個會改動帳務的來源都接到同一個 `_ledger_changed`。** 三個來源
        # （記帳、交易紀錄的刪除／編輯、待確認的確認入帳）做的是同一件事 ——
        # 產生或改變交易 —— 所以它們該通知的對象也是同一組。分成三個「差不多」
        # 的方法，就是下一個「某一頁忘了重刷」的來源。待確認住在盤點頁裡，
        # 它的確認入帳由盤點頁轉成 `ledger_changed` 發出來。
        self.entry.saved.connect(self._ledger_changed)
        self.transactions.changed.connect(self._ledger_changed)
        self.balance.ledger_changed.connect(self._ledger_changed)
        self.balance.changed.connect(self._balance_changed)
        self.balance.record_transaction_requested.connect(self._record_missing_transaction)
        self.transactions.template_requested.connect(self._create_template)
        self.operation_settings.apply_requested.connect(self._prefill_quick)
        self.operation_settings.changed.connect(self._catalog_changed)
        self.system_settings.restored.connect(self._restored)
        self.system_settings.saved.connect(self._settings_changed)
        self.system_settings.paths_changed.connect(self._restored)
        self._add_shortcuts()

    def _build_narrow_nav(self) -> QFrame:
        """窄視窗的頂端列：一顆按鈕，點開是跟側邊欄一模一樣的頁面清單。

        **是 `QFrame` 不是 `QWidget`**，理由同側邊欄 —— 底下那條分隔線要畫得出來。
        """
        self._inbox_count = 0
        """待確認的數字。只在 `refresh_pending_badge()` 算，換頁不重查。"""
        self.page_menu = QMenu(self)
        self._page_actions: dict[PageId, QAction] = {}
        for group in (DAILY_PAGES, SETTINGS_PAGES):
            if self._page_actions:
                self.page_menu.addSeparator()
            for page in group:
                action = self.page_menu.addAction(LABELS[page])
                action.triggered.connect(lambda _=False, p=page: self.show_page(p))
                self._page_actions[page] = action

        self.page_menu_button = QToolButton()
        self.page_menu_button.setObjectName("pageMenuButton")
        self.page_menu_button.setMenu(self.page_menu)
        self.page_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        bar = QFrame()
        bar.setObjectName("narrowNav")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(8, 6, 8, 6)
        bar_layout.addWidget(self.page_menu_button)
        bar_layout.addStretch()
        return bar

    def _adapt_to_width(self, width: int) -> None:
        """側邊欄 ↔ 頂端選單、外距大 ↔ 小。只有跨過門檻時才真的動，拖曳視窗時不抖。"""
        self.sidebar.adapt_to(width)
        narrow = width < NARROW_BREAKPOINT
        if narrow == self._narrow:
            return
        self._narrow = narrow
        self.sidebar.setVisible(not narrow)
        self.narrow_nav.setVisible(narrow)
        for widget in self._page_widgets.values():
            set_page_compact(widget, narrow)

    def is_narrow(self) -> bool:
        """現在是不是窄視窗版面。給測試用。"""
        return bool(self._narrow)

    def _add_shortcuts(self) -> None:
        new_action = QAction("新增交易", self)
        new_action.setShortcut(QKeySequence("Ctrl+N"))
        new_action.triggered.connect(self._focus_new)
        save_action = QAction("儲存交易", self)
        save_action.setShortcut(QKeySequence("Ctrl+S"))
        save_action.triggered.connect(self.entry.submit)
        # 與記帳頁的「清空」按鈕是同一件事，名字也要同一個。
        clear_action = QAction("清空", self)
        clear_action.setShortcut(QKeySequence("Esc"))
        clear_action.triggered.connect(self.entry.clear_form)
        self.addActions([new_action, save_action, clear_action])

    # --- 視窗幾何 -------------------------------------------------------------

    def _place_at_default_size(self) -> None:
        """每次啟動都是預設大小、置中在主螢幕 —— **不記上次的大小**（見 `window_state`）。

        螢幕比預設小（例如 1366×768 再加 125% 縮放）時縮到可用範圍內，
        不讓標題列或底部跑到螢幕外面。
        """
        width, height = window_state.DEFAULT_WIDTH, window_state.DEFAULT_HEIGHT
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(width, height)
            return
        available = screen.availableGeometry()
        width = min(width, available.width())
        height = min(height, available.height())
        self.resize(width, height)
        self.move(
            available.x() + (available.width() - width) // 2,
            available.y() + (available.height() - height) // 2,
        )

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._adapt_to_width(event.size().width())

    # --- 導覽 -----------------------------------------------------------------

    def _navigate(self, page_value: str) -> None:
        page = PageId(page_value)
        if page is PageId.OVERVIEW:
            # **切過去就重算**，不在每個 `_..._changed` 各記一筆 —— 那種清單一定會漏掉
            # 一項，而漏掉的症狀是總資產停在舊數字，看起來像算錯帳。
            self.overview.refresh()
        self.pages.setCurrentWidget(self._page_scrolls[page])
        self._sync_page_menu()

    def current_page_widget(self) -> QWidget | None:
        """堆疊**真正**顯示著的那一頁（捲動區裡面那個）。

        讀的是 `QStackedWidget`，不是側邊欄 —— 測試要驗的正是兩者有沒有一致。
        """
        scroll = self.pages.currentWidget()
        return scroll.widget() if isinstance(scroll, QScrollArea) else scroll

    def _sync_page_menu(self) -> None:
        """頂端選單按鈕寫著目前是哪一頁；待確認有事時選單裡帶著數字。"""
        current = self.sidebar.current_page()
        count = self._inbox_count
        for page, action in self._page_actions.items():
            label = LABELS[page]
            if page is PENDING_PAGE and count:
                label = f"{label}（{count}）"
            action.setText(label)
        if current is not None:
            self.page_menu_button.setText(f"☰  {LABELS[current]}")

    def show_page(self, page: PageId) -> None:
        """跳到某一頁。走側邊欄，讓選取狀態與畫面永遠是同一個真相。"""
        self.sidebar.select(page)
        self._navigate(str(page))

    def _focus_new(self) -> None:
        self.show_page(PageId.ENTRY)
        self.entry.amount.setFocus()

    def show_pending(self) -> None:
        """資產總覽的「去處理」：待確認住在餘額盤點頁底下，切過去再把那一塊捲到最上面。

        **捲到「補記與待確認」的標題貼著頂端**，不是 `ensureWidgetVisible(標題)`：預設視窗
        大小下標題剛好露在畫面底緣，那個呼叫判定「已經看得到」就不捲，而真正要處理的清單
        還在畫面外（2026-10-05 實機截圖抓到的）。頁面不夠長時捲軸自己會停在最底。

        **捲動排到下一輪事件迴圈。** 第一次切到這一頁時版面還沒算過，當下量到的位置都是 0。
        """
        self.show_page(PENDING_PAGE)
        scroll = self._page_scrolls[PENDING_PAGE]

        def reveal() -> None:
            content = scroll.widget()
            if content is not None:
                top = self.balance.pending_title.mapTo(content, QPoint(0, 0)).y()
                scroll.verticalScrollBar().setValue(max(0, top - 12))

        QTimer.singleShot(0, reveal)

    def _record_missing_transaction(self, account_id: str) -> None:
        """盤點頁的「補記交易」：切到記帳頁，帳戶先選好盤點頁正在看的那一個。

        使用者在看某個帳戶的差額，按下去要補的多半就是那個帳戶的帳。只選帳戶、
        不動其他欄位 —— 記帳頁上正在打的東西不能因為換頁而消失。
        """
        self.show_page(PageId.ENTRY)
        if account_id:
            self.entry.prefill_account(account_id)
        self.entry.amount.setFocus()

    def _prefill_quick(self, draft: dict[str, Any]) -> None:
        self.entry.apply_draft(draft)
        self.show_page(PageId.ENTRY)

    def _create_template(self, draft: dict[str, Any]) -> None:
        """交易紀錄的「建立模板」：先切到操作設定，再讓它切到模板分頁開視窗。

        順序不能反 —— 視窗是 modal 的，`exec()` 會停在這裡直到關掉；先換頁，
        使用者在視窗後面看到的才是它要回到的那一頁。
        """
        self.show_page(PageId.OPERATION_SETTINGS)
        self.operation_settings.create_template_from(draft)

    def _ledger_changed(self) -> None:
        """有交易被建立、改變或刪除之後，誰要重算。

        **餘額盤點一定要在這裡。** 未解釋差額是「盤點金額 － 期間 posting 加總」，
        任何一筆交易的增減都會改變它。2026-08 之前只有記帳頁接到這條線，於是從
        交易紀錄刪除一筆錯帳、或在待確認按下確認入帳之後，餘額盤點的差額都停在舊值。

        **資產總覽不在這裡** —— 它走「切過去就重算」（見 `overview.py` 的模組說明）。
        把它加進來就等於同時維護兩套規則，而其中一套遲早會漏。
        """
        self.transactions.first_page()
        self.balance.refresh()
        self.refresh_pending_badge()

    def _balance_changed(self) -> None:
        self.balance.refresh()

    def _catalog_changed(self) -> None:
        """操作設定裡的任何改動。

        以前有兩件事是**順帶**發生的：待確認頁重整時一律發 `changed`，連鎖到
        `_ledger_changed()`，於是交易紀錄跟著重載、待確認的數字跟著更新。那條連鎖拿掉了
        （見 `InboxSection`），兩件事都得在這裡明講，否則就是「跨頁連動掉了一條線」：

        - **交易紀錄要重載**：類別改名、更改所屬類別會改變交易顯示的名字，
          定存的中途解約會建立交易。只重填篩選下拉（`reload_filters()`）不會重查清單。
        - **待確認的數字要重算**：定存頁的「產生」、建立或結束合約都會改變待確認。
          待確認的清單本身由 `reload_accounts()` 重查。
        """
        self.entry.reload_options()
        self.balance.reload_accounts()
        self.transactions.reload_filters()
        self.transactions.first_page()
        self.system_settings.reload()
        self.operation_settings.refresh()
        self.refresh_pending_badge()

    def _settings_changed(self) -> None:
        self.entry.apply_defaults()
        self.transactions.first_page()
        self.balance.reload_accounts()

    def _restored(self) -> None:
        # 狀態列只放**暫時**訊息。資料庫路徑常駐在這裡吃掉一整行，而它是一年看兩次的
        # 東西 —— 現在住在「系統設定 → 資料路徑」。
        self.statusBar().showMessage("資料庫已重新載入。", 6000)
        self.entry.reload_options()
        self.entry.apply_defaults()
        self.balance.reload_accounts()
        self.transactions.reload_filters()
        self.transactions.first_page()
        self.operation_settings.refresh()
        self.system_settings.reload()
        self.refresh_pending_badge()

    def refresh_pending_badge(self) -> None:
        """待確認的數字直接畫在側邊欄右側，不必點進去才知道有沒有事情要處理。

        **掛在餘額盤點那一列**（`PENDING_PAGE`）：待確認住在那一頁底下（ADR-0016）。
        走 `controller.inbox_count()`，與資產總覽同一個來源 —— 兩邊各自算就會出現
        「側邊欄說 2、總覽說 3」，而使用者沒有辦法知道哪一個才對。
        """
        self._inbox_count = self.controller.inbox_count()
        self.sidebar.set_badge(PENDING_PAGE, self._inbox_count)
        self._sync_page_menu()
