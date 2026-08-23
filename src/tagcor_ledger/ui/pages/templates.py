"""模板：記帳時常用的組合，填進記帳頁之後仍然要自己按儲存。

模板**不會自己變成交易**。它只是把一組欄位帶進記帳頁 —— 這與「手動輸入才感受得到
花費」的初衷一致。會自己到期的是定存，那件事在別的分頁。

## 「封存」以前等於刪除

v0.22.0 之前這一頁只列使用中的模板（`refresh()` 沒有帶 `include_archived`），
而 store／application／controller **三層都沒有 `restore_template`**。按下「封存」
之後那一列就從畫面上永遠消失，只有「排序設定」視窗還看得到它（灰色）。

代價不只是「少一顆恢復按鈕」：`delete_account()` 的引用檢查涵蓋
`transaction_templates`，所以**一個看不見的封存模板會讓它引用的帳戶與類別永遠
刪不掉**，而使用者連是什麼東西擋著都不知道。現在這一頁列出全部並帶狀態欄，
封存與刪除是兩條分開的路 —— 與帳戶／類別／項目三頁同一套。
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
from tagcor_ledger.domain.models import SortLevel
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import result_message, template_values
from tagcor_ledger.ui.widgets.reorder_dialog import ReorderEntry, ask_order
from tagcor_ledger.ui.widgets.template_dialog import TemplateDialog
from tagcor_ledger.ui.widgets.table import (
    SETTINGS_TABLE_ROWS,
    RowsModel,
    bind_selection,
    set_button_role,
    setup_table,
)


SORT_PAGE = "templates"
SORT_FIELDS: tuple[tuple[str, str], ...] = (
    ("自訂順序", "custom"),
    ("模板名稱", "name"),
    ("類型", "entry_type"),
    ("金額", "amount"),
)
"""排序視窗裡可以選的欄位。key 必須在 `TEMPLATE_SORT_FIELDS` 白名單裡。

