"""綜合所得稅試算分頁。"""

from __future__ import annotations

import re

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.domain.money import Money, MoneyError
from tagcor_ledger.domain.tax.kinds import (
    DeductionChoice,
    FilingStatus,
    IncomeKind,
    OVERRIDABLE_INCOME_KINDS,
)
from tagcor_ledger.domain.tax.records import TaxYearInputs, TaxYearOverride
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import (
    ESTIMATE_FOOTER,
    TAX_ESTIMATE_AMOUNT_ERROR,
    TAX_ESTIMATE_AMOUNT_PLACEHOLDER,
    TAX_ESTIMATE_BALANCE_DUE,
    TAX_ESTIMATE_BALANCE_REFUND,
    TAX_ESTIMATE_DEPENDENTS_70_PLUS_LABEL,
    TAX_ESTIMATE_DEPENDENTS_70_PLUS_NOTE,
    TAX_ESTIMATE_DEPENDENTS_LABEL,
    TAX_ESTIMATE_DEDUCTION_LABEL,
    TAX_ESTIMATE_FILING_LABEL,
    TAX_ESTIMATE_HEADERS,
    TAX_ESTIMATE_IN_PROGRESS,
    TAX_ESTIMATE_INPUT_TITLE,
    TAX_ESTIMATE_OFFICIAL_BALANCE_LABEL,
    TAX_ESTIMATE_OFFICIAL_TAX_LABEL,
    TAX_ESTIMATE_OFFICIAL_TITLE,
    TAX_ESTIMATE_OTHER_SPECIAL_LABEL,
    TAX_ESTIMATE_DEPENDENT_INCOME_LABEL,
    TAX_ESTIMATE_FILER_70_PLUS_LABEL,
    TAX_ESTIMATE_OVERRIDE_BLANK_NOTE,
    TAX_ESTIMATE_OVERRIDE_TITLE,
    TAX_ESTIMATE_RESULT_TITLE,
    TAX_ESTIMATE_SAVE_BUTTON,
    TAX_ESTIMATE_SAVE_SUCCESS,
    TAX_ESTIMATE_YEAR_LABEL,
    TAX_FILING_OPTIONS,
    TAX_DEDUCTION_OPTIONS,
    TAX_OVERRIDE_HEADERS,
    TAX_OVERRIDE_OPTIONS,
    TAX_ESTIMATE_UNSAVED_RESULT,
    caution_lines,
    estimate_line_values,
    estimate_source_footnote_markers,
    estimate_source_footnotes,
    estimate_status,
    official_diff_text,
    refusal_lines,
    result_message,
    tax_estimate_ledger_hint,
    tax_estimate_unsaved_note,
)
from tagcor_ledger.ui.widgets.forms import combo_box, select_data, show_status
from tagcor_ledger.ui.widgets.layout import TABLE_WIDTH, page_layout
from tagcor_ledger.ui.widgets.table import RowsModel, set_button_role, setup_table

MAX_DEPENDENTS = 99
YEAR_SPAN = 5
_INTEGER_AMOUNT = re.compile(r"[0-9]+")


