"""Transaction input panel for the Phase 2 MVP."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QWidget,
)

from tagcor_ledger.application.tags import TagCatalog
from tagcor_ledger.application.transactions import current_timestamp
from tagcor_ledger.domain.models import TagPath


class TransactionPanel(QWidget):
    submitted = pyqtSignal()

    def __init__(self, tag_catalog: TagCatalog) -> None:
        super().__init__()
        self.tag_catalog = tag_catalog
        self.occurred_at_input = QLineEdit(current_timestamp())
        self.entry_type_combo = QComboBox()
        self.l1_combo = QComboBox()
        self.l2_combo = QComboBox()
        self.l3_combo = QComboBox()
        self.l4_combo = QComboBox()
        self.amount_input = QLineEdit()
        self.description_input = QLineEdit()
        self.submit_button = QPushButton("紀錄")

        self._build_ui()
        self._connect_signals()
        self.reload_tags(tag_catalog)

    def _build_ui(self) -> None:
        self.entry_type_combo.addItem("支出", "expense")
        self.entry_type_combo.addItem("收入", "income")
        self.entry_type_combo.addItem("轉帳", "transfer")
        self.entry_type_combo.addItem("調整", "adjustment")
        self.amount_input.setPlaceholderText("金額")
        self.description_input.setPlaceholderText("描述")

        form = QFormLayout()
        form.addRow("時間", self.occurred_at_input)
        form.addRow("類型", self.entry_type_combo)

        tag_row = QHBoxLayout()
        tag_row.addWidget(self.l1_combo)
        tag_row.addWidget(self.l2_combo)
        tag_row.addWidget(self.l3_combo)
        tag_row.addWidget(self.l4_combo)
        form.addRow("標籤", tag_row)

        form.addRow("金額", self.amount_input)
        form.addRow("描述", self.description_input)
        form.addRow("", self.submit_button)
        self.setLayout(form)

        self.setTabOrder(self.occurred_at_input, self.entry_type_combo)
        self.setTabOrder(self.entry_type_combo, self.l1_combo)
        self.setTabOrder(self.l1_combo, self.l2_combo)
        self.setTabOrder(self.l2_combo, self.l3_combo)
        self.setTabOrder(self.l3_combo, self.l4_combo)
        self.setTabOrder(self.l4_combo, self.amount_input)
        self.setTabOrder(self.amount_input, self.description_input)
        self.setTabOrder(self.description_input, self.submit_button)

    def _connect_signals(self) -> None:
        self.l1_combo.currentIndexChanged.connect(self._reload_l2)
        self.l2_combo.currentIndexChanged.connect(self._reload_l3)
        self.l3_combo.currentIndexChanged.connect(self._reload_l4)
        self.submit_button.clicked.connect(self.submitted.emit)
        self.amount_input.returnPressed.connect(self.submitted.emit)
        self.description_input.returnPressed.connect(self.submitted.emit)

    def reload_tags(self, tag_catalog: TagCatalog) -> None:
        self.tag_catalog = tag_catalog
        self._fill_combo(self.l1_combo, self.tag_catalog.children_of(None, 1))
        self._reload_l2()

    def tag_path(self) -> TagPath:
        return TagPath(
            l1_id=self._current_data(self.l1_combo),
            l2_id=self._current_data(self.l2_combo),
            l3_id=self._current_data(self.l3_combo),
            l4_id=self._current_data(self.l4_combo),
        )

    def entry_type(self) -> str:
        return self._current_data(self.entry_type_combo)

    def occurred_at(self) -> str:
        return self.occurred_at_input.text().strip()

    def amount(self) -> str:
        return self.amount_input.text().strip()

    def description(self) -> str:
        return self.description_input.text().strip()

    def reset_after_submit(self) -> None:
        self.occurred_at_input.setText(current_timestamp())
        self.amount_input.clear()
        self.description_input.clear()
        self.amount_input.setFocus()

    def _reload_l2(self) -> None:
        self._fill_combo(self.l2_combo, self.tag_catalog.children_of(self._current_data_or_none(self.l1_combo), 2))
        self._reload_l3()

    def _reload_l3(self) -> None:
        self._fill_combo(self.l3_combo, self.tag_catalog.children_of(self._current_data_or_none(self.l2_combo), 3))
        self._reload_l4()

    def _reload_l4(self) -> None:
        self._fill_combo(self.l4_combo, self.tag_catalog.children_of(self._current_data_or_none(self.l3_combo), 4))

    @staticmethod
    def _fill_combo(combo: QComboBox, options: Any) -> None:
        combo.blockSignals(True)
        combo.clear()
        for option in options:
            combo.addItem(option.name, option.tag_id)
        combo.blockSignals(False)

    @staticmethod
    def _current_data(combo: QComboBox) -> str:
        value = combo.currentData()
        if not isinstance(value, str) or value == "":
            raise ValueError("Tag selection is incomplete.")
        return value

    @staticmethod
    def _current_data_or_none(combo: QComboBox) -> str | None:
        value = combo.currentData()
        return value if isinstance(value, str) and value else None
