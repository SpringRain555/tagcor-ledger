"""稅務試算分頁的儲存、拒算與版面行為。"""

from __future__ import annotations

from datetime import date
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from tagcor_ledger.domain.tax.kinds import (
    DeductionChoice,
    FilingStatus,
    Flow,
    IncomeKind,
)
from tagcor_ledger.ui.navigation import PageId
from tagcor_ledger.ui.pages.tax import TaxTab


def _category(controller, name: str, *, parent_id: str | None = None) -> str:
    result = controller.create_category(name, parent_id=parent_id)
    assert result.success, result.message
    return str(result.details["category_id"])


def _income(
    controller,
    *,
    category_id: str,
    amount: int,
    occurred_on: str,
    description: str,
) -> None:
    result = controller.submit(
        occurred_at=f"{occurred_on}T12:00:00+08:00",
        entry_type="income",
        amount=str(amount),
        account_id="acct_cash",
        destination_account_id=None,
        category_id=category_id,
        description=description,
    )
    assert result.success, result.message


def _build_refund_case(window) -> None:
    controller = window.controller
    salary = _category(controller, "薪資")
    interest = _category(controller, "利息收入")
    deposit_interest = _category(controller, "定存利息", parent_id=interest)
    assert controller.set_tax_mapping(
        category_id=salary, flow=Flow.INCOME, tax_kind=IncomeKind.SALARY.value
    ).success
    assert controller.set_tax_mapping(
        category_id=deposit_interest,
        flow=Flow.INCOME,
        tax_kind=IncomeKind.INTEREST_TAXABLE.value,
    ).success
    for month in range(1, 13):
        _income(
            controller,
            category_id=salary,
            amount=100_000,
            occurred_on=f"2025-{month:02d}-15",
            description=f"薪資 {month}",
        )
    _income(
        controller,
        category_id=deposit_interest,
        amount=26_367,
        occurred_on="2025-02-01",
        description="定存利息實領",
    )


def _set_override(page, kind: IncomeKind, gross: str, withheld: str) -> None:
    page._override_fields[kind][0].setText(gross)
    page._override_fields[kind][1].setText(withheld)


def _visible_result_text(page) -> str:
    text = "\n".join(
        label.text()
        for label in page.result_column.findChildren(QLabel)
        if label.text() and not label.isHidden()
    )
    if not page.table.isHidden():
        cells = [
            str(page.model.index(row, column).data(Qt.ItemDataRole.DisplayRole))
            for row in range(page.model.rowCount())
            for column in range(page.model.columnCount())
        ]
        text += "\n" + "\n".join(cells)
    return text


def test_unsaved_year_is_prefilled_without_an_estimate(window, qtbot) -> None:
    window.resize(1280, 760)
    window.controller.today_provider = lambda: date(2025, 5, 15)
    window.show_page(PageId.TAX)
    window.tax.show_tab(TaxTab.ESTIMATE)
    page = window.tax.estimate
    page.refresh()
    qtbot.wait(20)

    assert page.year.currentData() == window.controller.tax_default_income_year()
    assert page.year.count() == 5
    assert page.year_note.text() == "年度進行中"
    assert page.filing.currentData() == FilingStatus.SINGLE
    assert page.deduction.currentData() == DeductionChoice.STANDARD
    assert page.dependents.value() == 0
    assert page.unsaved_note.text() == (
        "這一年還沒存過，先用預設值（自己單獨申報、標準扣除、沒有受扶養人）；"
        "按「儲存並試算」才會算。"
    )
    assert page.unsaved_result.text() == "按左邊的「儲存並試算」才會算。"
    assert page.table.isHidden()
    assert page.model.rowCount() == 0
    assert "70 歲以上的受扶養直系尊親屬" in page.dependents_note.text()
    assert "115 年度起也包括未成年的受扶養子女" in page.dependents_note.text()
    viewport = window._page_scrolls[PageId.TAX].viewport()
    for widget in (page.footer, page.unsaved_result):
        rect = widget.rect().translated(widget.mapTo(viewport, widget.rect().topLeft()))
        assert viewport.rect().contains(rect)


