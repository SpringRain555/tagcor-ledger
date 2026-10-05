"""法規頁的條文說明：從資料庫來的每一個欄位都逸出。

以前只逸出了條文原文與網址，標題、主管機關、日期直接插進 `setHtml()`。法規庫是自己
產生的、內容可信，但「哪些欄位可以不逸出」不該靠逐一判斷 —— 所以這裡逐欄量。
"""

from __future__ import annotations

from tagcor_ledger.application.reference import ReferenceEntry
from tagcor_ledger.ui.pages.reference import entry_html

MARKUP = "<b>注入</b>"
ESCAPED = "&lt;b&gt;注入&lt;/b&gt;"

DATABASE_FIELDS = (
    "law_name",
    "article",
    "title",
    "agency",
    "amended_date",
    "legal_status",
    "source_url",
    "fetched_at",
    "reviewed_at",
    "plain",
    "ledger_note",
    "body",
)


def _entry(**overrides: str) -> ReferenceEntry:
    fields = {
        "entry_id": "K0050015-3",
        "topic": "postal-savings",
        "topic_title": "郵政儲金與存款",
        "law_name": "郵政儲金匯兌法",
        "article": "3",
        "title": "存簿儲金",
        "agency": "交通部",
        "amended_date": "民國 103 年 01 月 29 日",
        "legal_status": "現行",
        "source_url": "https://law.moj.gov.tw/",
        "fetched_at": "2026-08-18",
        "reviewed_at": "2026-08-18",
        "plain": "摘要",
        "ledger_note": "意義",
        "body": "條文",
    }
    fields.update(overrides)
    return ReferenceEntry(**fields)


def test_every_database_field_is_escaped() -> None:
    for field in DATABASE_FIELDS:
        html = entry_html(_entry(**{field: MARKUP}), stale=False)
        assert MARKUP not in html, f"{field} 沒有逸出"
        # 陽性對照：內容還在，只是變成字面文字 —— 不是被整段丟掉。
        assert ESCAPED in html, f"{field} 的內容不見了"


def test_the_summary_bold_markup_still_renders() -> None:
    """摘要是我們自己寫的 `**粗體**`，逸出之後仍然要轉成粗體。"""
    html = entry_html(_entry(plain="這是**重點**"), stale=False)
    assert "<b>重點</b>" in html


def test_the_review_note_follows_the_flag() -> None:
    assert "需複查" in entry_html(_entry(), stale=True)
    assert "需複查" not in entry_html(_entry(), stale=False)
