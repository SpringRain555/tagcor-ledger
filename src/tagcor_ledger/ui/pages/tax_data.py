"""資料狀態分頁：稅務資料在哪、新不新、涵蓋哪些年度與來源，以及給 LLM session 的指示。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.application.result import Result
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import (
    QUESTION_INSTRUCTION,
    TAX_COPIED,
    TAX_COPY_BUTTON,
    TAX_DATASET_LOCATION_LABEL,
    TAX_DATA_COVERAGE_LABEL,
    TAX_DATA_ESTIMATED_LABEL,
    TAX_DATA_FRESHNESS_LABEL,
    TAX_DATA_SOURCES_LABEL,
    TAX_DATA_SOURCE_HEADERS,
    TAX_DATA_SUMMARY_LABEL,
    TAX_QUESTION_TITLE,
    TAX_UPDATE_TITLE,
    coverage_lines,
    dataset_location_text,
    estimated_window_lines,
    freshness_lines,
    tax_data_summary_lines,
    tax_source_values,
    update_instruction,
)
from tagcor_ledger.ui.widgets.layout import TABLE_WIDTH, page_layout
from tagcor_ledger.ui.widgets.table import RowsModel, setup_table


class TaxDataTab(QWidget):
    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.location = QLabel()
        self.location_value = QLabel()
        self.freshness = QVBoxLayout()
        self.summary = QVBoxLayout()
        self.coverage = QVBoxLayout()
        self.estimated = QVBoxLayout()
        self.sources_table = QTableView()
        self.sources_model = RowsModel(
            TAX_DATA_SOURCE_HEADERS,
            lambda row: tax_source_values(row["source"]),
        )
        self.update_edit = QPlainTextEdit()
        self.question_edit = QPlainTextEdit()
        self.copy_status = QLabel()
        self._build()
        self.refresh()

    def _build(self) -> None:
        self.location.setText(TAX_DATASET_LOCATION_LABEL)
        self.location_value.setWordWrap(True)
        self.freshness_label = QLabel(TAX_DATA_FRESHNESS_LABEL)
        self.summary_label = QLabel(TAX_DATA_SUMMARY_LABEL)
        self.coverage_label = QLabel(TAX_DATA_COVERAGE_LABEL)
        self.estimated_label = QLabel(TAX_DATA_ESTIMATED_LABEL)
        self.sources_label = QLabel(TAX_DATA_SOURCES_LABEL)
        for label in (
            self.freshness_label,
            self.summary_label,
            self.coverage_label,
            self.estimated_label,
            self.sources_label,
        ):
            label.setObjectName("sectionTitle")

        setup_table(self.sources_table, self.sources_model, stretch_column=5)
        self.update_edit.setReadOnly(True)
        self.question_edit.setReadOnly(True)
        self.copy_status.setObjectName("statusLabel")

        self.update_copy_button = QPushButton(TAX_COPY_BUTTON)
        self.question_copy_button = QPushButton(TAX_COPY_BUTTON)

        layout = page_layout(self, width=TABLE_WIDTH)
        layout.addWidget(self.location)
        layout.addWidget(self.location_value)
        layout.addWidget(self.freshness_label)
        layout.addLayout(self.freshness)
        layout.addWidget(self.summary_label)
        layout.addLayout(self.summary)
        layout.addWidget(self.coverage_label)
        layout.addLayout(self.coverage)
        layout.addWidget(self.estimated_label)
        layout.addLayout(self.estimated)
        layout.addWidget(self.sources_label)
        layout.addWidget(self.sources_table)
        layout.addLayout(self._instruction_row(TAX_UPDATE_TITLE, self.update_edit, self.update_copy_button))
        layout.addLayout(
            self._instruction_row(
                TAX_QUESTION_TITLE, self.question_edit, self.question_copy_button
            )
        )
        layout.addWidget(self.copy_status)
        layout.addStretch()

        self.update_copy_button.clicked.connect(lambda: self._copy(self.update_edit))
        self.question_copy_button.clicked.connect(lambda: self._copy(self.question_edit))

    @staticmethod
    def _instruction_row(
        title: str, edit: QPlainTextEdit, button: QPushButton
    ) -> QVBoxLayout:
        group = QVBoxLayout()
        group.addWidget(QLabel(title))
        row = QHBoxLayout()
        row.addWidget(edit, 1)
        row.addWidget(button)
        group.addLayout(row)
        return group

    def refresh(self) -> None:
        status = self.controller.tax_data_status()
        self.location_value.setText(dataset_location_text(status.path))
        self.location_value.setToolTip(str(status.path))
        self._replace_labels(self.freshness, freshness_lines(status.problems))

        reference = self.controller.reference_status()
        entry_count = self._reference_entry_count(reference)
        self._replace_labels(
            self.summary,
            tax_data_summary_lines(status, law_entry_count=entry_count),
        )
        self._replace_labels(self.coverage, coverage_lines(status))
        estimate_lines = estimated_window_lines(status)
        self.estimated_label.setVisible(bool(estimate_lines))
        self._replace_labels(self.estimated, estimate_lines)

        self.sources_model.replace_rows(
            [{"source": source} for source in status.sources]
        )
        today = self.controller.today_provider()
        self.update_edit.setPlainText(
            update_instruction(status.problems, today=today)
        )
        self.question_edit.setPlainText(QUESTION_INSTRUCTION)
        self.copy_status.clear()

    @staticmethod
    def _reference_entry_count(result: Result) -> int | None:
        if not result.success:
            return None
        meta = result.details.get("meta", {})
        if not isinstance(meta, dict):
            return None
        value = meta.get("entry_count")
        return value if isinstance(value, int) else None

    def _copy(self, edit: QPlainTextEdit) -> None:
        QApplication.clipboard().setText(edit.toPlainText())
        self.copy_status.setText(TAX_COPIED)

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                break
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    @classmethod
    def _replace_labels(cls, layout: QVBoxLayout, lines: list[str]) -> None:
        cls._clear_layout(layout)
        for line in lines:
            label = QLabel(line)
            label.setObjectName("hintLabel")
            label.setWordWrap(True)
            layout.addWidget(label)