def test_unsaved_year_names_the_year_used_for_prefill(window) -> None:
    window.controller.today_provider = lambda: date(2026, 5, 15)
    window.show_page(PageId.TAX)
    window.tax.show_tab(TaxTab.ESTIMATE)
    page = window.tax.estimate
    page.refresh()
    page.year.setCurrentIndex(page.year.findData(2025))
    page.save_button.click()

    page.year.setCurrentIndex(page.year.findData(2026))

    assert page.unsaved_note.text() == (
        "這一年還沒存過，先帶入 2025 年度的設定；按「儲存並試算」才會算。"
    )
    assert page.unsaved_result.text() == "按左邊的「儲存並試算」才會算。"


def test_refund_case_saves_estimate_official_difference_and_hides_refusal_amounts(
    window,
) -> None:
    window.controller.today_provider = lambda: date(2025, 5, 15)
    page = window.tax.estimate
    page.refresh()
    _build_refund_case(window)
    _set_override(page, IncomeKind.SALARY, "1200000", "30000")
    _set_override(page, IncomeKind.INTEREST_TAXABLE, "30000", "3000")
    page.official_tax.setText("22000")

    page.save_button.click()

    estimate = window.controller.tax_estimate(2025)
    assert estimate.balance_minor == -11_500
    assert "估計：應退 11,500 元" in page.result_status.text()
    assert page.model.rowCount() > 0
    assert page.official_diff.text().startswith("與財政部相差")
    assert page._override_fields[IncomeKind.SALARY][4].text() == "帳本：12 筆 1,200,000 元"

    page.filing.setCurrentIndex(page.filing.findData(FilingStatus.WITH_SPOUSE))
    page.deduction.setCurrentIndex(page.deduction.findData(DeductionChoice.ITEMIZED))
    page.save_button.click()

    refusal_text = _visible_result_text(page)
    assert "與配偶合併申報不在試算範圍內" in refusal_text
    assert refusal_text.count("請改用財政部稅額試算。") == 1
    assert re.search(r"[0-9]", refusal_text) is None
    assert page.table.isHidden()
    assert page.model.rowCount() > 0


def test_override_amount_with_comma_shows_cell_error_without_saving(window) -> None:
    window.controller.today_provider = lambda: date(2025, 5, 15)
    page = window.tax.estimate
    page.refresh()
    gross, _withheld, gross_error, _withheld_error, _hint = page._override_fields[
        IncomeKind.SALARY
    ]
    gross.setText("1,000")

    page.save_button.click()

    assert "非負整數元" in gross_error.text()
    assert window.controller.tax_year_inputs(2025) is None
    assert page.table.isHidden()


def test_official_refund_balance_roundtrips_across_years(window) -> None:
    window.controller.today_provider = lambda: date(2025, 5, 15)
    page = window.tax.estimate
    page.refresh()
    page.official_balance_direction.setCurrentIndex(
        page.official_balance_direction.findData("refund")
    )
    page.official_balance.setText("500")

    page.save_button.click()
    saved = window.controller.tax_year_inputs(2025)
    assert saved is not None
    assert saved.official_balance_minor == -500

    page.year.setCurrentIndex(page.year.findData(2024))
    page.year.setCurrentIndex(page.year.findData(2025))
    assert page.official_balance_direction.currentText() == "應退"
    assert page.official_balance.text() == "500"


