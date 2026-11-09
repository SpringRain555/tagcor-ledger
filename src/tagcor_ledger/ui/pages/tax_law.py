"""這個分頁只查條文；稅額的估計在『試算』分頁，數字來自 reference/tax/dataset.json，不是從條文推算。

法規參考分頁搜尋離線條文並顯示來源內容。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QTextBrowser,
    QWidget,
)

from tagcor_ledger.application.reference import ReferenceEntry, is_stale
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import (
    TAX_LAW_ALL_TOPICS,
    TAX_LAW_HEADERS,
    TAX_LAW_REFRESH,
    TAX_LAW_SEARCH_PLACEHOLDER,
    TAX_LAW_TOPICS_LABEL,
    tax_law_entry_html,
    tax_law_entry_values,
    tax_law_missing_text,
    tax_law_status_hint,
    tax_law_topic_label,
)
from tagcor_ledger.ui.widgets.forms import combo_box
from tagcor_ledger.ui.widgets.layout import TABLE_WIDTH, page_layout
from tagcor_ledger.ui.widgets.table import RowsModel, setup_table


class TaxLawTab(QWidget):
    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.topic = combo_box()
        self.search = QLineEdit()
        self.status = QLabel()
        self.table = QTableView()
        self.model = RowsModel(
            TAX_LAW_HEADERS,
            lambda row: tax_law_entry_values(row["entry"], stale=row["stale"]),
        )
        self.detail = QTextBrowser()
        self._entries: list[ReferenceEntry] = []
        self._build()
        self.refresh()

    def _build(self) -> None:
        self.status.setObjectName("hintLabel")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)

        self.search.setPlaceholderText(TAX_LAW_SEARCH_PLACEHOLDER)
        refresh_button = QPushButton(TAX_LAW_REFRESH)

        filters = QHBoxLayout()
        filters.addWidget(QLabel(TAX_LAW_TOPICS_LABEL))
        filters.addWidget(self.topic)
        filters.addWidget(self.search, 1)
        filters.addWidget(refresh_button)

        setup_table(self.table, self.model, stretch_column=2)
        self.detail.setOpenExternalLinks(False)
        self.detail.setObjectName("referenceDetail")

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(1, 1)

        layout = page_layout(self, width=TABLE_WIDTH)
        layout.addWidget(self.status)
        layout.addLayout(filters)
        layout.addWidget(splitter, 1)

        self.topic.currentIndexChanged.connect(self.reload_entries)
        self.search.returnPressed.connect(self.reload_entries)
        refresh_button.clicked.connect(self.refresh)
        self.table.selectionModel().selectionChanged.connect(
            lambda *_: self.show_selected()
        )

    def refresh(self) -> None:
        result = self.controller.reference_status()
        if not result.success:
            full_path = str(result.details.get("path", ""))
            parts = Path(full_path).parts
            shown = str(Path(*parts[-2:])) if len(parts) > 2 else full_path
            self.status.setText(
                tax_law_missing_text(
                    result.message,
                    str(result.details.get("how", "")),
                    shown,
                )
            )
            self.status.setToolTip(full_path)
            self.topic.clear()
            self.model.replace_rows([])
            self.detail.clear()
            return

        meta = result.details.get("meta", {})
        if not isinstance(meta, dict):
            meta = {}
        self.status.setText(
            tax_law_status_hint(meta.get("entry_count", "?"), meta.get("built_at", "?"))
        )
        self.status.setToolTip("")
        current = self.topic.currentData()
        self.topic.blockSignals(True)
        self.topic.clear()
        self.topic.addItem(TAX_LAW_ALL_TOPICS, None)
        for item in self.controller.reference_topics():
            self.topic.addItem(
                tax_law_topic_label(item["title"], item["entries"]), item["topic"]
            )
        index = self.topic.findData(current)
        if index >= 0:
            self.topic.setCurrentIndex(index)
        self.topic.blockSignals(False)
        self.reload_entries()

    def reload_entries(self) -> None:
        today = self.controller.today_provider()
        self._entries = self.controller.reference_entries(
            topic=self.topic.currentData(), keyword=self.search.text()
        )
        rows = [
            {"entry": entry, "stale": is_stale(entry.reviewed_at, today=today)}
            for entry in self._entries
        ]
        self.model.replace_rows(rows)
        self.detail.clear()

    def show_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None:
            return
        entry = item["entry"]
        if not isinstance(entry, ReferenceEntry):
            return
        self.detail.setHtml(tax_law_entry_html(entry, stale=bool(item["stale"])))
