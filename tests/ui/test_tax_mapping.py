"""所得歸類分頁的年度摘要、對話框與重整行為。"""

from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import QLabel

from tagcor_ledger.domain.tax.kinds import (
    DeductionChoice,
    FilingStatus,
    Flow,
    INCOME_KIND_NAMES,
    IncomeKind,
)
from tagcor_ledger.domain.tax.records import TaxYearInputs
from tagcor_ledger.ui.navigation import PageId
from tagcor_ledger.ui.pages.tax import TaxTab
from tagcor_ledger.ui.widgets.simple_form import ChoiceField, SimpleFormDialog
import tagcor_ledger.ui.pages.tax_mapping as tax_mapping_page


def _category(controller, name: str, *, parent_id: str | None = None) -> str:
    result = controller.create_category(name, parent_id=parent_id)
    assert result.success, result.message
    return str(result.details["category_id"])


def _income(controller, category_id: str, amount: int, description: str) -> None:
    result = controller.submit(
        occurred_at="2025-04-10T12:00:00+08:00",
        entry_type="income",
        amount=str(amount),
        account_id="acct_cash",
        destination_account_id=None,
        category_id=category_id,
        description=description,
    )
    assert result.success, result.message


def test_mapping_warning_and_double_click_use_the_same_form(window, monkeypatch) -> None:
    window.controller.today_provider = lambda: date(2025, 5, 15)
    page = window.tax.mapping
    page.refresh()
    unmapped = _category(window.controller, "未歸類收入")
    parent = _category(window.controller, "所得類別")
    child = _category(window.controller, "子項目", parent_id=parent)
    assert window.controller.set_tax_mapping(
        category_id=parent, flow=Flow.INCOME, tax_kind=IncomeKind.SALARY.value
    ).success
    assert window.controller.set_tax_mapping(
        category_id=child,
        flow=Flow.INCOME,
        tax_kind=IncomeKind.INTEREST_TAXABLE.value,
    ).success
    _income(window.controller, unmapped, 100, "未歸類收入")
    _income(window.controller, child, 200, "項目覆蓋收入")
    page.refresh()
    page.year.setCurrentIndex(page.year.findData(2025))

    assert page.model.items[0]["mapping"].unmapped
    assert page.warning.text() == "2025：1 筆收入（100 元）未歸類。"
    assert page.warning.objectName() == "statusLabel"
    assert page.warning.property("state") == "error"
    child_row = next(
        row
        for row, item in enumerate(page.model.items)
        if item["mapping"].category_id == child
    )
    assert page.model.index(child_row, 5).data() == "已歸類（覆蓋類別）"
    assert window.controller.save_tax_year_inputs(
        TaxYearInputs(
            2025,
            FilingStatus.SINGLE,
            DeductionChoice.STANDARD,
            False,
            False,
            False,
            0,
            0,
            None,
            None,
        )
    ).success
    assert "unmapped_income" in {
        reason.value for reason in window.controller.tax_estimate(2025).refused
    }

    calls = []

    def choose_salary(_parent, title, fields):
        calls.append((title, fields))
        return {"income_kind": IncomeKind.SALARY, "expense_kind": None}

    monkeypatch.setattr(tax_mapping_page, "ask_form", choose_salary)
    page.table.selectRow(0)
    page.configure_button.click()

    assert page.warning.isHidden()
    assert "unmapped_income" not in {
        reason.value for reason in window.controller.tax_estimate(2025).refused
    }
    assert calls[0][0] == "設定所得歸類"
    assert calls[0][1][0].options[0] == ("未歸類", None)
    assert calls[0][1][0].notes[IncomeKind.SALARY]

    child_row = next(
        row
        for row, item in enumerate(page.model.items)
        if item["mapping"].category_id == child
    )
    page.table.selectRow(child_row)
    page.table.doubleClicked.emit(page.model.index(child_row, 0))
    assert len(calls) == 2


def test_simple_form_updates_the_selected_income_kind_note() -> None:
    from tagcor_ledger.domain.tax.kinds import INCOME_KIND_NOTES

    dialog = SimpleFormDialog(
        "歸類",
        [
            ChoiceField(
                "income_kind",
                "收入算作",
                [("未歸類", None), ("薪資所得", IncomeKind.SALARY)],
                notes=INCOME_KIND_NOTES,
            )
        ],
        None,
    )
    combo = dialog._widgets["income_kind"]
    note = dialog.findChild(QLabel, "hintLabel")
    assert note is not None
    assert note.text() == ""

    combo.setCurrentIndex(combo.findData(IncomeKind.SALARY))

    assert note.text() == INCOME_KIND_NOTES[IncomeKind.SALARY]


def test_mapping_year_note_tracks_the_selected_year(window, monkeypatch) -> None:
    window.controller.today_provider = lambda: date(2026, 5, 15)
    monkeypatch.setattr(window.controller, "tax_default_income_year", lambda: 2025)
    page = window.tax.mapping
    page.year.setCurrentIndex(page.year.findData(2025))
    page.refresh()

    assert page.year.currentData() == 2025
    assert page.year_note.text() == ""

    page.year.setCurrentIndex(page.year.findData(2026))
    assert page.year_note.text() == "年度進行中"

    page.year.setCurrentIndex(page.year.findData(2025))
    assert page.year_note.text() == ""


def test_mapping_configure_button_stays_in_view_above_table(window, qtbot) -> None:
    window.resize(1280, 760)
    window.show_page(PageId.TAX)
    window.tax.show_tab(TaxTab.MAPPING)
    page = window.tax.mapping
    qtbot.wait(20)

    scroll = window._page_scrolls[PageId.TAX]
    scroll.verticalScrollBar().setValue(0)
    viewport = scroll.viewport()
    button_rect = page.configure_button.rect().translated(
        page.configure_button.mapTo(viewport, page.configure_button.rect().topLeft())
    )
    assert viewport.rect().contains(button_rect)
    table_rect = page.table.rect().translated(
        page.table.mapTo(viewport, page.table.rect().topLeft())
    )
    assert button_rect.bottom() < table_rect.top()
    for note in page._note_labels:
        note_rect = note.rect().translated(note.mapTo(viewport, note.rect().topLeft()))
        assert note_rect.top() > table_rect.bottom()


def test_item_mapping_dialog_labels_the_inherited_income_kind(window, monkeypatch) -> None:
    parent = _category(window.controller, "薪資類別")
    child = _category(window.controller, "薪資項目", parent_id=parent)
    assert window.controller.set_tax_mapping(
        category_id=parent,
        flow=Flow.INCOME,
        tax_kind=IncomeKind.SALARY.value,
    ).success
    page = window.tax.mapping
    page.refresh()
    row_index = next(
        row
        for row, item in enumerate(page.model.items)
        if item["mapping"].category_id == child
    )
    selected_text: dict[str, str] = {}

    def inspect_dialog(parent_widget, title, fields):
        dialog = SimpleFormDialog(title, fields, parent_widget)
        combo = dialog._widgets["income_kind"]
        selected_text["income"] = combo.currentText()
        return None

    monkeypatch.setattr(tax_mapping_page, "ask_form", inspect_dialog)
    page.table.selectRow(row_index)
    page.configure_button.click()

    assert selected_text["income"] == f"沿用類別：{INCOME_KIND_NAMES[IncomeKind.SALARY]}"
