"""系統設定：一般設定、資料路徑、備份與還原、重製四個分頁的容器。

路徑改變與還原／重製都對外發同一個 `restored` 意義的訊號 —— 三者都會讓「目前開的是
哪個資料庫」改變，畫面要整份重載。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.pages.maintenance import MaintenancePage
from tagcor_ledger.ui.pages.reset import ResetPage
from tagcor_ledger.ui.pages.settings_general import GeneralSettingsPage
from tagcor_ledger.ui.pages.settings_paths import PathSettingsPage


class SystemSettingsPage(QWidget):
    saved = Signal()
    restored = Signal()
    paths_changed = Signal()

    def __init__(self, controller: LedgerController, paths: AppPaths) -> None:
        super().__init__()
        self.general = GeneralSettingsPage(controller, paths)
        self.paths = PathSettingsPage(controller)
        self.maintenance = MaintenancePage(controller)
        self.reset = ResetPage(controller)
        self._build()

    def _build(self) -> None:
        tabs = QTabWidget()
        tabs.setObjectName("settingsTabs")
        tabs.addTab(self.general, "一般設定")
        tabs.addTab(self.paths, "資料路徑")
        tabs.addTab(self.maintenance, "備份與還原")
        tabs.addTab(self.reset, "重製與還原")
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        self.general.saved.connect(self.saved.emit)
        self.paths.changed.connect(self.paths_changed.emit)
        self.maintenance.restored.connect(self.restored.emit)
        self.reset.reset_done.connect(self.restored.emit)

    def reload(self) -> None:
        self.general.reload()
        self.paths.reload()
        self.maintenance.refresh()
