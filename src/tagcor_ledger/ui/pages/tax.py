"""稅務頁外殼與各分頁的固定順序。"""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtWidgets import QLabel, QTabWidget, QWidget

from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import TAX_PAGE_NOTE, TAX_PAGE_TITLE, TAX_TAB_LABELS
from tagcor_ledger.ui.pages.tax_data import TaxDataTab
from tagcor_ledger.ui.pages.tax_estimate import TaxEstimateTab
from tagcor_ledger.ui.pages.tax_law import TaxLawTab
from tagcor_ledger.ui.pages.tax_mapping import TaxMappingTab
from tagcor_ledger.ui.pages.tax_reminders import TaxRemindersTab
from tagcor_ledger.ui.widgets.layout import TABLE_WIDTH, page_layout


class TaxTab(StrEnum):
    REMINDERS = "reminders"
    ESTIMATE = "estimate"
    MAPPING = "mapping"
    DATA = "data"
    LAW = "law"


TaxTabPage = TaxRemindersTab | TaxEstimateTab | TaxMappingTab | TaxDataTab | TaxLawTab


class TaxPage(QWidget):
    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.tabs = QTabWidget()
        self.tabs.setObjectName("taxTabs")
        self.reminders = TaxRemindersTab(controller)
        self.estimate = TaxEstimateTab(controller)
        self.mapping = TaxMappingTab(controller)
        self.data = TaxDataTab(controller)
        self.law = TaxLawTab(controller)
        self._tab_pages: dict[TaxTab, TaxTabPage] = {
            TaxTab.REMINDERS: self.reminders,
            TaxTab.ESTIMATE: self.estimate,
            TaxTab.MAPPING: self.mapping,
            TaxTab.DATA: self.data,
            TaxTab.LAW: self.law,
        }
        self._build()
        self.tabs.currentChanged.connect(self._tab_changed)

    def _build(self) -> None:
        title = QLabel(TAX_PAGE_TITLE)
        title.setObjectName("pageTitle")
        note = QLabel(TAX_PAGE_NOTE)
        note.setObjectName("hintLabel")
        note.setWordWrap(True)

        for tab in TaxTab:
            page = self._tab_pages.get(tab)
            if page is not None:
                self.tabs.addTab(page, TAX_TAB_LABELS[tab.value])

        layout = page_layout(self, width=TABLE_WIDTH)
        layout.addWidget(title)
        layout.addWidget(note)
        layout.addWidget(self.tabs, 1)

    def refresh(self) -> None:
        page = self.tabs.currentWidget()
        if isinstance(page, (TaxRemindersTab, TaxEstimateTab, TaxMappingTab, TaxDataTab, TaxLawTab)):
            page.refresh()

    def _tab_changed(self, index: int) -> None:
        page = self.tabs.widget(index)
        if isinstance(page, (TaxRemindersTab, TaxEstimateTab, TaxMappingTab, TaxDataTab, TaxLawTab)):
            page.refresh()

    def show_tab(self, tab: TaxTab | str) -> None:
        """切到指定稅務分頁。"""
        try:
            selected = TaxTab(tab)
        except (TypeError, ValueError):
            selected = TaxTab.REMINDERS
        page = self._tab_pages[selected]
        self.tabs.setCurrentWidget(page)
