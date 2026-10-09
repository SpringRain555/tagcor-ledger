"""操作設定的「類別與項目」分頁：左邊類別、右邊它底下的項目，上面一排共用按鈕。

## 為什麼合成一頁（2026-10-05）

使用者：「兩者性質相似，而且空間足夠同時顯示兩者。」以前是兩個分頁，要看某個類別底下
有哪些項目，得切到「項目」分頁再去下拉選類別。

## 為什麼仍然是兩張表

v0.14.0 把它們拆開的理由沒有變：類別是十來個、很少動；項目是幾十個、每個月都在加。
**一張平的表兩邊都做不好** —— 舊版就是那樣漏掉「有子項目的類別沒有自己的列」，類別因此
改不了名（見 `catalog.py` 的模組說明）。所以這一頁不是把兩張表併成一張，是讓它們**並排**。

## 同名的按鈕只有一份（2026-10-09）

使用者：「兩邊都有的同名按鈕（重新命名、排序設定）可以合併嗎？」以前兩個窗格各有一排
「重新命名、封存／恢復、刪除未使用、排序設定」，按之前得先想「我選的是左邊還是右邊」。
現在那四顆收成**兩張表上方的一排**，對目前選取的那一列動作，不管它在左邊還是右邊。
只有一邊有的留在自己的表上方：「新增類別」在左，「新增項目」與「更改所屬類別」在右。

這要求**一次只能選一列**：點了右邊的項目，左邊的選取就清掉，反過來也一樣 —— 否則
「重新命名」不知道要改誰。（2026-10-05 的版本左右可以同時選，那時兩邊各有自己的按鈕，
所以沒有歧義。）

## 選取與篩選是兩件事

**點左邊一個類別，右邊只列它底下的項目** —— 使用者明說這個設計要留著。從這一版起
「選取」（按鈕要動誰）與「篩選」（右邊列誰）分開：

- 選了左邊的類別 → 右邊的「所屬類別」切到它。
- 接著點右邊的項目 → 左邊的**選取**清掉（一次只選一列），右邊的**篩選**不動 —— 正在看的
  就是那個類別底下的項目，表格第一欄與「所屬類別」下拉都寫著是哪一個。
- **再點一次已選的那一列 → 取消選取**（Qt 的單選模式原本只有 Ctrl＋點才取消）。
  取消的是左邊的類別時，右邊回到「全部」：點一下篩、再點一下不篩（使用者選定）。
- 右邊的「所屬類別」下拉仍然可以自己選；它不會反過來改左邊的選取。

## 排序設定只有一個視窗

左邊兩組排序方式（類別表、項目表），右邊兩欄拖曳（類別順序、所選類別底下的項目）。
以前項目那一邊的視窗本來就含類別順序，所以合併只多了「類別表的排序方式」那一組。

## 版面

分頁容器的最小寬度是所有分頁裡最大的那一個（`QStackedWidget` 的規則），而「定存」分頁
本來就要約 790 px，所以兩張表並排永遠放得下。共用那一排只有四顆按鈕，每個窗格自己的那一排
只有一兩顆 —— 2026-10-05 為了塞下各五六顆而分成兩排的做法，到這裡就不需要了。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.domain.models import CategoryTreeFilter
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import result_message
from tagcor_ledger.ui.pages.catalog import (
    CategoriesPage,
    ItemsPage,
    is_active,
    order_button,
    selection_action_buttons,
)
from tagcor_ledger.ui.widgets.forms import select_data
from tagcor_ledger.ui.widgets.reorder_dialog import ReorderEntry, SortSection, ask_order
from tagcor_ledger.ui.widgets.table import allow_click_to_deselect, bind_any_selection


def _entry(row: dict[str, Any], children: tuple[ReorderEntry, ...] = ()) -> ReorderEntry:
    return ReorderEntry(
        identifier=str(row["category_id"]),
        name=str(row["name"]),
        archived=row["status"] != "active",
        children=children,
    )


class CategoryItemsTab(QWidget):
    changed = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.categories = CategoriesPage(controller, shared_actions=True)
        self.items = ItemsPage(controller, shared_actions=True)
        self.rename_button, self.toggle_button, self.delete_button = selection_action_buttons()
        self.order_button = order_button()
        self._build()

    def _build(self) -> None:
        actions = QHBoxLayout()
        # 跟窗格裡那一排（新增類別…）同一個內距：左緣對齊、上面不貼著分頁標籤 ——
        # 這一頁自己的版面是零內距，兩個窗格的內距由各自的頁面給。
        inner = self.categories.layout()
        if inner is not None:
            margins = inner.contentsMargins()
            actions.setContentsMargins(margins.left(), margins.top(), 0, 0)
        for button in (self.rename_button, self.toggle_button, self.delete_button):
            actions.addWidget(button)
        actions.addSpacing(16)
        actions.addWidget(self.order_button)
        actions.addStretch()

        panes = QHBoxLayout()
        panes.setSpacing(24)
        for title, page in (("類別", self.categories), ("項目", self.items)):
            pane = QWidget()
            column = QVBoxLayout(pane)
            column.setContentsMargins(0, 0, 0, 0)
            label = QLabel(title)
            label.setObjectName("sectionTitle")
            column.addWidget(label)
            column.addWidget(page)
            panes.addWidget(pane)
        # 兩張表都收寬（`fit_content`），多出來的寬度留在右邊，不要把兩欄拉開。
        panes.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(actions)
        layout.addLayout(panes)

        tables = (self.categories.table, self.items.table)
        bind_any_selection(tables, self.rename_button, enabled_when=is_active)
        bind_any_selection(tables, self.toggle_button, self.delete_button)
        for table in tables:
            allow_click_to_deselect(table)

        self.rename_button.clicked.connect(self.rename_selected)
        self.toggle_button.clicked.connect(self.toggle_selected)
        self.delete_button.clicked.connect(self.delete_selected)
        self.order_button.clicked.connect(self.edit_order)
        self.categories.changed.connect(self.changed.emit)
        self.items.changed.connect(self.changed.emit)
        self.categories.table.selectionModel().selectionChanged.connect(
            lambda *_: self._category_selection_changed()
        )
        self.items.table.selectionModel().selectionChanged.connect(
            lambda *_: self._item_selection_changed()
        )

    def refresh(self) -> None:
        self.categories.refresh()
        self.items.refresh()

    # --- 共用按鈕：動的是有選取的那一邊 ---------------------------------------------

    def selected_page(self) -> CategoriesPage | ItemsPage | None:
        """目前選取在哪一邊。兩張表互斥，所以最多只有一邊。"""
        for page in (self.categories, self.items):
            if page.table.selectionModel().hasSelection():
                return page
        return None

    def rename_selected(self) -> None:
        page = self.selected_page()
        if page is not None:
            page.rename_selected()

    def toggle_selected(self) -> None:
        page = self.selected_page()
        if page is not None:
            page.toggle_selected()

    def delete_selected(self) -> None:
        page = self.selected_page()
        if page is not None:
            page.delete_selected()

    # --- 選取與篩選 -------------------------------------------------------------------

    def _category_selection_changed(self) -> None:
        """選了類別 → 右邊列它底下的項目；**使用者自己取消**左邊的類別 → 右邊回到全部。

        左邊的選取變空有兩種來由，要分得開：點了右邊的項目（右邊這時有選取，篩選不動 ——
        正在看的就是這個類別的項目），或使用者再點一次已選的類別（右邊沒有選取，回到全部）。
        資料重整造成的清空不會走到這裡：model reset 不發 `selectionChanged`。
        """
        item = self.categories.model.selected_item(self.categories.table)
        if item is not None:
            self.items.table.clearSelection()
            select_data(self.items.parent_filter, str(item["category_id"]))
        elif not self.items.table.selectionModel().hasSelection():
            select_data(self.items.parent_filter, None)

    def _item_selection_changed(self) -> None:
        """選了項目 → 左邊的選取清掉（一次只選一列），右邊的篩選不動。"""
        if self.items.table.selectionModel().hasSelection():
            self.categories.table.clearSelection()

    # --- 排序 --------------------------------------------------------------------------

    def edit_order(self) -> None:
        """一個視窗：兩張表各自的排序方式 ＋ 兩層的自訂順序。

        **視窗裡的清單不受兩張表的搜尋與篩選影響** —— 它排的是儲存順序，而儲存順序是
        整組的，只排看得見的那幾筆，剩下的位置就無法定義。

        項目的自訂順序是「每個類別各自一組」（`sort_order` 只在同一組之內有意義），所以
        拖曳是兩欄：左邊排類別、右邊排所選類別底下的項目。**左邊那份類別順序也會一起存** ——
        它就是決定「哪一組排在前面」的東西。
        """
        rows = self.controller.category_tree(tree_filter=CategoryTreeFilter(status="all"))
        children: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            if int(row["level"]) == 2:
                children.setdefault(str(row["parent_id"]), []).append(row)
        entries = [
            _entry(row, tuple(_entry(child) for child in children.get(str(row["category_id"]), [])))
            for row in rows
            if int(row["level"]) == 1
        ]
        dialog = ask_order(
            self,
            "類別與項目排序",
            entries,
            caption="類別順序",
            child_caption="底下的項目",
            sort_sections=(
                SortSection(
                    "左邊「類別」的排序方式", CategoriesPage.SORT_FIELDS, self.categories.sort
                ),
                SortSection("右邊「項目」的排序方式", ItemsPage.SORT_FIELDS, self.items.sort),
            ),
        )
        if dialog is None:
            return
        category_spec, item_spec = dialog.sort_specs()
        result = self.categories.save_sort(category_spec)
        if result.success:
            result = self.items.save_sort(item_spec)
        if result.success:
            result = self.controller.set_category_order(
                dialog.parent_order(), parent_id=None, level=1
            )
        for parent_id, ordered in dialog.child_orders().items():
            if not result.success:
                break
            result = self.controller.set_category_order(ordered, parent_id=parent_id, level=2)
        # 走到一半失敗時，前面那幾步已經存進去了 —— 照樣重整，畫面才跟資料一致。
        self.refresh()
        self.changed.emit()
        if not result.success:
            QMessageBox.warning(self, "操作失敗", result_message(result))