**「模板」這一頁不是 `CatalogPage` 的子類**（它沒有新增／改名／封存那一組共用按鈕，
只有自己的四顆），所以這幾個常數放在模組層而不是類別屬性上。"""

DEFAULT_SORT: tuple[SortLevel, ...] = (SortLevel(field="custom"),)
"""還沒設定過時用的規格。**不能用空的** —— 空規格填進排序視窗會退成「下拉裡的
第一個」，那不是一個想清楚過的預設值。"""


class TemplatesPage(QWidget):
    apply_requested = Signal(dict)
    changed = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.sort: tuple[SortLevel, ...] = controller.sort_spec(SORT_PAGE) or DEFAULT_SORT
        self.table = QTableView()
        # 欄位形狀刻意與交易紀錄一致（日期換成名稱）—— 兩張表講的是同一種東西，
        # 而「這個模板是從哪個帳戶付、記到哪個項目」正是挑模板時要看的。
        self.model = RowsModel(
            ["模板名稱", "類型", "帳戶", "類別", "金額（TWD）", "備註", "狀態"],
            template_values,
            amount_column=4,
        )
        self._build()
        self.refresh()

    def _build(self) -> None:
        add_button = QPushButton("新增模板")
        edit_button = QPushButton("編輯模板")
        apply_button = QPushButton("填入記帳頁")
        toggle_button = QPushButton("封存／恢復所選模板")
        delete_button = QPushButton("刪除模板")
        self.order_button = QPushButton("排序設定")
        self.order_button.setToolTip("開一個視窗，用拖曳排出自己想要的模板順序。")
        set_button_role(add_button, "primary")
        set_button_role(apply_button, "primary")
        # **「封存／恢復」不再是 danger。** 它現在真的可逆了，紅色留給下面那顆 ——
        # 畫面上的紅色要對應「按下去救不回來」，不是「這個動作比較嚴重」。
        set_button_role(delete_button, "danger")

        row = QHBoxLayout()
        for button in (
            add_button,
            edit_button,
            apply_button,
            toggle_button,
            delete_button,
            self.order_button,
        ):
            row.addWidget(button)
        row.addStretch()

        setup_table(self.table, self.model, fit_content=True, fit_rows=SETTINGS_TABLE_ROWS)
        # 「新增」與「排序設定」以外四顆都是對所選模板動作 —— 沒選就停用。
        bind_selection(self.table, edit_button, apply_button, toggle_button, delete_button)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.table)
        # 表格現在是固定高度（`fit_rows`），沒有這一行的話 QVBoxLayout 會把多餘的
        # 高度平均塞進每個 widget 之間 —— 按鈕與表格會浮在分頁中間。
        layout.addStretch()

        add_button.clicked.connect(lambda: self.edit(None))
        edit_button.clicked.connect(self.edit_selected)
        apply_button.clicked.connect(self.apply_selected)
        toggle_button.clicked.connect(self.toggle_selected)
        delete_button.clicked.connect(self.delete_selected)
        self.order_button.clicked.connect(self.edit_order)

    def edit_order(self) -> None:
        """模板只有一組。**拖曳清單列出全部（含封存的）**，因為它排的是儲存順序。"""
        rows = self.controller.list_templates(include_archived=True)
        dialog = ask_order(
            self,
            "模板排序",
            [
                ReorderEntry(
                    identifier=str(row["template_id"]),
                    name=str(row["name"]),
                    archived=row["status"] != "active",
                )
                for row in rows
            ],
            caption="自訂順序（拖曳）",
            sort_fields=SORT_FIELDS,
            sort_spec=self.sort,
        )
        if dialog is None:
            return
        # 規格先存、再套順序 —— 反過來的話存檔失敗時畫面已經照新規格重畫了。
        result = self.controller.save_sort_spec(SORT_PAGE, dialog.sort_spec())
        if result.success:
            self.sort = dialog.sort_spec()
            result = self.controller.set_template_order(dialog.parent_order())
        self._finish(result)

    def refresh(self) -> None:
        """**列出全部，包含已封存的。**

        這一頁是管理頁，看不到封存的東西就沒辦法恢復它 —— 與「類別」「項目」兩頁
        的狀態篩選預設是「全部」同一個理由。這裡不做篩選列：模板通常只有十來個，
        一條搜尋框對它沒有幫助。
        """
        self.model.replace_rows(
            self.controller.list_templates(include_archived=True, sort=self.sort)
        )

    def edit_selected(self) -> None:
        self.edit(self.model.selected_item(self.table))

    def edit(self, item: dict[str, Any] | None) -> None:
        dialog = TemplateDialog(self.controller, current=item, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._finish(self.controller.save_template(dialog.saved_value))

    def apply_selected(self) -> None:
        """**已封存的模板也填得進去，這是刻意的。**

        「填入」只是把欄位帶到記帳頁，使用者仍然要自己按儲存 —— 真正的守門在儲存
        那一刻（帳戶或類別若已封存會被擋下並說出原因）。在這裡多加一道停用，等於
        為了一個不會出錯的情況新增一套只有這一頁有的規則。
        """
        item = self.model.selected_item(self.table)
        if item is not None:
            self.apply_requested.emit(item)

    def toggle_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None:
            return
        template_id = str(item["template_id"])
        active = item["status"] == "active"
        self._finish(
            self.controller.archive_template(template_id)
            if active
            else self.controller.restore_template(template_id)
        )

    def delete_selected(self) -> None:
        """刪除模板。**沒有「未使用」這個條件** —— 沒有任何東西引用得到模板。

        套用模板產生的是一筆獨立的交易，那筆交易不記得自己從哪個模板來，所以刪掉
        模板動不到任何歷史資料。確認框要把這件事講出來，否則使用者會以為刪模板會
        連帶影響已經記過的帳。
        """
        item = self.model.selected_item(self.table)
        if item is None:
            return
        answer = QMessageBox.question(
            self,
            "確認刪除",
            f"確定要刪除模板「{item['name']}」嗎？\n\n"
            "刪掉就沒有了。已經用它記過的交易不受影響 —— 模板只是預填用的，"
            "交易存下來之後就與它無關。\n\n"
            "只是暫時不想用的話，改按「封存／恢復所選模板」。",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._finish(self.controller.delete_template(str(item["template_id"])))

    def _finish(self, result: Result) -> None:
        if not result.success:
            QMessageBox.warning(self, "操作失敗", result_message(result))
            return
        self.refresh()
        self.changed.emit()
