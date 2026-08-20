"""帳戶與類別／項目的維護，同一個類別用 `kind` 切換。

「刪除未使用」只在完全沒有歷史資料引用時成功；有引用就只能封存。這是刻意的 —— 刪掉
被引用的設定項會讓舊交易失去名稱。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import account_values, category_values, result_message
from tagcor_ledger.ui.widgets.table import (
    RowsModel,
    bind_selection,
    set_button_role,
    setup_table,
)


class CatalogPage(QWidget):
    changed = Signal()

    def __init__(self, controller: LedgerController, kind: str) -> None:
        super().__init__()
        self.controller = controller
        self.kind = kind
        headers = (
            ["帳戶", "目前餘額（TWD）", "狀態"]
            if kind == "account"
            else ["類別", "項目", "狀態"]
        )
        mapper = account_values if kind == "account" else category_values
        self.model = RowsModel(
            headers,
            mapper,
            amount_column=1 if kind == "account" else None,
        )
        self.table = QTableView()
        self._build()
        self.refresh()

    def _build(self) -> None:
        add_button = QPushButton("新增帳戶" if self.kind == "account" else "新增類別")
        add_child = QPushButton("新增項目")
        rename = QPushButton("重新命名")
        toggle = QPushButton("封存／恢復所選項目")
        delete_button = QPushButton("刪除未使用")
        set_button_role(add_button, "primary")
        set_button_role(add_child, "primary")
        set_button_role(delete_button, "danger")
        row = QHBoxLayout()
        row.addWidget(add_button)
        if self.kind == "category":
            row.addWidget(add_child)
        row.addWidget(rename)
        row.addWidget(toggle)
        row.addWidget(delete_button)
        row.addStretch()
        setup_table(self.table, self.model, fit_content=True)
        # 「新增」不需要選取，其餘三顆都是對所選項目動作 —— 沒選就停用。
        bind_selection(self.table, rename, toggle, delete_button)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.table)
        add_button.clicked.connect(self.add_item)
        add_child.clicked.connect(self.add_child)
        rename.clicked.connect(self.rename_selected)
        toggle.clicked.connect(self.toggle_selected)
        delete_button.clicked.connect(self.delete_selected)

    def refresh(self) -> None:
        if self.kind == "account":
            self.model.replace_rows(self.controller.account_options(include_archived=True))
            return
        rows: list[dict[str, Any]] = []
        parents = self.controller.category_options(include_archived=True)
        for parent in parents:
            children = self.controller.category_options(
                str(parent["category_id"]),
                include_archived=True,
            )
            if not children:
                rows.append({**parent, "parent_name": parent["name"]})
            for child in children:
                rows.append({**child, "parent_name": parent["name"]})
        self.model.replace_rows(rows)

    def add_item(self) -> None:
        name, accepted = QInputDialog.getText(
            self,
            "新增帳戶" if self.kind == "account" else "新增類別",
            "名稱",
        )
        if not accepted:
            return
        if self.kind == "account":
            balance, accepted = QInputDialog.getText(
                self,
                "新增帳戶",
                "期初餘額（TWD）",
                text="0",
            )
            if not accepted:
                return
            result = self.controller.create_account(name, balance)
        else:
            result = self.controller.create_category(name)
        self._finish(result)

    def add_child(self) -> None:
        parents = self.controller.category_options()
        if not parents:
            return
        labels = [str(item["name"]) for item in parents]
        selected, accepted = QInputDialog.getItem(
            self,
            "新增項目",
            "上層類別",
            labels,
            editable=False,
        )
        if not accepted:
            return
        name, accepted = QInputDialog.getText(self, "新增項目", "項目名稱")
        if accepted:
            parent_id = str(parents[labels.index(selected)]["category_id"])
            self._finish(self.controller.create_category(name, parent_id))

    def rename_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None or item["status"] != "active":
            return
        name, accepted = QInputDialog.getText(
            self,
            "重新命名",
            "名稱",
            text=str(item["name"]),
        )
        if not accepted:
            return
        result = (
            self.controller.rename_account(str(item["account_id"]), name)
            if self.kind == "account"
            else self.controller.rename_category(str(item["category_id"]), name)
        )
        self._finish(result)

    def toggle_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None:
            return
        active = item["status"] == "active"
        if self.kind == "account":
            result = (
                self.controller.archive_account(str(item["account_id"]))
                if active
                else self.controller.restore_account(str(item["account_id"]))
            )
        else:
            result = (
                self.controller.archive_category(str(item["category_id"]))
                if active
                else self.controller.restore_category(str(item["category_id"]))
            )
        self._finish(result)

    def delete_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None:
            return
        answer = QMessageBox.question(
            self,
            "確認刪除",
            "只會刪除完全未使用的設定項；已有歷史資料者請改用封存。是否繼續？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        result = (
            self.controller.delete_account(str(item["account_id"]))
            if self.kind == "account"
            else self.controller.delete_category(str(item["category_id"]))
        )
        self._finish(result)

    def _finish(self, result: Any) -> None:
        if not result.success:
            QMessageBox.warning(self, "操作失敗", result_message(result))
            return
        self.refresh()
        self.changed.emit()
