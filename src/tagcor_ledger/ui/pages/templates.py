"""模板：記帳時常用的組合，套用之後仍然要自己按儲存。

模板**不會自己變成交易**。它只是把一組欄位帶進記帳頁 —— 這與「手動輸入才感受得到
花費」的初衷一致。會自己到期的是定期收支與定存，那兩件事在別的分頁。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.application.result import Result
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import result_message, template_values
from tagcor_ledger.ui.widgets.draft_dialog import DraftDialog
from tagcor_ledger.ui.widgets.table import (
    SETTINGS_TABLE_ROWS,
    RowsModel,
    bind_selection,
    set_button_role,
    setup_table,
)


class TemplatesPage(QWidget):
    apply_requested = Signal(dict)
    changed = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.table = QTableView()
        self.model = RowsModel(
            ["名稱", "類型", "金額（TWD）", "備註"],
            template_values,
            amount_column=2,
        )
        self._build()
        self.refresh()

    def _build(self) -> None:
        add_button = QPushButton("新增模板")
        edit_button = QPushButton("編輯模板")
        apply_button = QPushButton("套用到記帳")
        archive_button = QPushButton("封存模板")
        set_button_role(add_button, "primary")
        set_button_role(apply_button, "primary")
        set_button_role(archive_button, "danger")

        row = QHBoxLayout()
        for button in (add_button, edit_button, apply_button, archive_button):
            row.addWidget(button)
        row.addStretch()

        setup_table(self.table, self.model, fit_content=True, fit_rows=SETTINGS_TABLE_ROWS)
        # 「新增」以外三顆都是對所選模板動作 —— 沒選就停用。
        bind_selection(self.table, edit_button, apply_button, archive_button)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.table)
        # 表格現在是固定高度（`fit_rows`），沒有這一行的話 QVBoxLayout 會把多餘的
        # 高度平均塞進每個 widget 之間 —— 按鈕與表格會浮在分頁中間。
        layout.addStretch()

        add_button.clicked.connect(lambda: self.edit(None))
        edit_button.clicked.connect(self.edit_selected)
        apply_button.clicked.connect(self.apply_selected)
        archive_button.clicked.connect(self.archive_selected)

    def refresh(self) -> None:
        self.model.replace_rows(self.controller.list_templates())

    def edit_selected(self) -> None:
        self.edit(self.model.selected_item(self.table))

    def edit(self, item: dict[str, Any] | None) -> None:
        dialog = DraftDialog(self.controller, schedule=False, current=item, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._finish(self.controller.save_template(dialog.saved_value))

    def apply_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is not None:
            self.apply_requested.emit(item)

    def archive_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is not None:
            self._finish(self.controller.archive_template(str(item["template_id"])))

    def _finish(self, result: Result) -> None:
        if not result.success:
            QMessageBox.warning(self, "操作失敗", result_message(result))
            return
        self.refresh()
        self.changed.emit()
