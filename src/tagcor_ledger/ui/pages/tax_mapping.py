"""所得與繳款稅目的類別／項目歸類分頁。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableView,
    QWidget,
)

from tagcor_ledger.domain.tax.kinds import Flow, IncomeKind, TaxKind
from tagcor_ledger.domain.tax.records import TaxMappingRow
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import (
    TAX_ESTIMATE_IN_PROGRESS,
    TAX_MAPPING_CONFIGURE_BUTTON,
    TAX_MAPPING_DIALOG_TITLE,
    TAX_MAPPING_EXPENSE_LABEL,
    TAX_MAPPING_HEADERS,
    TAX_MAPPING_INCOME_LABEL,
    TAX_MAPPING_INCOME_NOTES,
    TAX_MAPPING_NO_CHANGE,
    TAX_MAPPING_NOTE_LINES,
    TAX_MAPPING_SAVE_SUCCESS,
    TAX_MAPPING_YEAR_LABEL,
    result_message,
    tax_mapping_expense_options,
    tax_mapping_income_options,
    tax_mapping_values,
    tax_mapping_warning,
)
from tagcor_ledger.ui.widgets.forms import combo_box, select_data, show_status
from tagcor_ledger.ui.widgets.layout import TABLE_WIDTH, page_layout
from tagcor_ledger.ui.widgets.simple_form import ChoiceField, ask_form
from tagcor_ledger.ui.widgets.table import RowsModel, bind_selection, setup_table

YEAR_SPAN = 5


class TaxMappingTab(QWidget):
    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.year = combo_box()
        self.year_note = QLabel()
        self.warning = QLabel()
        self.status = QLabel()
        self.table = QTableView()
        self.model = RowsModel(
            TAX_MAPPING_HEADERS,
            lambda item: tax_mapping_values(item["mapping"]),
        )
        self.configure_button = QPushButton(TAX_MAPPING_CONFIGURE_BUTTON)
        self._note_labels = tuple(QLabel(text) for text in TAX_MAPPING_NOTE_LINES)
        self._build()
        self.year.currentIndexChanged.connect(self._year_changed)
        self.configure_button.clicked.connect(self._edit_selected)
        self.table.doubleClicked.connect(lambda *_args: self._edit_selected())
        self.refresh()

    def _build(self) -> None:
        for label in (self.year_note, self.warning, *self._note_labels):
            label.setObjectName("hintLabel")
            label.setWordWrap(True)
        self.warning.setObjectName("statusLabel")
        self.status.setObjectName("statusLabel")
        self.status.setWordWrap(True)
        for note in self._note_labels:
            note.setMaximumWidth(TABLE_WIDTH)

        year_row = QWidget()
        year_layout = QHBoxLayout(year_row)
        year_layout.setContentsMargins(0, 0, 0, 0)
        year_layout.addWidget(self.year, 0)
        year_layout.addWidget(self.year_note)
        year_layout.addWidget(self.configure_button)
        year_layout.addStretch()
        self.year_form = QFormLayout()
        self.year_form.addRow(TAX_MAPPING_YEAR_LABEL, year_row)

        setup_table(self.table, self.model, stretch_column=1)
        bind_selection(self.table, self.configure_button)

        layout = page_layout(self, width=TABLE_WIDTH, margins=(0, 0, 0, 0))
        layout.addLayout(self.year_form)
        layout.addWidget(self.warning)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.status)
        for note in self._note_labels:
            layout.addWidget(note)
        layout.addStretch()

    def refresh(self) -> None:
        self._refresh_years()
        self._load_rows()

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
        self._set_year_note(selected)

    def _year_changed(self, _index: int) -> None:
        year = self.year.currentData()
        if isinstance(year, int):
            self._set_year_note(year)
        self._load_rows()

    def _set_year_note(self, year: int) -> None:
        self.year_note.setText(
            TAX_ESTIMATE_IN_PROGRESS
            if year == self.controller.today_provider().year
            else ""
        )

    def _load_rows(self) -> None:
        year = self.year.currentData()
        if not isinstance(year, int):
            return
        rows = self.controller.tax_mapping_rows(year)
        self.model.replace_rows([{"mapping": row} for row in rows])
        unmapped = [row for row in rows if row.unmapped]
        count = sum(row.own_year_count for row in unmapped)
        amount = sum(row.own_year_minor for row in unmapped)
        if count:
            show_status(
                self.warning,
                tax_mapping_warning(year, count, amount),
                ok=False,
            )
        else:
            show_status(self.warning, "", ok=None)
        self.warning.setVisible(count > 0)

    def _selected_row(self) -> TaxMappingRow | None:
        item = self.model.selected_item(self.table)
        row = item.get("mapping") if item is not None else None
        return row if isinstance(row, TaxMappingRow) else None

    def _edit_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        values = ask_form(
            self,
            TAX_MAPPING_DIALOG_TITLE,
            [
                ChoiceField(
                    "income_kind",
                    TAX_MAPPING_INCOME_LABEL,
                    tax_mapping_income_options(row),
                    default=row.income_kind,
                    notes=TAX_MAPPING_INCOME_NOTES,
                ),
                ChoiceField(
                    "expense_kind",
                    TAX_MAPPING_EXPENSE_LABEL,
                    tax_mapping_expense_options(row),
                    default=row.expense_kind,
                ),
            ],
        )
        if values is None:
            return
        raw_income = values["income_kind"]
        raw_expense = values["expense_kind"]
        try:
            income_kind = IncomeKind(raw_income) if raw_income is not None else None
            expense_kind = TaxKind(raw_expense) if raw_expense is not None else None
        except ValueError:
            return

        changed = False
        mappings = (
            (Flow.INCOME, row.income_kind, income_kind),
            (Flow.EXPENSE, row.expense_kind, expense_kind),
        )
        for flow, current, selected in mappings:
            if current == selected:
                continue
            result = self.controller.set_tax_mapping(
                category_id=row.category_id,
                flow=flow,
                tax_kind=selected.value if selected is not None else None,
            )
            if not result.success:
                if changed:
                    self._load_rows()
                show_status(self.status, result_message(result), ok=False)
                return
            changed = True

        if changed:
            self._load_rows()
            show_status(self.status, TAX_MAPPING_SAVE_SUCCESS, ok=True)
        else:
            show_status(self.status, TAX_MAPPING_NO_CHANGE, ok=None)
