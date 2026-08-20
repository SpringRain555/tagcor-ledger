"""操作設定：六個分頁的容器。

它自己沒有畫面邏輯，只負責放標題與把底下六頁的訊號往上轉。

## 分頁順序本身就是分組

**帳戶／類別／項目／模板** —— 記帳時會用到的東西，你自己決定什麼時候用。
**定期收支／定存** —— 會自己到期、自己產生待確認的東西。

前四個是「名冊」，後兩個是「會動的」。中間那條界線不需要寫成標題，順序就講完了。

## 為什麼「類別」與「項目」分開

它們是同一張表的兩層，但**要做的事不一樣**：類別是十來個、很少動；項目是幾十個、
每個月都在加。合在一頁時，那一頁既沒辦法好好列類別（有子項目的類別根本沒有自己的列，
見 `catalog.py`），也沒辦法好好找項目（沒有篩選）。

**標題只在這一層。** 子頁不再各自畫一個 20pt 大標 —— 側邊欄已經說了在哪一頁、
分頁標籤已經說了是哪一個，第三次重複只是吃掉一行高度。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QTabWidget, QWidget

from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.pages.catalog import AccountsPage, CategoriesPage, ItemsPage
from tagcor_ledger.ui.pages.deposits import DepositsPage
from tagcor_ledger.ui.pages.recurring import RecurringPage
from tagcor_ledger.ui.pages.templates import TemplatesPage
from tagcor_ledger.ui.widgets.layout import TABLE_WIDTH, page_layout


class OperationSettingsPage(QWidget):
    apply_requested = Signal(dict)
    changed = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.accounts = AccountsPage(controller)
        self.categories = CategoriesPage(controller)
        self.items = ItemsPage(controller)
        self.templates = TemplatesPage(controller)
        self.recurring = RecurringPage(controller)
        self.deposits = DepositsPage(controller)
        self._build()

    def _tabs(self) -> tuple[tuple[QWidget, str], ...]:
        """分頁順序的唯一正本。`refresh()` 與漂移守門都讀它。"""
        return (
            (self.accounts, "帳戶"),
            (self.categories, "類別"),
            (self.items, "項目"),
            (self.templates, "模板"),
            (self.recurring, "定期收支"),
            (self.deposits, "定存"),
        )

    def _build(self) -> None:
        title = QLabel("操作設定")
        title.setObjectName("pageTitle")
        tabs = QTabWidget()
        tabs.setObjectName("settingsTabs")
        for page, label in self._tabs():
            tabs.addTab(page, label)
            page.changed.connect(self.changed.emit)
        layout = page_layout(self, width=TABLE_WIDTH)
        layout.addWidget(title)
        layout.addWidget(tabs)
        self.templates.apply_requested.connect(self.apply_requested.emit)

    def refresh(self) -> None:
        for page, _label in self._tabs():
            page.refresh()
