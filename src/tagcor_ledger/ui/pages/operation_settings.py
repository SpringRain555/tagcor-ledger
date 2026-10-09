"""操作設定：四個分頁的容器。

它自己沒有畫面邏輯，只負責放標題與把底下各頁的訊號往上轉。

## 分頁順序本身就是分組

**帳戶／類別與項目／模板** —— 記帳時會用到的東西，你自己決定什麼時候用。
**定存** —— 會自己到期、自己產生待確認的東西。

前三個是「名冊」，最後一個是「會動的」。中間那條界線不需要寫成標題，順序就講完了。

v0.23.0 之前「會動的」有兩個，另一個是定期收支
（[ADR-0011](../../../../docs/decisions/ADR-0011-drop-recurring-schedules.md)）。

## 「類別」與「項目」在同一個分頁、仍是兩張表

2026-10-05 起它們在同一個分頁裡**並排**（`category_items.py`）：點左邊的類別，右邊列它
底下的項目。v0.14.0 把它們拆開的理由沒有變 —— 類別十來個、很少動；項目幾十個、每個月都在加；
一張平的表既沒辦法好好列類別（有子項目的類別根本沒有自己的列，見 `catalog.py`），
也沒辦法好好找項目 —— 所以並排的是兩張完整的表，不是併成一張。

`categories`／`items` 兩個名字留著，指向那個分頁裡的兩個窗格。2026-10-09 起兩張表上方
共用一排按鈕（重新命名、封存／恢復、刪除未使用、排序設定），一次只選一列 —— 細節見
`category_items.py`。

**標題只在這一層。** 子頁不再各自畫一個 20pt 大標 —— 側邊欄已經說了在哪一頁、
分頁標籤已經說了是哪一個，第三次重複只是吃掉一行高度。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QTabWidget, QWidget

from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.pages.catalog import AccountsPage
from tagcor_ledger.ui.pages.category_items import CategoryItemsTab
from tagcor_ledger.ui.pages.deposits import DepositsPage
from tagcor_ledger.ui.pages.templates import TemplatesPage
from tagcor_ledger.ui.widgets.layout import TABLE_WIDTH, page_layout

# `_tabs()` 以前宣告回傳 `QWidget`，而 `QWidget` 上沒有 `.changed` 與 `.refresh()`。
# 本機的 mypy 看不出來 —— conda 的 PySide6 有 `.pyi` 但**沒有 `py.typed`**，依
# PEP 561 那些 stub 會被忽略，於是整個 Qt 都是 `Any`。CI 裝的是帶 stub 的版本，
# 一跑就報出來。列具體的四頁而不是用 Protocol：`addTab()` 要的是真的 `QWidget`，
# 而 Protocol 表達不出「同時也是 QWidget」。
SettingsTabPage = AccountsPage | CategoryItemsTab | TemplatesPage | DepositsPage


class OperationSettingsPage(QWidget):
    apply_requested = Signal(dict)
    changed = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.accounts = AccountsPage(controller)
        self.category_items = CategoryItemsTab(controller)
        self.categories = self.category_items.categories
        self.items = self.category_items.items
        self.templates = TemplatesPage(controller)
        self.deposits = DepositsPage(controller)
        self._build()

    def _tabs(self) -> tuple[tuple[SettingsTabPage, str], ...]:
        """分頁順序的唯一正本。`refresh()` 與漂移守門都讀它。"""
        return (
            (self.accounts, "帳戶"),
            (self.category_items, "類別與項目"),
            (self.templates, "模板"),
            (self.deposits, "定存"),
        )

    def _build(self) -> None:
        title = QLabel("操作設定")
        title.setObjectName("pageTitle")
        self.tabs = QTabWidget()
        self.tabs.setObjectName("settingsTabs")
        for page, label in self._tabs():
            self.tabs.addTab(page, label)
            page.changed.connect(self.changed.emit)
        layout = page_layout(self, width=TABLE_WIDTH)
        layout.addWidget(title)
        layout.addWidget(self.tabs)
        self.templates.apply_requested.connect(self.apply_requested.emit)

    def refresh(self) -> None:
        for page, _label in self._tabs():
            page.refresh()

    def show_tab(self, page: SettingsTabPage) -> None:
        self.tabs.setCurrentWidget(page)

    def create_template_from(self, draft: dict[str, Any]) -> None:
        """交易紀錄的「建立模板」：切到模板分頁，開一張已經帶入那筆內容的**新增**視窗。

        先切分頁再開視窗，使用者關掉視窗之後看到的就是模板清單 —— 剛存的那一列在眼前。
        名稱留白讓使用者取；按儲存才寫入（`TemplatesPage.edit`）。
        """
        self.show_tab(self.templates)
        self.templates.edit(None, prefill=draft)
