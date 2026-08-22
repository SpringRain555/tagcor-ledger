"""帳戶、類別、項目三個維護分頁。

## 為什麼是三個類別而不是一個 `kind: str`

舊版是一個 `CatalogPage(controller, kind)`，`kind` 在 refresh、新增、改名、封存、刪除
五個方法裡各分支一次。**那個分支藏了一個功能缺陷**：`refresh` 只在類別「沒有」子項目
時才把類別自己加成一列，所以「伙食」永遠不會出現，畫面上看到的那個「伙食」是項目那一列
的第一欄 —— 改名、封存、刪除因此對類別全部失效，而且看起來像有作用（它真的改了東西，
只是改到項目）。

現在是一個基底加三個薄子類。基底管**形狀**（按鈕列、表格、選取連動、失敗訊息），
子類只回答四件事：列從哪來、id 叫什麼、五個動作各自呼叫哪個 controller 方法。
沒有任何一個方法需要問「我現在是哪一種」。

## 「刪除未使用」的邊界沒有變

只在完全沒有歷史資料引用時成功；有引用就只能封存。刪掉被引用的設定項會讓舊交易
失去名稱。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.application.result import Result
from tagcor_ledger.domain.models import CategoryTreeFilter
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import (
    account_values,
    category_values,
    item_values,
    result_message,
)
from tagcor_ledger.ui.widgets.filters import CatalogFilterBar
from tagcor_ledger.ui.widgets.simple_form import ChoiceField, TextField, ask_form
from tagcor_ledger.ui.widgets.table import (
    SETTINGS_TABLE_ROWS,
    RowsModel,
    bind_selection,
    set_button_role,
    setup_table,
)


class CatalogPage(QWidget):
    """帳戶／類別／項目共用的形狀。子類只填下面那幾個掛鉤。"""

    changed = Signal()

    HEADERS: tuple[str, ...] = ()
    AMOUNT_COLUMN: int | None = None
    ADD_LABEL = "新增"
    ID_FIELD = ""
    NAME_LABEL = "名稱"
    """重新命名時那一格的標籤。三個分頁各自說自己的話 ——「名稱」對「帳戶」與
    「項目」都成立，所以它等於沒說。"""

    SORT_KEYS: tuple[str | None, ...] = ()
    """欄索引 → SQL 的 `sort_key`。`None` 表示那一欄不能排；空 tuple 表示整頁不能排。

    值必須是 `CATEGORY_SORT_KEYS` 裡有的 key —— 那份白名單才是唯一能拼進
    `ORDER BY` 的東西。"""

    REORDERABLE = False
    """這一頁要不要「上移／下移」。開了就要實作 `_reorder()`。"""

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.sort_key = "default"
        self.descending = False
        self.filter_bar: CatalogFilterBar | None = None
        self.model = RowsModel(
            list(self.HEADERS),
            self._values,
            amount_column=self.AMOUNT_COLUMN,
        )
        self.table = QTableView()
        self._build()
        self.refresh()
        if self.filter_bar is not None:
            # 訊號**最後**才接。`_build()` 與第一次 `refresh()` 都會動篩選列，
            # 在那之前接上只會多跑一次重整。
            self.filter_bar.changed.connect(self.refresh)

    # --- 子類要回答的 -----------------------------------------------------------

    @staticmethod
    def _values(item: dict[str, Any]) -> list[str]:
        raise NotImplementedError

    def _rows(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def _create(self) -> Result | None:
        """回傳 `None` 代表使用者取消，不是失敗。"""
        raise NotImplementedError

    def _rename(self, identifier: str, name: str) -> Result:
        raise NotImplementedError

    def _archive(self, identifier: str) -> Result:
        raise NotImplementedError

    def _restore(self, identifier: str) -> Result:
        raise NotImplementedError

    def _delete(self, identifier: str) -> Result:
        raise NotImplementedError

    def _reorder(self, identifier: str, anchor_id: str, place: str) -> Result:
        raise NotImplementedError

    def _make_filter_bar(self) -> CatalogFilterBar | None:
        """這一頁要不要篩選列。回傳 `None` 就沒有。

        **在這裡建，不在 `__init__` 開頭建** —— `QWidget.__init__` 還沒跑完之前往
        `self` 上掛屬性是 PySide6 明確不保證的事。基底會先呼叫這裡，再呼叫 `refresh()`。
        """
        return None

    # --- 形狀 -------------------------------------------------------------------

    def _build(self) -> None:
        add_button = QPushButton(self.ADD_LABEL)
        rename = QPushButton("重新命名")
        toggle = QPushButton("封存／恢復所選項目")
        delete_button = QPushButton("刪除未使用")
        set_button_role(add_button, "primary")
        set_button_role(delete_button, "danger")

        row = QHBoxLayout()
        for button in (add_button, rename, toggle, delete_button):
            row.addWidget(button)
        if self.REORDERABLE:
            self.move_up = QPushButton("上移")
            self.move_down = QPushButton("下移")
            for button in (self.move_up, self.move_down):
                button.setToolTip(
                    "調整自訂順序。這個順序也會用在記帳頁的下拉選單 —— "
                    "常用的排前面，每天都省一點時間。\n"
                    "點表頭改成依某一欄排序時會停用（那時候看到的不是自訂順序）；"
                    "再點一次表頭就回到自訂順序。"
                )
                row.addWidget(button)
            self.move_up.clicked.connect(lambda: self.move_selected("before"))
            self.move_down.clicked.connect(lambda: self.move_selected("after"))
        row.addStretch()

        setup_table(self.table, self.model, fit_content=True, fit_rows=SETTINGS_TABLE_ROWS)
        # 「新增」不需要選取，其餘三顆都是對所選項目動作 —— 沒選就停用。
        bind_selection(self.table, rename, toggle, delete_button)
        if self.REORDERABLE:
            # **上移／下移不走 `bind_selection`。** 它們的條件比「有沒有選取」多兩個：
            # 現在顯示的是不是自訂順序、以及同一組裡上／下還有沒有鄰居。
            # 交給 `bind_selection` 再自己覆蓋一次，只會變成兩段程式輪流改同一個狀態。
            self.table.selectionModel().selectionChanged.connect(
                lambda *_: self._sync_move_buttons()
            )
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        # **篩選列自己一行**，不擠在按鈕列右邊 —— 四顆按鈕加一條搜尋框會把分頁的
        # 最小寬度撐大，而這一頁的表格本來就只有三欄。
        self.filter_bar = self._make_filter_bar()
        if self.filter_bar is not None:
            layout.addWidget(self.filter_bar)
        layout.addWidget(self.table)
        # 表格現在是固定高度（`fit_rows`），沒有這一行的話 QVBoxLayout 會把多餘的
        # 高度平均塞進每個 widget 之間 —— 按鈕與表格會浮在分頁中間。
        layout.addStretch()

        self._setup_sorting()

        add_button.clicked.connect(self.add_item)
        rename.clicked.connect(self.rename_selected)
        toggle.clicked.connect(self.toggle_selected)
        delete_button.clicked.connect(self.delete_selected)

    def _setup_sorting(self) -> None:
        """點表頭排序。**排序在 SQL 裡做，不是 `setSortingEnabled(True)`。**

        `QTableView.setSortingEnabled(True)` 會叫 model 自己在 Python 裡排 —— 那正是
        `AGENTS.md` 禁止的事。這裡只借用表頭的「可點 ＋ 顯示指示箭頭」，真正的排序
        是把 `sort_key` 送回 SQL 再查一次。
        """
        if not self.SORT_KEYS:
            return
        header = self.table.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        # **三段循環：升冪 → 降冪 → 收回箭頭。** 收回時 `column` 是 -1，那就是
        # 「回到自訂順序」—— 沒有這一段的話，使用者一旦點過表頭就再也回不去，
        # 而自訂順序才是這兩頁的預設。
        header.setSortIndicatorClearable(True)
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        header.sortIndicatorChanged.connect(self._sort_changed)

    def _sort_changed(self, column: int, order: Qt.SortOrder) -> None:
        if column < 0:
            # 箭頭被收回去了 —— 回到自訂順序。
            self.sort_key = "default"
            self.descending = False
            self.refresh()
            return
        key = self.SORT_KEYS[column] if column < len(self.SORT_KEYS) else None
        if key is None:
            # 那一欄不能排。把指示箭頭收回去，不要留一個會動但沒有作用的箭頭。
            self.table.horizontalHeader().setSortIndicator(
                -1, Qt.SortOrder.AscendingOrder
            )
            return
        self.sort_key = key
        self.descending = order == Qt.SortOrder.DescendingOrder
        self.refresh()

    def refresh(self) -> None:
        self.model.replace_rows(self._rows())
        self._sync_move_buttons()

    # --- 自訂順序 ---------------------------------------------------------------

    def _sync_move_buttons(self) -> None:
        """上移／下移能不能按。

        三個條件都要成立：有選取、現在顯示的**是自訂順序**、同一組裡那個方向還有鄰居。

        第二個條件是關鍵：依「項目數」排序時，「上移」要移到哪裡沒有答案 ——
        畫面上那一列的上面那一列不是儲存順序裡的鄰居。讓它可以按，就是讓使用者按下去
        看到一個無法解釋的結果。
        """
        if not self.REORDERABLE:
            return
        self.move_up.setEnabled(self._anchor_for("before") is not None)
        self.move_down.setEnabled(self._anchor_for("after") is not None)

    def _anchor_for(self, place: str) -> str | None:
        """往上／往下找同一組裡的第一個鄰居，回傳它的 id。找不到就 `None`。

        **找的是畫面上看得到的鄰居**，不是資料庫裡的。這一頁可以搜尋與篩選，
        兩者不一定是同一個 —— 送畫面上那個，移動的結果才會跟眼睛看到的一致。
        """
        if self.sort_key != "default":
            return None
        item = self.model.selected_item(self.table)
        if item is None:
            return None
        rows = self.model.items
        identifier = str(item[self.ID_FIELD])
        index = next(
            (i for i, row in enumerate(rows) if str(row[self.ID_FIELD]) == identifier),
            None,
        )
        if index is None:
            return None
        step = -1 if place == "before" else 1
        position = index + step
        while 0 <= position < len(rows):
            if rows[position].get("parent_id") == item.get("parent_id"):
                return str(rows[position][self.ID_FIELD])
            position += step
        return None

    def move_selected(self, place: str) -> None:
        """把所選那一列往上（`before`）或往下（`after`）移一格。

        移完之後**要把它重新選起來** —— 否則按一次「上移」就掉了選取，想連按三次
        得中間重新點三次。使用者要的是「一直往上」，不是「往上一格」。

        **重新選取一定要排在 `_finish()` 之後。** `_finish()` 會發 `changed`，
        而 `main_window._catalog_changed()` 接到之後又會把這一頁重整一次 ——
        先選再發訊號的話，選取會被那一次重整洗掉（實測過，測試當場紅）。
        """
        item = self.model.selected_item(self.table)
        anchor_id = self._anchor_for(place)
        if item is None or anchor_id is None:
            return
        identifier = str(item[self.ID_FIELD])
        result = self._reorder(identifier, anchor_id, place)
        self._finish(result)
        if result.success:
            self._select_by_id(identifier)

    def _select_by_id(self, identifier: str) -> None:
        for row, item in enumerate(self.model.items):
            if str(item[self.ID_FIELD]) == identifier:
                self.table.selectRow(row)
                return

    def selected_id(self) -> str | None:
        item = self.model.selected_item(self.table)
        return str(item[self.ID_FIELD]) if item is not None else None

    def add_item(self) -> None:
        result = self._create()
        if result is not None:
            self._finish(result)

    def rename_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None or item["status"] != "active":
            return
        values = ask_form(
            self,
            "重新命名",
            [TextField("name", self.NAME_LABEL, default=str(item["name"]))],
        )
        if values is not None:
            self._finish(self._rename(str(item[self.ID_FIELD]), str(values["name"])))

    def toggle_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None:
            return
        identifier = str(item[self.ID_FIELD])
        active = item["status"] == "active"
        self._finish(self._archive(identifier) if active else self._restore(identifier))

    def delete_selected(self) -> None:
        identifier = self.selected_id()
        if identifier is None:
            return
        answer = QMessageBox.question(
            self,
            "確認刪除",
            "只會刪除完全未使用的設定項；已有歷史資料者請改用封存。是否繼續？",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._finish(self._delete(identifier))

    def _finish(self, result: Result) -> None:
        if not result.success:
            QMessageBox.warning(self, "操作失敗", result_message(result))
            return
        self.refresh()
        self.changed.emit()


class AccountsPage(CatalogPage):
    HEADERS = ("帳戶", "目前餘額（TWD）", "狀態")
    AMOUNT_COLUMN = 1
    ADD_LABEL = "新增帳戶"
    ID_FIELD = "account_id"
    NAME_LABEL = "帳戶名稱"

    _values = staticmethod(account_values)

    def _rows(self) -> list[dict[str, Any]]:
        return self.controller.account_options(include_archived=True)

    def _create(self) -> Result | None:
        values = ask_form(
            self,
            "新增帳戶",
            [
                TextField("name", "帳戶名稱", placeholder="例如：郵局、現金"),
                TextField(
                    "balance",
                    "期初餘額（TWD）",
                    default="0",
                    placeholder="整數，例如 0 或 100000",
                ),
            ],
        )
        if values is None:
            return None
        return self.controller.create_account(str(values["name"]), str(values["balance"]))

    def _rename(self, identifier: str, name: str) -> Result:
        return self.controller.rename_account(identifier, name)

    def _archive(self, identifier: str) -> Result:
        return self.controller.archive_account(identifier)

    def _restore(self, identifier: str) -> Result:
        return self.controller.restore_account(identifier)

    def _delete(self, identifier: str) -> Result:
        return self.controller.delete_account(identifier)


class CategoryPageBase(CatalogPage):
    """類別與項目共用的四個動作 —— 它們是同一張表的兩層。"""

    ID_FIELD = "category_id"
    LEVEL = 1
    WITH_PARENT_FILTER = False
    REORDERABLE = True

    def _make_filter_bar(self) -> CatalogFilterBar | None:
        return CatalogFilterBar(with_parent=self.WITH_PARENT_FILTER)

    def _rows(self) -> list[dict[str, Any]]:
        """**整個條件送進 SQL**，不撈回來再用 Python 濾。

        以前 `level` 是在這裡用 list comprehension 濾掉的，「項目」分頁的類別篩選
        也是 —— 兩者都是 `AGENTS.md` 那條「篩選、排序一律在 SQL 裡做」的例外。
        """
        bar = self.filter_bar
        return self.controller.category_tree(
            tree_filter=CategoryTreeFilter(
                level=self.LEVEL,
                parent_id=bar.parent_id() if bar is not None else None,
                search=bar.search_text() if bar is not None else "",
                status=bar.status_value() if bar is not None else "all",
                sort_key=self.sort_key,
                descending=self.descending,
            )
        )

    def _rename(self, identifier: str, name: str) -> Result:
        return self.controller.rename_category(identifier, name)

    def _archive(self, identifier: str) -> Result:
        return self.controller.archive_category(identifier)

    def _restore(self, identifier: str) -> Result:
        return self.controller.restore_category(identifier)

    def _delete(self, identifier: str) -> Result:
        return self.controller.delete_category(identifier)

    def _reorder(self, identifier: str, anchor_id: str, place: str) -> Result:
        return self.controller.reorder_category(
            identifier, anchor_id=anchor_id, place=place
        )


class CategoriesPage(CategoryPageBase):
    """類別（第一層）。**每一個類別都有自己的一列，不管它有沒有子項目。**"""

    HEADERS = ("類別", "項目數", "狀態")
    ADD_LABEL = "新增類別"
    NAME_LABEL = "類別名稱"
    LEVEL = 1
    SORT_KEYS = ("name", "item_count", "status")

    _values = staticmethod(category_values)

    def _create(self) -> Result | None:
        values = ask_form(
            self,
            "新增類別",
            [TextField("name", "類別名稱", placeholder="例如：伙食、交通")],
        )
        if values is None:
            return None
        return self.controller.create_category(str(values["name"]))


class ItemsPage(CategoryPageBase):
    """項目（第二層）。上方有搜尋、所屬類別與狀態 —— 項目一多就找不到自己要的那一個。"""

    HEADERS = ("所屬類別", "項目", "狀態")
    ADD_LABEL = "新增項目"
    NAME_LABEL = "項目名稱"
    LEVEL = 2
    WITH_PARENT_FILTER = True
    SORT_KEYS = ("parent_name", "name", "status")

    _values = staticmethod(item_values)

    @property
    def parent_filter(self) -> QComboBox:
        """「所屬類別」那個下拉。篩選列自己持有它，這裡只是給頁面與測試一個入口。"""
        assert self.filter_bar is not None and self.filter_bar.parent_filter is not None
        return self.filter_bar.parent_filter

    def refresh(self) -> None:
        """先重填「所屬類別」下拉，再列資料。

        下拉的內容是**所有第一層類別**，跟目前的篩選無關 —— 用搜尋縮小清單之後，
        下拉裡不該跟著只剩搜尋到的那幾個，否則就換不回去了。
        """
        if self.filter_bar is not None:
            self.filter_bar.set_parents(
                self.controller.category_tree(
                    tree_filter=CategoryTreeFilter(level=1, sort_key="name")
                )
            )
        super().refresh()

    def _create(self) -> Result | None:
        """一張表單問完「所屬類別」與「項目名稱」，按一次確定。

        **類別用下拉的 `userData` 帶 id，不用名稱反查。** 舊版是
        `labels.index(selected)` —— 拿顯示文字回頭找位置，名稱一重複就會挑錯。
        """
        parents = self.controller.category_options()
        if not parents:
            QMessageBox.information(self, "沒有類別", "請先在「類別」分頁建立一個類別。")
            return None
        values = ask_form(
            self,
            "新增項目",
            [
                ChoiceField(
                    "parent_id",
                    "所屬類別",
                    [(str(item["name"]), str(item["category_id"])) for item in parents],
                ),
                TextField("name", "項目名稱", placeholder="例如：早餐、捷運"),
            ],
        )
        if values is None:
            return None
        return self.controller.create_category(
            str(values["name"]), str(values["parent_id"])
        )
