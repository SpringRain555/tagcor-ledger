"""稅務頁的分頁、提醒、資料狀態與法規內容。"""

from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path

from PySide6.QtWidgets import QApplication

from tagcor_ledger.application.reference import ReferenceEntry
from tagcor_ledger.domain.tax.kinds import TaxKind
from tagcor_ledger.domain.tax.reminders import ReminderSwitch
from tagcor_ledger.ui.formatting import (
    TAX_NO_FRESHNESS_PROBLEMS,
    TAX_TAB_LABELS,
    tax_law_entry_html,
)
from tagcor_ledger.ui.navigation import PageId
from tagcor_ledger.ui.pages.tax import TaxTab


def _write_calendar(
    tmp_path: Path,
    monkeypatch,
    *,
    kinds: tuple[TaxKind, ...] = tuple(TaxKind),
) -> Path:
    baseline = Path(os.environ["TAGCOR_TAX_DATA"])
    dataset = json.loads(baseline.read_text(encoding="utf-8"))
    source_id = str(dataset["sources"][0]["id"])
    dataset["calendar"] = {
        "typical": {
            kind.value: {
                "start": "05-01",
                "end": "05-31",
                "basis": "測試用期間",
                "source_ids": [source_id],
            }
            for kind in kinds
        },
        "years": {},
    }
    target = tmp_path / "tax-dataset.json"
    target.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("TAGCOR_TAX_DATA", str(target))
    return target


def test_tax_page_exposes_the_declared_order_and_falls_back_to_reminders(window) -> None:
    assert [tab.value for tab in TaxTab] == [
        "reminders",
        "estimate",
        "mapping",
        "data",
        "law",
    ]
    assert [window.tax.tabs.tabText(i) for i in range(window.tax.tabs.count())] == [
        TAX_TAB_LABELS["reminders"],
        TAX_TAB_LABELS["data"],
        TAX_TAB_LABELS["law"],
    ]

    for tab in (TaxTab.ESTIMATE, TaxTab.MAPPING):
        window.tax.show_tab(tab)
        assert window.tax.tabs.currentWidget() is window.tax.reminders
    window.show_page(PageId.TAX)
    assert window.current_page_widget() is window.tax


def test_reminders_show_five_tax_items_and_switch_changes_persist(window) -> None:
    page = window.tax.reminders
    assert page.model.rowCount() == 5
    assert page.model.headers == ["稅目", "開關", "期間", "狀態", "去年繳款", "備註"]
    assert page.model.columnCount() == 6

    page.table.selectRow(1)
    assert page.switch.count() == 2
    assert page.switch.currentText() == "未設定"
    page.switch.setCurrentIndex(page.switch.findData(ReminderSwitch.ON))
    selected_kind = page.model.items[1]["view"].kind
    assert window.controller.tax_reminder_switches()[selected_kind] is ReminderSwitch.ON
    page.refresh()
    assert page.model.items[1]["switch"] is ReminderSwitch.ON
    assert page.model.index(1, 1).data() == "開"


def test_reminder_marking_and_cancelling_only_affect_a_current_cycle(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    _write_calendar(tmp_path, monkeypatch)
    from tagcor_ledger.app.paths import resolve_app_paths
    from tagcor_ledger.ui.main_window import MainWindow

    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    window.controller.today_provider = lambda: date(2026, 5, 15)
    page = window.tax.reminders
    page.refresh()
    page.table.selectRow(0)

    assert page.handled_button.isEnabled()
    page.handled_button.click()
    assert page.model.index(0, 3).data() == "已處理"
    page.not_applicable_button.click()
    assert page.model.index(0, 3).data() == "本年不適用"
    page.cancel_button.click()
    assert page.model.index(0, 3).data() == "期間中"


def test_missing_dataset_is_explained_and_update_instruction_uses_controller_date(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("TAGCOR_TAX_DATA", str(tmp_path / "missing-dataset.json"))
    from tagcor_ledger.app.paths import resolve_app_paths
    from tagcor_ledger.ui.main_window import MainWindow

    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    window.controller.today_provider = lambda: date(2026, 11, 9)
    page = window.tax.data
    page.refresh()

    freshness = [page.freshness.itemAt(i).widget().text() for i in range(page.freshness.count())]
    assert len(freshness) == 1
    assert "稅務資料不在" in freshness[0]
    assert "--today 2026-11-09" in page.update_edit.toPlainText()
    page.update_copy_button.click()
    assert QApplication.clipboard().text() == page.update_edit.toPlainText()
    assert page.copy_status.text() == "已複製。"
    page.question_copy_button.click()
    assert QApplication.clipboard().text() == page.question_edit.toPlainText()


def test_data_tab_shows_dataset_path_summary_coverage_and_sources(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    path = _write_calendar(tmp_path, monkeypatch)
    from tagcor_ledger.app.paths import resolve_app_paths
    from tagcor_ledger.ui.main_window import MainWindow

    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    window.controller.today_provider = lambda: date(2026, 5, 15)
    page = window.tax.data
    page.refresh()

    assert page.location_value.text().endswith("tax-dataset.json")
    assert page.location_value.toolTip() == str(path)
    assert page.freshness.count() == 1
    assert page.freshness.itemAt(0).widget().text() == TAX_NO_FRESHNESS_PROBLEMS
    assert page.summary.count() >= 3
    assert page.coverage.count() > 0
    assert page.sources_model.rowCount() > 0
    assert page.sources_model.columnCount() == 6


def test_law_tab_searches_and_uses_controller_date_for_review_flags(window) -> None:
    page = window.tax.law
    page.search.setText("存簿儲金")
    page.reload_entries()
    assert page.model.rowCount() > 0, "測試法規庫中有存簿儲金條文，應可由關鍵字找到"

    entry = page._entries[0]
    reviewed = date.fromisoformat(entry.reviewed_at)
    frozen_today = date(reviewed.year + 1, reviewed.month, 1)
    window.controller.today_provider = lambda: frozen_today
    page.refresh()
    assert page.model.index(0, 4).data() == "需複查"
    page.table.selectRow(0)
    assert "需複查" in page.detail.toPlainText()


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


def test_every_law_database_field_is_escaped() -> None:
    for field in DATABASE_FIELDS:
        html = tax_law_entry_html(_entry(**{field: MARKUP}), stale=False)
        assert MARKUP not in html, f"{field} 沒有逸出"
        assert ESCAPED in html, f"{field} 的內容不見了"


def test_law_summary_bold_markup_still_renders() -> None:
    html = tax_law_entry_html(_entry(plain="這是**重點**"), stale=False)
    assert "<b>重點</b>" in html


def test_law_review_note_follows_the_flag() -> None:
    assert "需複查" in tax_law_entry_html(_entry(), stale=True)
    assert "需複查" not in tax_law_entry_html(_entry(), stale=False)
