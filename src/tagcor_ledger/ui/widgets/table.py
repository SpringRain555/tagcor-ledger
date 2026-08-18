"""所有列表頁共用的表格 model 與外觀設定。

`RowsModel` 存的是 controller 給的原始 dict，顯示字串由 `mapper` 現算。所以
`selected_item()` 拿得到完整的那一列（含 id、revision 這些沒顯示出來的欄位），
頁面不需要為了拿 id 而把 id 塞進某個看不見的欄位。
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtWidgets import QAbstractItemView, QPushButton, QTableView


class RowsModel(QAbstractTableModel):
    def __init__(
        self,
        headers: list[str],
        mapper: Callable[[dict[str, Any]], list[str]],
    ) -> None:
        super().__init__()
        self.headers = headers
        self.mapper = mapper
        self.items: list[dict[str, Any]] = []

    def replace_rows(self, items: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self.items = items
        self.endResetModel()

    def selected_item(self, table: QTableView) -> dict[str, Any] | None:
        rows = table.selectionModel().selectedRows()
        return self.items[rows[0].row()] if rows else None

    def rowCount(  # noqa: N802
        self,
        parent: QModelIndex | QPersistentModelIndex = QModelIndex(),
    ) -> int:
        return 0 if parent.isValid() else len(self.items)

    def columnCount(  # noqa: N802
        self,
        parent: QModelIndex | QPersistentModelIndex = QModelIndex(),
    ) -> int:
        return 0 if parent.isValid() else len(self.headers)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self.items):
            return None
        if role == Qt.ItemDataRole.UserRole:
            return self.items[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return self.mapper(self.items[index.row()])[index.column()]
        return None

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return super().headerData(section, orientation, role)


def setup_table(table: QTableView, model: RowsModel) -> None:
    table.setModel(model)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.horizontalHeader().setStretchLastSection(True)
    table.setAlternatingRowColors(True)


def set_button_role(button: QPushButton, role: str) -> QPushButton:
    """套用 `primaryButton`／`dangerButton` 的 QSS 角色樣式。

    高風險操作（刪除、作廢、重製、還原）一律用 `danger`。
    """
    button.setObjectName(f"{role}Button")
    return button