def test_estimate_column_geometry_keeps_fields_and_long_step_name_in_bounds(
    window, qtbot
) -> None:
    window.resize(1280, 760)
    window.controller.today_provider = lambda: date(2025, 5, 15)
    window.show_page(PageId.TAX)
    window.tax.show_tab(TaxTab.ESTIMATE)
    page = window.tax.estimate
    page.refresh()
    _build_refund_case(window)
    _set_override(page, IncomeKind.SALARY, "1200000", "30000")
    _set_override(page, IncomeKind.INTEREST_TAXABLE, "30000", "3000")
    page.save_button.click()
    qtbot.wait(20)

    viewport_width = page.input_scroll.viewport().width()
    assert page.input_scroll.widget().width() <= viewport_width
    for gross, withheld, *_rest in page._override_fields.values():
        for edit in (gross, withheld):
            left = edit.mapTo(page.input_scroll.viewport(), edit.rect().topLeft()).x()
            assert left >= 0
            assert left + edit.width() <= viewport_width
    override_widgets = []
    for kind, fields in page._override_fields.items():
        gross, withheld, _gross_error, _withheld_error, hint = fields
        override_widgets.extend((page._override_labels[kind], gross, withheld, hint))
    rects = [
        widget.rect().translated(
            widget.mapTo(page._override_grid_widget, widget.rect().topLeft())
        )
        for widget in override_widgets
    ]
    assert len(rects) == 16
    assert all(rect.isValid() for rect in rects)
    for index, rect in enumerate(rects):
        for other in rects[index + 1 :]:
            assert not rect.intersects(other)
    assert len(page._override_fields) == 4
    steps = [
        page.model.index(row, 0).data(Qt.ItemDataRole.DisplayRole)
        for row in range(page.model.rowCount())
    ]
    longest_step = max(steps, key=page.table.fontMetrics().horizontalAdvance)
    assert page.table.columnWidth(0) >= page.table.fontMetrics().horizontalAdvance(longest_step)
    column_widths = [page.table.columnWidth(column) for column in range(3)]
    assert sum(column_widths) <= page.table.viewport().width(), (
        column_widths,
        page.table.viewport().width(),
    )
    basis_width = page.table.columnWidth(2)
    basis_metrics = page.table.fontMetrics()
    basis_values = [page.table.model().headerData(2, Qt.Orientation.Horizontal)]
    basis_values.extend(
        page.model.index(row, 2).data(Qt.ItemDataRole.DisplayRole)
        for row in range(page.model.rowCount())
    )
    basis_overflows = [
        (str(value), basis_metrics.horizontalAdvance(str(value)))
        for value in basis_values
        if basis_metrics.horizontalAdvance(str(value)) > basis_width
    ]
    assert not basis_overflows, (basis_width, basis_overflows)
    footnote_rect = page.footnotes.rect().translated(
        page.footnotes.mapTo(page.result_column, page.footnotes.rect().topLeft())
    )
    assert page.footnotes.text()
    assert page.result_column.rect().contains(footnote_rect)


def test_estimate_status_and_footer_stay_in_view_for_result_and_refusal(
    window, qtbot
) -> None:
    window.resize(1280, 760)
    window.controller.today_provider = lambda: date(2025, 5, 15)
    window.show_page(PageId.TAX)
    window.tax.show_tab(TaxTab.ESTIMATE)
    page = window.tax.estimate
    page.refresh()
    _build_refund_case(window)
    _set_override(page, IncomeKind.SALARY, "1200000", "30000")
    _set_override(page, IncomeKind.INTEREST_TAXABLE, "30000", "3000")
    page.save_button.click()
    qtbot.wait(20)

    scroll = window._page_scrolls[PageId.TAX]
    scroll.verticalScrollBar().setValue(0)
    viewport = scroll.viewport()
    for widget in (page.result_status, page.footer):
        rect = widget.rect().translated(widget.mapTo(viewport, widget.rect().topLeft()))
        assert viewport.rect().contains(rect)

    page.filing.setCurrentIndex(page.filing.findData(FilingStatus.WITH_SPOUSE))
    page.save_button.click()
    qtbot.wait(20)

    for widget in (page.result_status, page.footer):
        rect = widget.rect().translated(widget.mapTo(viewport, widget.rect().topLeft()))
        assert viewport.rect().contains(rect)
