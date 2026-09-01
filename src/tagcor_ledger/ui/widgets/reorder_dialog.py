"""自訂順序的排序視窗：拖曳排，按確定才寫入。

## 為什麼排序不留在主表格裡

上一版是在主表格放「上移／下移」，代價是**依欄位排序時那兩顆必須停用** ——
畫面上那一列的鄰居不是儲存順序裡的鄰居，「上移」沒有可以解釋的結果。使用者一點
表頭就發現按鈕灰掉了，而原因看不出來。

搬到獨立視窗之後那個衝突就不存在了：**這個視窗永遠顯示自訂順序**，主表格愛怎麼
排就怎麼排，兩者不再互相解釋。

## 為什麼這裡可以拖曳，主表格不行

主表格是 `QTableView` ＋ 唯讀 model ＋ **在 SQL 裡排序**（`AGENTS.md` 的硬規則）。
要在那上面拖，得換成可寫入的 model，等於為了一個功能開一個例外。

這裡的清單是 `QListWidget` ＋ `InternalMove` —— 它本來就是可寫入的 model，拖曳是
內建行為。清單順序就是答案，按確定時一次送出整份 id。

## 三個刻意的選擇

- **按「確定」才寫入。** 拖到一半按取消要真的什麼都沒發生。
- **封存的也列出來，標「已封存」。** 藏起來的話它們的順序值會停在舊的，日後恢復
  就出現在一個莫名其妙的位置。
- **同時提供上移／下移按鈕。** 只有拖曳的話，鍵盤操作與手不穩的人就沒有路可走。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.domain.models import SortLevel
from tagcor_ledger.ui.widgets.sort_editor import SortEditor
from tagcor_ledger.ui.widgets.table import set_button_role


VISIBLE_ROWS = 10
"""清單至少要放得下幾列才開始捲。

2026-08-22 第一版沒設下限，實機截圖上五個項目就被切掉第五列 —— 一個要靠拖曳的
清單，**看不到全部就沒辦法決定要拖到哪裡**。10 列在 760 px 高的畫面裡放得下，
也涵蓋多數類別底下的項目數。

