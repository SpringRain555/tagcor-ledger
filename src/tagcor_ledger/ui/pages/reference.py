"""法規參考：查稅務與金融法規的精選條文。

**這一頁只查不算。** App 不計算稅額、不做申報、不依法規自動調整任何帳務數字 ——
法規會改，而自動調整過的帳沒有人看得懂當初為什麼是那個數字。

法規庫不存在時這一頁顯示怎麼建立，不是空白也不是錯誤 —— 記帳不依賴它。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.application.reference import DISCLAIMER, ReferenceEntry, is_stale
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import reference_entry_values
from tagcor_ledger.ui.widgets.table import RowsModel, set_button_role, setup_table


class ReferencePage(QWidget):
    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.topic = QComboBox()
        self.search = QLineEdit()
        self.status = QLabel()
        self.table = QTableView()
        self.model = RowsModel(
            ["法規", "條號", "標題", "版本", "複查"],
            reference_entry_values,
        )
        self.detail = QTextBrowser()
        self._entries: list[ReferenceEntry] = []
        self._build()
        self.refresh()

    def _build(self) -> None:
        title = QLabel("法規參考")
        title.setObjectName("pageTitle")

        disclaimer = QLabel(DISCLAIMER)
        disclaimer.setObjectName("errorLabel")
        disclaimer.setWordWrap(True)

        self.status.setObjectName("hintLabel")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)

        self.search.setPlaceholderText("搜尋條文、摘要或法規名稱，例如：存簿儲金、贈與")
        refresh_button = QPushButton("重新整理")
        set_button_role(refresh_button, "primary")

        filters = QHBoxLayout()
        filters.addWidget(QLabel("主題"))
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

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(disclaimer)
        layout.addWidget(self.status)
        layout.addLayout(filters)
        layout.addWidget(splitter, 1)

        self.topic.currentIndexChanged.connect(self.reload_entries)
        self.search.returnPressed.connect(self.reload_entries)
        refresh_button.clicked.connect(self.refresh)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self.show_selected())

    def refresh(self) -> None:
        status = self.controller.reference_status()
        if not status.success:
            self.status.setText(
                f"{status.message}\n{status.details.get('how', '')}\n"
                f"預期位置：{status.details.get('path', '')}"
            )
            self.topic.clear()
            self.model.replace_rows([])
            self.detail.setPlainText("")
            return

        meta = dict(status.details.get("meta", {}))
        self.status.setText(
            f"共 {meta.get('entry_count', '?')} 篇，建立於 {meta.get('built_at', '?')}。"
            "條文原文抓自全國法規資料庫，每篇都附來源網址與抓取時間。"
        )
        current = self.topic.currentData()
        self.topic.blockSignals(True)
        self.topic.clear()
        self.topic.addItem("全部主題", None)
        for item in self.controller.reference_topics():
            self.topic.addItem(f"{item['title']}（{item['entries']}）", item["topic"])
        index = self.topic.findData(current)
        if index >= 0:
            self.topic.setCurrentIndex(index)
        self.topic.blockSignals(False)
        self.reload_entries()

    def reload_entries(self) -> None:
        self._entries = self.controller.reference_entries(
            topic=self.topic.currentData(), keyword=self.search.text()
        )
        self.model.replace_rows(
            [
                {
                    "entry_id": entry.entry_id,
                    "law_name": entry.law_name,
                    "article": entry.article,
                    "title": entry.title,
                    "amended_date": entry.amended_date,
                    "stale": is_stale(entry.reviewed_at),
                }
                for entry in self._entries
            ]
        )
        self.detail.setPlainText("")

    def show_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None:
            return
        entry = next(
            (one for one in self._entries if one.entry_id == item["entry_id"]), None
        )
        if entry is None:
            return
        stale_note = (
            "<p><b>需複查</b>：這一篇超過半年沒有複查過，數字與條文可能已經修正。</p>"
            if is_stale(entry.reviewed_at)
            else ""
        )
        self.detail.setHtml(
            f"<h2>{entry.heading}　{entry.title}</h2>"
            f"{stale_note}"
            f"<p><b>白話摘要</b><br>{_html(entry.plain)}</p>"
            f"<p><b>對這個帳本的意義</b><br>{_html(entry.ledger_note)}</p>"
            f"<p><b>條文原文</b>（摘要與原文有出入時，以原文為準）</p>"
            f"<pre>{_escape(entry.body)}</pre>"
            f"<hr><p>主管機關：{entry.agency}　版本：{entry.amended_date}　"
            f"法律狀態：{entry.legal_status}</p>"
            f"<p>來源：{_escape(entry.source_url)}<br>"
            f"抓取時間：{entry.fetched_at}　複查日期：{entry.reviewed_at}</p>"
        )


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _html(text: str) -> str:
    """摘要是我們自己寫的 Markdown 粗體，轉成 HTML；其餘一律逸出。"""
    escaped = _escape(text)
    parts = escaped.split("**")
    rebuilt = []
    for index, part in enumerate(parts):
        rebuilt.append(f"<b>{part}</b>" if index % 2 else part)
    return "".join(rebuilt).replace("\n", "<br>")
