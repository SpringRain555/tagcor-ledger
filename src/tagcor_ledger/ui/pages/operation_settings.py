"""操作設定：帳戶、類別、模板與週期排程三個分頁的容器。

它自己沒有畫面邏輯，只負責把底下三頁的訊號往上轉。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.pages.automation import AutomationPage
from tagcor_ledger.ui.pages.catalog import CatalogPage


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
