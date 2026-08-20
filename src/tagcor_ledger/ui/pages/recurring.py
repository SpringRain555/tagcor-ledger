"""定期收支：訂閱、房租這種每隔一段時間自己到期的項目。

## 為什麼改叫「定期收支」

程式裡叫 `recurring_schedules`，UI 以前照字面翻成「週期排程」—— 那是**實作的名字**，
不是使用者腦子裡的東西。使用者想的是「每個月會自動扣款的那些」，而「排程」聽起來像
是某種背景工作。**程式識別字不動**（`recurring_schedules`、`schedule_id` 是 schema，
改它要 migration，而使用者根本看不到它）。

## 它與定存為什麼不合併

兩者都會產生待確認，但形狀不同：定期收支是「每 N 個月重複同一筆」，定存是
「一期一期滾、有利率與到期轉存方式」。合併只會做出一個裝了兩種表單的分頁。

## 到期不會自動入帳

「產生到期待確認項目」只是把到期的期次放進待確認頁；要不要成為交易，由使用者在那裡
按下確認決定。
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
from tagcor_ledger.ui.formatting import result_message, schedule_values
from tagcor_ledger.ui.widgets.draft_dialog import DraftDialog
from tagcor_ledger.ui.widgets.table import (
    SETTINGS_TABLE_ROWS,
    RowsModel,
    bind_selection,
    set_button_role,
    setup_table,
)


class RecurringPage(QWidget):
    changed = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.table = QTableView()
        self.model = RowsModel(
            ["名稱", "類型", "週期", "下次日期", "結束日期"],
            schedule_values,
        )
        self._build()
        self.refresh()

    def _build(self) -> None:
        add_button = QPushButton("新增定期收支")
        edit_button = QPushButton("編輯所選項目")
        archive_button = QPushButton("封存所選項目")
        generate_button = QPushButton("產生到期待確認項目")
        set_button_role(add_button, "primary")
        set_button_role(generate_button, "primary")
        set_button_role(archive_button, "danger")

        row = QHBoxLayout()
        for button in (add_button, edit_button, archive_button, generate_button):
            row.addWidget(button)
        row.addStretch()

        setup_table(self.table, self.model, fit_content=True, fit_rows=SETTINGS_TABLE_ROWS)
        bind_selection(self.table, edit_button, archive_button)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.table)
        # 表格現在是固定高度（`fit_rows`），沒有這一行的話 QVBoxLayout 會把多餘的
        # 高度平均塞進每個 widget 之間 —— 按鈕與表格會浮在分頁中間。
        layout.addStretch()

        add_button.clicked.connect(lambda: self.edit(None))
        edit_button.clicked.connect(self.edit_selected)
        archive_button.clicked.connect(self.archive_selected)
        generate_button.clicked.connect(self.generate_due)

    def refresh(self) -> None:
        self.model.replace_rows(self.controller.list_schedules())

    def edit_selected(self) -> None:
        self.edit(self.model.selected_item(self.table))

    def edit(self, item: dict[str, Any] | None) -> None:
        dialog = DraftDialog(self.controller, schedule=True, current=item, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._finish(self.controller.save_schedule(dialog.saved_value))

    def archive_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is not None:
            self._finish(self.controller.archive_schedule(str(item["schedule_id"])))

    def generate_due(self) -> None:
        result = self.controller.generate_due()
        if not result.success:
            QMessageBox.warning(self, "產生失敗", result_message(result))
            return
        generated = int(result.details.get("generated", 0))
        suffix = "，仍有更多漏期可繼續產生" if result.details.get("has_more") else ""
        QMessageBox.information(
            self, "產生完成", f"已產生 {generated} 期待確認項目{suffix}。"
        )
        self.changed.emit()

    def _finish(self, result: Result) -> None:
        if not result.success:
            QMessageBox.warning(self, "操作失敗", result_message(result))
            return
        self.refresh()
        self.changed.emit()
