"""操作設定：帳戶、類別、模板與週期排程、定存四個分頁的容器。

它自己沒有畫面邏輯，只負責放標題與把底下四頁的訊號往上轉。

**標題只在這一層。** 子頁不再各自畫一個 20pt 大標 —— 側邊欄已經說了在哪一頁、
分頁標籤已經說了是哪一個，第三次重複只是吃掉一行高度。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.pages.automation import AutomationPage
from tagcor_ledger.ui.pages.catalog import CatalogPage
from tagcor_ledger.ui.pages.deposits import DepositsPage


class OperationSettingsPage(QWidget):
    apply_requested = Signal(dict)
    changed = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.accounts = CatalogPage(controller, "account")
        self.categories = CatalogPage(controller, "category")
        self.automation = AutomationPage(controller)
        self.deposits = DepositsPage(controller)
        self._build()

    def _build(self) -> None:
        title = QLabel("操作設定")
        title.setObjectName("pageTitle")
        tabs = QTabWidget()
        tabs.setObjectName("settingsTabs")
        tabs.addTab(self.accounts, "帳戶")
        tabs.addTab(self.categories, "類別／項目")
        tabs.addTab(self.automation, "模板與週期排程")
        tabs.addTab(self.deposits, "定存")
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(tabs)
        self.accounts.changed.connect(self.changed.emit)
        self.categories.changed.connect(self.changed.emit)
        self.automation.changed.connect(self.changed.emit)
        self.deposits.changed.connect(self.changed.emit)
        self.automation.apply_requested.connect(self.apply_requested.emit)

    def refresh(self) -> None:
        self.accounts.refresh()
        self.categories.refresh()
        self.automation.refresh()
        self.deposits.refresh()
