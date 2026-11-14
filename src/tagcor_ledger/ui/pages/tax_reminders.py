"""稅務提醒分頁：設定開關與標記目前週期。"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTableView, QWidget

from tagcor_ledger.domain.tax.kinds import ReminderMark, TaxKind
from tagcor_ledger.domain.tax.reminders import ReminderSwitch, ReminderView
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import (
    SWITCH_NAMES,
    TAX_REMINDER_ACTION_LABELS,
    TAX_REMINDER_HEADERS,
    TAX_REMINDER_NOTE_LINES,
    TAX_REMINDER_SWITCH_LABEL,
    result_message,
    tax_reminder_values,
)
from tagcor_ledger.ui.widgets.forms import combo_box, show_status
from tagcor_ledger.ui.widgets.layout import TABLE_WIDTH, page_layout
from tagcor_ledger.ui.widgets.table import RowsModel, bind_selection, set_button_role, setup_table


class TaxRemindersTab(QWidget):
    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.switch = combo_box()
        self.status = QLabel()
        self.table = QTableView()
        self.notes = tuple(QLabel(text) for text in TAX_REMINDER_NOTE_LINES)
        self.model = RowsModel(
            TAX_REMINDER_HEADERS,
            lambda item: tax_reminder_values(
                item["view"],
                switch=item["switch"],
                today=self.controller.today_provider(),
            ),
        )
        self._build()
        self.refresh()

    def _build(self) -> None:
        self.switch.setEditable(True)
        line = self.switch.lineEdit()
        if line is not None:
            line.setReadOnly(True)
        self.switch.addItem(SWITCH_NAMES[ReminderSwitch.ON], ReminderSwitch.ON)
        self.switch.addItem(SWITCH_NAMES[ReminderSwitch.OFF], ReminderSwitch.OFF)
        self.switch.setCurrentIndex(-1)
        self.switch.setEditText(SWITCH_NAMES[ReminderSwitch.UNSET])
        self.switch.setEnabled(False)
        # 下拉的寬度依選項（「開」「關」）算，而「未設定」是編輯框文字、不是選項 ——
        # 不給最小字數的話實機只看得到「定」。這個字數是以拉丁字母 X 的寬度計，
        # 一個中文字約兩個 X 寬，所以乘 2（只乘 1 時實機量過仍然不夠）。
        self.switch.setMinimumContentsLength(
            2 * max(len(name) for name in SWITCH_NAMES.values())
        )

        setup_table(self.table, self.model, stretch_column=5, fit_rows=5)
        for note in self.notes:
            note.setObjectName("hintLabel")
            note.setWordWrap(True)
        self.status.setObjectName("statusLabel")
        self.status.setWordWrap(True)

        self.handled_button = QPushButton(TAX_REMINDER_ACTION_LABELS[0])
        self.not_applicable_button = QPushButton(TAX_REMINDER_ACTION_LABELS[1])
        self.cancel_button = QPushButton(TAX_REMINDER_ACTION_LABELS[2])
        set_button_role(self.handled_button, "primary")
        for button in (self.not_applicable_button, self.cancel_button):
            button.setEnabled(False)

        actions = QHBoxLayout()
        actions.addWidget(QLabel(TAX_REMINDER_SWITCH_LABEL))
        actions.addWidget(self.switch)
        actions.addWidget(self.handled_button)
        actions.addWidget(self.not_applicable_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch()

        layout = page_layout(self, width=TABLE_WIDTH)
        layout.addWidget(self.table)
        layout.addLayout(actions)
        layout.addWidget(self.status)
        layout.addWidget(self.notes[0])
        layout.addWidget(self.notes[1])
        layout.addStretch()

        bind_selection(
            self.table,
            self.handled_button,
            self.not_applicable_button,
            self.cancel_button,
            enabled_when=self._has_cycle,
        )
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._show_selected())
        self.switch.currentIndexChanged.connect(self._switch_changed)
        self.handled_button.clicked.connect(lambda: self._set_mark(ReminderMark.HANDLED))
        self.not_applicable_button.clicked.connect(
            lambda: self._set_mark(ReminderMark.NOT_APPLICABLE)
        )
        self.cancel_button.clicked.connect(lambda: self._set_mark(None))

    @staticmethod
    def _has_cycle(item: dict[str, Any]) -> bool:
        view = item.get("view")
        return isinstance(view, ReminderView) and view.cycle is not None

    def refresh(self) -> None:
        selected_kind = self._selected_kind()
        views = self.controller.tax_reminder_views()
        switches = self.controller.tax_reminder_switches()
        rows = [{"view": view, "switch": switches[view.kind]} for view in views]
        self.model.replace_rows(rows)
        if selected_kind is not None:
            for row, item in enumerate(rows):
                view = item["view"]
                if isinstance(view, ReminderView) and view.kind is selected_kind:
                    self.table.selectRow(row)
                    break
        self._show_selected()

    def _selected_item(self) -> dict[str, Any] | None:
        return self.model.selected_item(self.table)

    def _selected_kind(self) -> TaxKind | None:
        item = self._selected_item()
        view = item.get("view") if item is not None else None
        return view.kind if isinstance(view, ReminderView) else None

    def _show_selected(self) -> None:
        item = self._selected_item()
        self.switch.blockSignals(True)
        if item is None:
            self.switch.setCurrentIndex(-1)
            self.switch.setEditText(SWITCH_NAMES[ReminderSwitch.UNSET])
            self.switch.setEnabled(False)
        else:
            switch = item["switch"]
            index = self.switch.findData(switch)
            self.switch.setCurrentIndex(index)
            if index < 0:
                self.switch.setEditText(SWITCH_NAMES[ReminderSwitch.UNSET])
            self.switch.setEnabled(True)
        self.switch.blockSignals(False)

    def _switch_changed(self, index: int) -> None:
        item = self._selected_item()
        if item is None or index < 0:
            return
        view = item["view"]
        raw_switch = self.switch.itemData(index)
        if not isinstance(view, ReminderView):
            return
        try:
            switch = ReminderSwitch(raw_switch)
        except ValueError:
            return
        result = self.controller.save_tax_reminder_switch(view.kind, switch)
        show_status(self.status, result_message(result), ok=result.success)
        if result.success:
            self.refresh()

    def _set_mark(self, mark: ReminderMark | None) -> None:
        item = self._selected_item()
        if item is None:
            return
        view = item["view"]
        if not isinstance(view, ReminderView) or view.cycle is None:
            return
        result = self.controller.mark_tax_reminder(view.kind, view.cycle.year, mark)
        show_status(self.status, result_message(result), ok=result.success)
        if result.success:
            self.refresh()