class TaxEstimateTab(QWidget):
    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.year = combo_box()
        self.year_note = QLabel()
        self.unsaved_note = QLabel()
        self.filing = combo_box()
        self.deduction = combo_box()
        self.other_special = QCheckBox(TAX_ESTIMATE_OTHER_SPECIAL_LABEL)
        self.dependent_income = QCheckBox(TAX_ESTIMATE_DEPENDENT_INCOME_LABEL)
        self.filer_70_plus = QCheckBox(TAX_ESTIMATE_FILER_70_PLUS_LABEL)
        self.dependents = QSpinBox()
        self.dependents_70_plus = QSpinBox()
        self.dependents_note = QLabel(TAX_ESTIMATE_DEPENDENTS_70_PLUS_NOTE)
        self.official_tax = QLineEdit()
        self.official_tax_error = QLabel()
        self.official_balance_direction = combo_box()
        self.official_balance = QLineEdit()
        self.official_balance_error = QLabel()
        self.save_button = QPushButton(TAX_ESTIMATE_SAVE_BUTTON)
        self.save_status = QLabel()
        self.result_status = QLabel()
        self.unsaved_result = QLabel()
        self.refusal_box = QWidget()
        self.refusal_layout = QVBoxLayout(self.refusal_box)
        self.caution_box = QWidget()
        self.caution_layout = QVBoxLayout(self.caution_box)
        self.official_diff = QLabel()
        self.footer = QLabel(ESTIMATE_FOOTER)
        self.footnotes = QLabel()
        self.model = RowsModel(
            TAX_ESTIMATE_HEADERS,
            lambda item: estimate_line_values(
                item["line"],
                footnotes=item["footnotes"],
            ),
        )
        self.table = QTableView()
        self._override_fields: dict[
            IncomeKind, tuple[QLineEdit, QLineEdit, QLabel, QLabel, QLabel]
        ] = {}
        self._override_labels: dict[IncomeKind, QLabel] = {}
        self._inputs_saved = False
        self._build()
        self.year.currentIndexChanged.connect(self._year_changed)
        self.dependents.valueChanged.connect(self._sync_dependent_limit)
        self.save_button.clicked.connect(self.save_and_estimate)
        self.refresh()

    def _build(self) -> None:
        for filing_label, filing_value in TAX_FILING_OPTIONS:
            self.filing.addItem(filing_label, filing_value)
        for deduction_label, deduction_value in TAX_DEDUCTION_OPTIONS:
            self.deduction.addItem(deduction_label, deduction_value)
        self.dependents.setRange(0, MAX_DEPENDENTS)
        self.dependents_70_plus.setRange(0, 0)
        self.official_balance_direction.addItem(TAX_ESTIMATE_BALANCE_DUE, "due")
        self.official_balance_direction.addItem(TAX_ESTIMATE_BALANCE_REFUND, "refund")

        for text_label in (
            self.year_note,
            self.unsaved_note,
            self.dependents_note,
            self.save_status,
            self.official_diff,
        ):
            text_label.setObjectName(
                "hintLabel" if text_label is not self.save_status else "statusLabel"
            )
            text_label.setWordWrap(True)
        self.unsaved_result.setObjectName("hintLabel")
        self.unsaved_result.setWordWrap(True)
        self.result_status.setObjectName("statusLabel")
        self.result_status.setWordWrap(True)
        self.footer.setObjectName("hintLabel")
        self.footer.setWordWrap(True)
        self.footnotes.setObjectName("hintLabel")
        self.footnotes.setWordWrap(True)
        self._style_error(self.official_tax_error)
        self._style_error(self.official_balance_error)
        self._style_error(self.save_status, status=True)

        self.official_tax.setPlaceholderText(TAX_ESTIMATE_AMOUNT_PLACEHOLDER)
        self.official_balance.setPlaceholderText(TAX_ESTIMATE_AMOUNT_PLACEHOLDER)
        self.official_tax.setObjectName("officialTaxAmount")
        self.official_balance.setObjectName("officialBalanceAmount")
        set_button_role(self.save_button, "primary")
        setup_table(self.table, self.model, stretch_column=2)
        self.table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.model.modelReset.connect(self._fit_result_table)

        left_content = self._input_form()
        self.input_scroll = QScrollArea()
        self.input_scroll.setWidgetResizable(True)
        self.input_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.input_scroll.setWidget(left_content)

        self.result_status.setObjectName("statusLabel")
        result_column = QWidget()
        self.result_column = result_column
        result_layout = QVBoxLayout(result_column)
        result_layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel(TAX_ESTIMATE_RESULT_TITLE)
        title.setObjectName("sectionTitle")
        result_layout.addWidget(title)
        result_layout.addWidget(self.result_status)
        result_layout.addWidget(self.footer)
        result_layout.addWidget(self.unsaved_result)
        result_layout.addWidget(self.refusal_box)
        result_layout.addWidget(self.table)
        result_layout.addWidget(self.footnotes)
        result_layout.addWidget(self.caution_box)
        result_layout.addWidget(self.official_diff)
        result_layout.addStretch()

        columns = QSplitter(Qt.Orientation.Horizontal)
        columns.addWidget(self.input_scroll)
        columns.addWidget(result_column)
        columns.setStretchFactor(0, 4)
        columns.setStretchFactor(1, 6)
        # 初次版面完成後才分配比例，讓試算結果欄先取得六成寬度。
        QTimer.singleShot(
            0,
            lambda: columns.setSizes(
                [columns.width() * 2 // 5, columns.width() * 3 // 5]
            ),
        )

        layout = page_layout(self, width=TABLE_WIDTH, margins=(0, 0, 0, 0))
        layout.addWidget(columns, 1)

    def _input_form(self) -> QWidget:
        content = QWidget()
        content.setMinimumWidth(0)
        content.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 4, 4)
        title = QLabel(TAX_ESTIMATE_INPUT_TITLE)
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        year_row = QWidget()
        year_layout = QHBoxLayout(year_row)
        year_layout.setContentsMargins(0, 0, 0, 0)
        year_layout.addWidget(self.year, 1)
        year_layout.addWidget(self.year_note)
        form.addRow(TAX_ESTIMATE_YEAR_LABEL, year_row)
        form.addRow("", self.unsaved_note)
        form.addRow(TAX_ESTIMATE_FILING_LABEL, self.filing)
        form.addRow(TAX_ESTIMATE_DEDUCTION_LABEL, self.deduction)
        form.addRow("", self.other_special)
        form.addRow("", self.dependent_income)
        form.addRow("", self.filer_70_plus)
        form.addRow(TAX_ESTIMATE_DEPENDENTS_LABEL, self.dependents)
        dependents_70_plus_label = QLabel(TAX_ESTIMATE_DEPENDENTS_70_PLUS_LABEL)
        dependents_70_plus_label.setWordWrap(True)
        dependents_70_plus_label.setMaximumWidth(220)
        form.addRow(dependents_70_plus_label, self.dependents_70_plus)
        form.addRow("", self.dependents_note)
        layout.addLayout(form)

        override_title = QLabel(TAX_ESTIMATE_OVERRIDE_TITLE)
        override_title.setObjectName("sectionTitle")
        layout.addWidget(override_title)
        blank_note = QLabel(TAX_ESTIMATE_OVERRIDE_BLANK_NOTE)
        blank_note.setWordWrap(True)
        layout.addWidget(blank_note)
        layout.addWidget(self._override_grid())

        official_title = QLabel(TAX_ESTIMATE_OFFICIAL_TITLE)
        official_title.setObjectName("sectionTitle")
        layout.addWidget(official_title)
        official_form = QFormLayout()
        official_form.addRow(
            TAX_ESTIMATE_OFFICIAL_TAX_LABEL,
            self._amount_cell(self.official_tax, self.official_tax_error),
        )
        balance_row = QWidget()
        balance_layout = QHBoxLayout(balance_row)
        balance_layout.setContentsMargins(0, 0, 0, 0)
        balance_layout.addWidget(self.official_balance_direction)
        balance_layout.addWidget(self.official_balance, 1)
        official_form.addRow(
            TAX_ESTIMATE_OFFICIAL_BALANCE_LABEL,
            self._amount_cell(balance_row, self.official_balance_error),
        )
        layout.addLayout(official_form)
        layout.addWidget(self.save_button)
        layout.addWidget(self.save_status)
        layout.addStretch()
        return content

    def _override_grid(self) -> QWidget:
        grid_widget = QWidget()
        self._override_grid_widget = grid_widget
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        for column, label in enumerate(TAX_OVERRIDE_HEADERS[1:], start=1):
            header = QLabel(label)
            header.setObjectName("sectionTitle")
            grid.addWidget(header, 0, column)
        for index, (name, kind) in enumerate(TAX_OVERRIDE_OPTIONS):
            row_index = 1 + 3 * index
            gross = QLineEdit()
            withheld = QLineEdit()
            gross.setMaximumWidth(170)
            withheld.setMaximumWidth(170)
            gross.setPlaceholderText(TAX_ESTIMATE_AMOUNT_PLACEHOLDER)
            withheld.setPlaceholderText(TAX_ESTIMATE_AMOUNT_PLACEHOLDER)
            gross.setObjectName(f"taxOverrideGross_{kind.value}")
            withheld.setObjectName(f"taxOverrideWithheld_{kind.value}")
            gross_error = QLabel()
            withheld_error = QLabel()
            self._style_error(gross_error)
            self._style_error(withheld_error)
            gross_cell = self._amount_cell(gross, gross_error)
            withheld_cell = self._amount_cell(withheld, withheld_error)
            name_label = QLabel(name)
            name_label.setWordWrap(True)
            self._override_labels[kind] = name_label
            grid.addWidget(name_label, row_index, 0, 1, 3)
            grid.addWidget(gross_cell, row_index + 1, 1)
            grid.addWidget(withheld_cell, row_index + 1, 2)
            hint = QLabel()
            hint.setObjectName("hintLabel")
            hint.setWordWrap(True)
            grid.addWidget(hint, row_index + 2, 0, 1, 3)
            self._override_fields[kind] = (gross, withheld, gross_error, withheld_error, hint)
        return grid_widget

    @staticmethod
    def _amount_cell(edit: QWidget, error: QLabel) -> QWidget:
        cell = QWidget()
        layout = QVBoxLayout(cell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(edit)
        layout.addWidget(error)
        return cell

    @staticmethod
    def _style_error(label: QLabel, *, status: bool = False) -> None:
        label.setObjectName("statusLabel" if status else "errorLabel")
        label.setWordWrap(True)

    def refresh(self) -> None:
        self._refresh_years()
        self._load_year()

    def _refresh_years(self) -> None:
        today = self.controller.today_provider()
        years = tuple(range(today.year, today.year - YEAR_SPAN, -1))
        selected = self.year.currentData()
        if selected not in years:
            selected = self.controller.tax_default_income_year()
        if selected not in years:
            selected = years[0]
        self.year.blockSignals(True)
        self.year.clear()
        for year in years:
            self.year.addItem(str(year), year)
        select_data(self.year, selected)
        self.year.blockSignals(False)

    def _year_changed(self, _index: int) -> None:
        self._load_year()

    def _load_year(self) -> None:
        year = self.year.currentData()
        if not isinstance(year, int):
            return
        saved = self.controller.tax_year_inputs(year)
        inputs = saved or self.controller.tax_prefilled_inputs(year)
        self._inputs_saved = saved is not None
        if inputs is None:
            inputs = TaxYearInputs(
                year,
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
        self._load_inputs(inputs)
        self._load_overrides(year)
        self._set_year_notes(year)
        self.save_status.clear()
        self._render_estimate(year)

    def _load_inputs(self, inputs: TaxYearInputs) -> None:
        select_data(self.filing, inputs.filing)
        select_data(self.deduction, inputs.deduction)
        self.other_special.setChecked(inputs.other_special_deductions)
        self.dependent_income.setChecked(inputs.dependents_have_income)
        self.filer_70_plus.setChecked(inputs.filer_70_plus)
        self.dependents.setValue(inputs.dependents)
        self._sync_dependent_limit()
        self.dependents_70_plus.setValue(inputs.dependents_70_plus)
        self.official_tax.setText(
            "" if inputs.official_tax_minor is None else str(inputs.official_tax_minor)
        )
        balance = inputs.official_balance_minor
        select_data(self.official_balance_direction, "refund" if balance is not None and balance < 0 else "due")
        self.official_balance.setText("" if balance is None else str(abs(balance)))

    def _load_overrides(self, year: int) -> None:
        overrides = self.controller.tax_year_overrides(year)
        totals: dict[IncomeKind, tuple[int, int]] = {
            kind: (0, 0) for kind in OVERRIDABLE_INCOME_KINDS
        }
        for row in self.controller.tax_mapping_rows(year):
            kind = row.effective_income_kind
            if kind not in totals:
                continue
            count, amount = totals[kind]
            totals[kind] = (count + row.own_year_count, amount + row.own_year_minor)

        for kind, fields in self._override_fields.items():
            gross, withheld, gross_error, withheld_error, hint = fields
            override = overrides.get(kind)
            gross.setText(
                "" if override is None or override.gross_minor is None else str(override.gross_minor)
            )
            withheld.setText(
                ""
                if override is None or override.withheld_minor is None
                else str(override.withheld_minor)
            )
            gross_error.clear()
            withheld_error.clear()
            count, amount = totals[kind]
            hint.setText(tax_estimate_ledger_hint(count, amount))

    def _set_year_notes(self, year: int) -> None:
        today = self.controller.today_provider()
        self.year_note.setText(TAX_ESTIMATE_IN_PROGRESS if year == today.year else "")
        self.unsaved_note.setText(
            ""
            if self._inputs_saved
            else tax_estimate_unsaved_note(
                self.controller.tax_prefill_source_year(year)
            )
        )
        self.unsaved_note.setVisible(not self._inputs_saved)

    def _fit_result_table(self) -> None:
        rows = self.model.rowCount()
        header_height = self.table.horizontalHeader().sizeHint().height()
        row_height = self.table.verticalHeader().defaultSectionSize()
        self.table.setFixedHeight(
            header_height + rows * row_height + 2 * self.table.frameWidth()
        )

    def _sync_dependent_limit(self, _value: int | None = None) -> None:
        self.dependents_70_plus.setMaximum(self.dependents.value())

    def _render_estimate(self, year: int) -> None:
        self._clear_layout(self.refusal_layout)
        self._clear_layout(self.caution_layout)
        self.official_diff.clear()
        self.footnotes.clear()
        self.footnotes.hide()
        if not self._inputs_saved:
            self.result_status.clear()
            self.result_status.hide()
            self.refusal_box.hide()
            self.table.hide()
            self.caution_box.hide()
            self.official_diff.hide()
            self.unsaved_result.setText(TAX_ESTIMATE_UNSAVED_RESULT)
            self.unsaved_result.show()
            return

        self.unsaved_result.clear()
        self.unsaved_result.hide()
        estimate = self.controller.tax_estimate(year)
        self.result_status.setText(estimate_status(estimate))
        self.result_status.show()
        if estimate.refused:
            for line in refusal_lines(estimate):
                label = QLabel(line)
                label.setObjectName("hintLabel")
                label.setWordWrap(True)
                self.refusal_layout.addWidget(label)
            self.refusal_box.show()
            self.table.hide()
            self.caution_box.hide()
            self.official_diff.hide()
            return

        self.refusal_box.hide()
        sources = {source.id: source for source in self.controller.tax_data_status().sources}
        footnote_markers = estimate_source_footnote_markers(estimate)
        self.model.replace_rows(
            [
                {"line": line, "footnotes": footnote_markers}
                for line in estimate.lines
            ]
        )
        footnotes = estimate_source_footnotes(estimate, sources)
        self.footnotes.setText("\n".join(footnotes))
        self.footnotes.setVisible(bool(footnotes))
        self.table.show()
        cautions = caution_lines(estimate)
        for line in cautions:
            label = QLabel(line)
            label.setObjectName("hintLabel")
            label.setWordWrap(True)
            self.caution_layout.addWidget(label)
        self.caution_box.setVisible(bool(cautions))
        difference = official_diff_text(estimate)
        self.official_diff.setText(difference or "")
        self.official_diff.setVisible(difference is not None)

    def save_and_estimate(self) -> None:
        self._clear_errors()
        year = self.year.currentData()
        if not isinstance(year, int):
            return
        parsed_overrides: dict[IncomeKind, tuple[int | None, int | None]] = {}
        invalid = False
        for kind, fields in self._override_fields.items():
            gross, withheld, gross_error, withheld_error, _hint = fields
            gross_value, gross_ok = self._parse_amount(gross.text(), gross_error)
            withheld_value, withheld_ok = self._parse_amount(withheld.text(), withheld_error)
            parsed_overrides[kind] = (gross_value, withheld_value)
            invalid = invalid or not gross_ok or not withheld_ok
        official_tax, tax_ok = self._parse_amount(self.official_tax.text(), self.official_tax_error)
        official_balance_amount, balance_ok = self._parse_amount(
            self.official_balance.text(), self.official_balance_error
        )
        invalid = invalid or not tax_ok or not balance_ok
        if invalid:
            return

        balance: int | None = official_balance_amount
        if balance is not None and self.official_balance_direction.currentData() == "refund":
            balance = -balance
        inputs = TaxYearInputs(
            income_year=year,
            filing=FilingStatus(self.filing.currentData()),
            deduction=DeductionChoice(self.deduction.currentData()),
            other_special_deductions=self.other_special.isChecked(),
            dependents_have_income=self.dependent_income.isChecked(),
            filer_70_plus=self.filer_70_plus.isChecked(),
            dependents=self.dependents.value(),
            dependents_70_plus=self.dependents_70_plus.value(),
            official_tax_minor=official_tax,
            official_balance_minor=balance,
        )
        result = self.controller.save_tax_year_inputs(inputs)
        if not result.success:
            show_status(self.save_status, result_message(result), ok=False)
            return
        for kind, (gross_minor, withheld_minor) in parsed_overrides.items():
            result = self.controller.save_tax_year_override(
                TaxYearOverride(year, kind, gross_minor, withheld_minor)
            )
            if not result.success:
                show_status(self.save_status, result_message(result), ok=False)
                return

        self._load_year()
        show_status(self.save_status, TAX_ESTIMATE_SAVE_SUCCESS, ok=True)

    def _parse_amount(self, text: str, error: QLabel) -> tuple[int | None, bool]:
        value = text.strip()
        if not value:
            return None, True
        if _INTEGER_AMOUNT.fullmatch(value) is None:
            error.setText(TAX_ESTIMATE_AMOUNT_ERROR)
            return None, False
        try:
            amount = Money.from_decimal_string(value, allow_zero=True).amount_minor
        except MoneyError:
            error.setText(TAX_ESTIMATE_AMOUNT_ERROR)
            return None, False
        return amount, True

    def _clear_errors(self) -> None:
        self.official_tax_error.clear()
        self.official_balance_error.clear()
        for fields in self._override_fields.values():
            fields[2].clear()
            fields[3].clear()

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                break
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
