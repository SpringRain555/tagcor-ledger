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
from shiboken6 import isValid

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


def fit_to_contents(table: QTableView) -> None:
    """把表格的寬度收到欄寬總和。

    三四欄的表拉滿整個視窗時，表頭只畫到最後一欄就結束，右邊留下一大塊有框線卻沒有
    表頭的空白 —— 看起來像壞掉。收到內容寬度就沒有那條接縫。

    **不要讀 `sectionSize`。** `ResizeToContents` 的欄寬是 Qt 在版面階段才算的，
    在 `modelReset` 或 `sectionResized` 當下讀到的都可能是中間值 —— 2026-08-20 兩種
    寫法都試過，結果是把帳戶表夾成 187 px（欄寬其實要 311），「狀態」欄整個看不到
    還冒出橫向捲軸。

    `sizeHintForColumn()` 是**現算**的：它直接問 model 與 delegate，不經過版面階段，
    所以資料一進去就是最終值。表頭文字的寬度另外由 `sectionSizeHint()` 補上 ——
    「目前餘額（TWD）」比它底下的數字寬。
    """
    header = table.horizontalHeader()
    width = sum(
        max(table.sizeHintForColumn(column), header.sectionSizeHint(column))
        for column in range(header.count())
    )
    table.setMaximumWidth(width + 2 * table.frameWidth())


SETTINGS_TABLE_ROWS = 14
"""操作設定裡每張表最多長到幾列，超過就自己捲。

這些表只有三四欄（`fit_content` 已經把寬度收掉），若再讓高度吃滿視窗，三列資料就會
變成一條又窄又高、幾乎全是空框線的長條 —— 2026-08-20 實機截圖上的「類別」分頁就是
那個樣子。14 列在 760 px 高的視窗裡放得下，也足夠讓「有很多項目」看起來像一張表。
"""


def fit_to_rows(table: QTableView, *, limit: int) -> None:
    """把表格的**高度**收到實際列數，最多 `limit` 列。

    跟 `fit_to_contents` 是同一個毛病的另一半：三列資料佔滿一整塊高度時，最後一列
    底下留著一大片有框線卻沒有內容的空白 —— 2026-08-20 資產總覽的實機截圖上就是
    那個樣子，看起來像資料還沒載完。

    `limit` 是為了不讓帳戶一多就把底下的定存與待辦推出畫面；超過就讓表格自己捲。
    """
    model = table.model()
    rows = min(model.rowCount() if model is not None else 0, limit)
    header = table.horizontalHeader().sizeHint().height()
    body = rows * table.verticalHeader().defaultSectionSize()
    table.setFixedHeight(header + body + 2 * table.frameWidth())


def setup_table(
    table: QTableView,
    model: RowsModel,
    *,
    stretch_column: int | None = None,
    fit_content: bool = False,
    fit_rows: int | None = None,
) -> None:
    """套用共用外觀。

    欄寬一律依內容決定，`stretch_column` 才指定哪一欄吃掉多餘寬度。
    **不用 `setStretchLastSection`** —— 最後一欄通常是「狀態」這種兩個字的欄位，
    讓它獨吞剩下的寬度，而真正需要空間的「備註」反而被擠窄。

    `fit_content=True` 讓整張表收到欄寬總和（見 `fit_to_contents`）。
    欄位少的設定用表格用它；欄位多的長表（交易紀錄、待確認）維持滿寬並指定
    `stretch_column`。**兩者不會同時用** —— 收寬之後就沒有多餘寬度可以給誰吃。

    `fit_rows` 另外把**高度**也收到實際列數（見 `fit_to_rows`）。只有摘要用的小表
    需要它；一張表是某一頁的主角時，讓它長滿高度才對。
    """
    if fit_content and stretch_column is not None:
        raise ValueError("fit_content 與 stretch_column 不能同時指定")
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
    # **表頭不可點。** Qt 的預設是可點，而可點的表頭看起來就像可以排序 ——
    # 這個專案裡沒有任何一張表用點表頭排序（v0.19.0 起排序統一走「排序…」視窗）。
    # 留著預設值等於在畫面上放一個按了沒反應的東西。
    header.setSectionsClickable(False)
    header.setSortIndicatorShown(False)
    for column in range(model.columnCount()):
        mode = (
            QHeaderView.ResizeMode.Stretch
            if column == stretch_column
            else QHeaderView.ResizeMode.ResizeToContents
        )
        header.setSectionResizeMode(column, mode)

    if fit_content:
        # 換資料就重量。`fit_to_contents` 是現算的，所以在 `modelReset` 當下就已經
        # 拿得到最終值，不必等版面階段。
        model.modelReset.connect(lambda: fit_to_contents(table))
        fit_to_contents(table)

    if fit_rows is not None:
        rows_limit = fit_rows
        model.modelReset.connect(lambda: fit_to_rows(table, limit=rows_limit))
        fit_to_rows(table, limit=rows_limit)


def bind_selection(table: QAbstractItemView, *buttons: QPushButton) -> None:
    """沒有選取任何一列時，把這些按鈕停用。

    原本的寫法是 handler 裡 `if item is None: return` —— 使用者按下去**什麼都不會發生**，
    沒有訊息也沒有變化，看起來就像程式當掉。停用按鈕才說得出「現在不能按」。

    **收 `QAbstractItemView` 而不是 `QTableView`**，因為維護頁的備份清單是
    `QListWidget`。同一條「沒選取就停用」的規則對它一樣成立，而且那一頁有
    「刪除所選備份」這種不可逆的操作 —— 正是最不該讓人按了沒反應的地方。

    ## 為什麼 `sync` 要先問 view 還在不在

    `QTableView` 用的 `RowsModel` 是**頁面自己持有**的 Python 物件，銷毀順序由
    Python 決定，view 一定先走。`QListWidget` 不一樣：它的 model 是 **C++ 那邊的
    內部子物件**，`~QListWidget` 期間它會再發一次 `modelReset` —— 那時候 C++ 物件
    已經沒了，Python 包裝還在，`table.selectionModel()` 就丟
    `RuntimeError: Internal C++ object already deleted`。

    2026-08-22 使用者實機遇到：操作全程正常，**關掉程式的時候**跳出一個紅色驚嘆號。
    這條路是 v0.16.1 把型別從 `QTableView` 放寬到 `QAbstractItemView` 時才第一次
    被走到（日誌佐證：0.8.0～0.14.3 共 10 次關閉全部乾淨）。

    「一個已經不存在的 widget 選了幾列」本來就沒有意義，所以直接跳過 ——
    這不是把錯誤吞掉，是那個問題在那個時間點不成立。
    """

    def sync() -> None:
        if not isValid(table):
            return
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
