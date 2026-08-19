"""所有列表頁共用的表格 model 與外觀設定。

`RowsModel` 存的是 controller 給的原始 dict，顯示字串由 `mapper` 現算。所以
`selected_item()` 拿得到完整的那一列（含 id、revision 這些沒顯示出來的欄位），
頁面不需要為了拿 id 而把 id 塞進某個看不見的欄位。

## 金額欄為什麼要特別處理

帳本裡最常被眼睛掃的就是金額，而預設的表格會把它當成普通字串**靠左**排 ——
`1200`、`85`、`100000` 的個位數不對齊，要比大小得一個一個讀。
所以金額欄一律**右對齊**，並依收入／支出上色（`amount_column` 指定是哪一欄）。
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QPushButton,
    QTableView,
)

from tagcor_ledger.ui import colors


class RowsModel(QAbstractTableModel):
    def __init__(
        self,
        headers: list[str],
        mapper: Callable[[dict[str, Any]], list[str]],
        *,
        amount_column: int | None = None,
    ) -> None:
        super().__init__()
        self.headers = headers
        self.mapper = mapper
        self.amount_column = amount_column
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
        if index.column() != self.amount_column:
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole:
            return QColor(amount_color(self.items[index.row()]))
        return None

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation != Qt.Orientation.Horizontal:
            return super().headerData(section, orientation, role)
        if role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            # 標題要跟資料同一邊。Qt 預設把標題置中，於是每一欄的標題與內容都對不齊。
            if section == self.amount_column:
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return super().headerData(section, orientation, role)


def amount_color(item: dict[str, Any]) -> str:
    """依流向決定金額的顏色。

    - 收入綠、支出紅（使用者 2026-08-19 選定的國際財會方向）
    - **轉帳不上色** —— 錢只是換了地方，不是收支
    - 作廢的整列變暗，因為它已經不算數了
    - 沒有流向的金額（定存本金、帳戶餘額）就是一般文字，不要為了「有顏色」而上色
    """
    if str(item.get("status", "")) == "voided":
        return colors.TEXT_FAINT
    entry_type = str(item.get("entry_type", ""))
    if not entry_type:
        return colors.TEXT
    if entry_type == "income":
        return colors.INCOME
    if entry_type == "expense":
        return colors.EXPENSE
    return colors.AMOUNT_NEUTRAL


def setup_table(
    table: QTableView,
    model: RowsModel,
    *,
    stretch_column: int | None = None,
) -> None:
    """套用共用外觀。

    欄寬一律依內容決定，`stretch_column` 才指定哪一欄吃掉多餘寬度。
    **不用 `setStretchLastSection`** —— 最後一欄通常是「狀態」這種兩個字的欄位，
    讓它獨吞剩下的寬度，而真正需要空間的「備註」反而被擠窄。

    沒有指定 `stretch_column` 時，多餘的寬度就留在右邊 —— 留白比硬撐開某一欄好看，
    也不會讓短短的「使用中」離「帳戶」有半個螢幕遠。
    """
    table.setModel(model)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(34)

    header = table.horizontalHeader()
    header.setHighlightSections(False)
    header.setStretchLastSection(False)
    for column in range(model.columnCount()):
        mode = (
            QHeaderView.ResizeMode.Stretch
            if column == stretch_column
            else QHeaderView.ResizeMode.ResizeToContents
        )
        header.setSectionResizeMode(column, mode)


def bind_selection(table: QTableView, *buttons: QPushButton) -> None:
    """沒有選取任何一列時，把這些按鈕停用。

    原本的寫法是 handler 裡 `if item is None: return` —— 使用者按下去**什麼都不會發生**，
    沒有訊息也沒有變化，看起來就像程式當掉。停用按鈕才說得出「現在不能按」。
    """

    def sync() -> None:
        has_selection = bool(table.selectionModel().selectedRows())
        for button in buttons:
            button.setEnabled(has_selection)

    table.selectionModel().selectionChanged.connect(lambda *_: sync())
    model = table.model()
    if model is not None:
        model.modelReset.connect(sync)
    sync()


def set_button_role(button: QPushButton, role: str) -> QPushButton:
    """套用 `primaryButton`／`dangerButton` 的 QSS 角色樣式。

    高風險操作（刪除、作廢、重製、還原）一律用 `danger`。
    """
    button.setObjectName(f"{role}Button")
    return button