高度照字型現算，不寫死列高（跟 `forms.py` 的日曆同一個理由：QSS 改了列高之後
寫死的數字就是錯的）。
"""

MIN_LIST_WIDTH = 200
"""名字不要被截掉。「電子票證儲值」這種六個字的項目在預設寬度下會變成「電子票證…」。"""

LIST_ROW_PADDING = 14
"""每一列在文字高度之外的內距（px），跟 QSS 給清單項目的內距對齊。"""


@dataclass(frozen=True, slots=True)
class ReorderEntry:
    """拖曳清單裡的一列。`children` 只有「類別」那一組會用到。"""

    identifier: str
    name: str
    archived: bool = False
    children: tuple["ReorderEntry", ...] = field(default_factory=tuple)


def entry_label(entry: ReorderEntry) -> str:
    return f"{entry.name}（已封存）" if entry.archived else entry.name


class OrderList(QWidget):
    """一份可拖曳的順序清單，外加上移／下移。"""

    def __init__(self, caption: str, entries: list[ReorderEntry]) -> None:
        super().__init__()
        self.caption = QLabel(caption)
        self.list = QListWidget()
        self.list.setObjectName("reorderList")
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        row_height = self.list.fontMetrics().height() + LIST_ROW_PADDING
        self.list.setMinimumHeight(VISIBLE_ROWS * row_height)
        self.list.setMinimumWidth(MIN_LIST_WIDTH)
        self.up = QPushButton("上移")
        self.down = QPushButton("下移")
        self._build()
        self.set_entries(entries)

    def _build(self) -> None:
        buttons = QHBoxLayout()
        buttons.addWidget(self.up)
        buttons.addWidget(self.down)
        buttons.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.caption)
        layout.addWidget(self.list)
        layout.addLayout(buttons)
        self.up.clicked.connect(lambda: self._nudge(-1))
        self.down.clicked.connect(lambda: self._nudge(1))
        self.list.currentRowChanged.connect(lambda *_: self._sync())

    def set_entries(self, entries: list[ReorderEntry]) -> None:
        self.list.clear()
        for entry in entries:
            item = QListWidgetItem(entry_label(entry))
            item.setData(Qt.ItemDataRole.UserRole, entry.identifier)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        self._sync()

    def _nudge(self, step: int) -> None:
        row = self.list.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(target, item)
        # `takeItem` 會把選取一起拿走。不重新選起來的話，連按兩次「上移」得
        # 中間再點一次 —— 使用者要的是「一直往上」。
        self.list.setCurrentRow(target)

    def _sync(self) -> None:
        row = self.list.currentRow()
        self.up.setEnabled(row > 0)
        self.down.setEnabled(0 <= row < self.list.count() - 1)

    def ordered_ids(self) -> list[str]:
        return [
            str(self.list.item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(self.list.count())
        ]

    def current_id(self) -> str | None:
        item = self.list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None


class ReorderDialog(QDialog):
    """一組（或兩層）自訂順序。

    `groups` 有子項目時（`children` 不為空）會長出第二個清單：左邊選上層、
    右邊排它底下的那一組。**這對應「第一層類別自訂、第二層項目自訂」** ——
    項目的順序本來就是「每個類別各自一組」，一份平的清單表達不了它。
    """

    def __init__(
        self,
        title: str,
        entries: list[ReorderEntry],
        *,
        parent: QWidget | None = None,
        caption: str = "拖曳調整順序",
        child_caption: str = "",
        sort_fields: Sequence[tuple[str, str]] = (),
        sort_spec: Sequence[SortLevel] = (),
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._entries = entries
        self._child_caption = child_caption
        self.parents = OrderList(caption, entries)
        # **不要叫 `self.children`。** `QObject.children()` 是 Qt 自己的方法，
        # 指派同名的實例屬性會把它蓋掉 —— 之後任何呼叫 `dialog.children()` 的地方
        # （Qt 的 Python 側輔助函式、除錯工具）拿到的是一個不可呼叫的 OrderList。
        # 本機的 mypy 抓不到這種遮蔽（conda 的 PySide6 沒有 `py.typed`，Qt 全是
        # `Any`），是 CI 上帶 stub 的版本報出來的。
        self.child_list: OrderList | None = None
        self._child_orders: dict[str, list[str]] = {}
        self._current_parent: str | None = None
        if any(entry.children for entry in entries):
            self.child_list = OrderList(child_caption or "底下的項目", [])
        # **排序方式與自訂順序並排在同一個視窗裡。** 它們是同一件事的兩半：
        # 左邊決定「照什麼排」，右邊決定「自訂那一層長什麼樣」。分成兩個入口的話，
        # 使用者得先猜哪一個才是他要的。
        self.sort_editor = SortEditor(sort_fields) if sort_fields else None
        self._build()
        if self.sort_editor is not None:
            self.sort_editor.set_spec(sort_spec)

    def _build(self) -> None:
        lists = QHBoxLayout()
        if self.sort_editor is not None:
            side = QVBoxLayout()
            side.addWidget(self.sort_editor)
            side.addStretch()
            lists.addLayout(side)
        lists.addWidget(self.parents)
        if self.child_list is not None:
            lists.addWidget(self.child_list)

        self.hint = QLabel()
        self.hint.setObjectName("hintLabel")
        self.hint.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("確定")
        set_button_role(ok, "primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(lists)
        layout.addWidget(self.hint)
        layout.addWidget(buttons)

        if self.sort_editor is not None:
            self.sort_editor.changed.connect(self._sync_hint)
        self._sync_hint()

        if self.child_list is not None:
            self.parents.list.currentRowChanged.connect(lambda *_: self._show_children())
            self._show_children()

    def _sync_hint(self) -> None:
        """排序方式沒用到自訂順序時要**明講拖曳不會反映在清單上**。

        不講的話，使用者拖了半天按確定、清單卻沒變 —— 看起來像功能壞掉，
        實際上是他選了「照名稱排」。順序**有**存下去，只是沒有拿來用。
        """
        base = "拖曳或用上移／下移調整自訂順序，按「確定」才會存下來。"
        if self.sort_editor is not None and not self.sort_editor.uses_custom():
            self.hint.setText(
                base + "\n"
                "目前的排序方式沒有用到「自訂順序」，所以拖曳的結果不會顯示在清單上"
                "（順序仍然會存起來）。要看到效果，請把某一層改成自訂順序。"
            )
            return
        self.hint.setText(base + "這份順序也會用在記帳頁的下拉選單。")

    def sort_spec(self) -> tuple[SortLevel, ...]:
        return self.sort_editor.spec() if self.sort_editor is not None else ()

    def _show_children(self) -> None:
        """換到另一個上層時，先把目前這一組的順序記下來再換。

        不記的話，切走再切回來就會看到拖曳前的順序 —— 使用者會以為剛才白拖了。
        """
        if self.child_list is None:
            return
        if self._current_parent is not None:
            self._child_orders[self._current_parent] = self.child_list.ordered_ids()
        parent_id = self.parents.current_id()
        self._current_parent = parent_id
        entry = next(
            (item for item in self._entries if item.identifier == parent_id), None
        )
        if entry is None:
            self.child_list.set_entries([])
            return
        self.child_list.caption.setText(f"「{entry.name}」底下的項目")
        remembered = self._child_orders.get(entry.identifier)
        children = list(entry.children)
        if remembered is not None:
            by_id = {child.identifier: child for child in children}
            children = [by_id[i] for i in remembered if i in by_id]
        self.child_list.set_entries(children)

    def parent_order(self) -> list[str]:
        return self.parents.ordered_ids()

    def child_orders(self) -> dict[str, list[str]]:
        """每個上層底下那一組的順序。**只回傳使用者真的看過的那幾組。**

        沒點開過的組別不送出去 —— 送出去等於用一份沒人確認過的順序去覆寫，
        而且會白白撞上 `REORDER_LIST_STALE` 的檢查。
        """
        if self.child_list is None:
            return {}
        orders = dict(self._child_orders)
        if self._current_parent is not None:
            orders[self._current_parent] = self.child_list.ordered_ids()
        return orders


def ask_order(
    parent: QWidget,
    title: str,
    entries: list[ReorderEntry],
    *,
    caption: str = "拖曳調整順序",
    child_caption: str = "",
    sort_fields: Sequence[tuple[str, str]] = (),
    sort_spec: Sequence[SortLevel] = (),
) -> ReorderDialog | None:
    """開排序視窗。**取消回傳 `None`** —— 那不是失敗，呼叫端不要跳錯誤訊息。"""
    dialog = ReorderDialog(
        title,
        entries,
        parent=parent,
        caption=caption,
        child_caption=child_caption,
        sort_fields=sort_fields,
        sort_spec=sort_spec,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog
