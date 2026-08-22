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
from tagcor_ledger.ui.widgets.reorder_dialog import ReorderEntry, ask_order
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
            # **排序是獨立視窗，不是表格上的兩顆按鈕。** 上一版把「上移／下移」放在
            # 這裡，代價是依欄位排序時必須停用它們 —— 畫面上那一列的鄰居不是儲存
            # 順序裡的鄰居。搬進視窗之後衝突就不存在了：那個視窗永遠顯示自訂順序。
            self.order_button = QPushButton("排序…")
            self.order_button.setToolTip(
                "開一個視窗，用拖曳排出自己想要的順序。\n"
                "這份順序也會用在記帳頁的下拉選單 —— 常用的排前面。"
            )
            self.order_button.clicked.connect(self.edit_order)
            row.addWidget(self.order_button)
        row.addStretch()

        setup_table(self.table, self.model, fit_content=True, fit_rows=SETTINGS_TABLE_ROWS)
        # 「新增」與「排序…」不需要選取，其餘三顆都是對所選項目動作 —— 沒選就停用。
        bind_selection(self.table, rename, toggle, delete_button)
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

    # --- 自訂順序 ---------------------------------------------------------------

    def edit_order(self) -> None:
        """開排序視窗。子類用 `_order_entries()` 與 `_save_order()` 回答內容與寫法。

        **視窗裡的清單不受這一頁的搜尋與篩選影響。** 它排的是儲存順序，而儲存順序
        是整組的 —— 只排看得見的那幾筆，剩下的位置就無法定義。
        """
        raise NotImplementedError

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
    REORDERABLE = True

    _values = staticmethod(account_values)

    def edit_order(self) -> None:
        """帳戶只有一組，所以只有一份清單。

        這份順序同時決定**記帳頁的帳戶下拉與資產總覽**的列法 —— 那正是排它的理由，
        每天要選的那個帳戶不該埋在第五個。
        """
        rows = self.controller.account_options(include_archived=True)
        dialog = ask_order(
            self,
            "帳戶順序",
            [
                ReorderEntry(
                    identifier=str(row["account_id"]),
                    name=str(row["name"]),
                    archived=row["status"] != "active",
                )
                for row in rows
            ],
            caption="拖曳調整帳戶順序",
        )
        if dialog is not None:
            self._finish(self.controller.set_account_order(dialog.parent_order()))

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

    def _all_categories(self) -> list[dict[str, Any]]:
        """整棵樹，**不套這一頁的篩選** —— 排序視窗排的是儲存順序，那是整組的。"""
        return self.controller.category_tree(
            tree_filter=CategoryTreeFilter(status="all")
        )

    @staticmethod
    def _entry(row: dict[str, Any], children: tuple[ReorderEntry, ...] = ()) -> ReorderEntry:
        return ReorderEntry(
            identifier=str(row["category_id"]),
            name=str(row["name"]),
            archived=row["status"] != "active",
            children=children,
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

    def edit_order(self) -> None:
        """第一層全部是一組（`parent_id` 都是 `None`），所以只有一份清單。"""
        rows = [row for row in self._all_categories() if int(row["level"]) == 1]
        dialog = ask_order(
            self,
            "類別順序",
            [self._entry(row) for row in rows],
            caption="拖曳調整類別順序",
        )
        if dialog is not None:
            self._finish(
                self.controller.set_category_order(
                    dialog.parent_order(), parent_id=None, level=1
                )
            )


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

    def edit_order(self) -> None:
        """兩層：左邊排類別，右邊排**所選類別底下**的項目。

        項目的順序是「每個類別各自一組」（`sort_order` 只在同一組之內有意義），
        一份平的清單表達不了它 —— 所以這個視窗一定是兩欄。

        **左邊那份類別順序也會一起存。** 它就是決定「哪一組排在前面」的東西，
        跟「這一組裡面誰在前面」是同一件事的兩層。
        """
        rows = self._all_categories()
        children: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            if int(row["level"]) == 2:
                children.setdefault(str(row["parent_id"]), []).append(row)
        entries = [
            self._entry(
                row,
                tuple(self._entry(child) for child in children.get(str(row["category_id"]), [])),
            )
            for row in rows
            if int(row["level"]) == 1
        ]
        dialog = ask_order(
            self,
            "項目順序",
            entries,
            caption="類別順序",
            child_caption="底下的項目",
        )
        if dialog is None:
            return
        result = self.controller.set_category_order(
            dialog.parent_order(), parent_id=None, level=1
        )
        for parent_id, ordered in dialog.child_orders().items():
            if not result.success:
                break
            result = self.controller.set_category_order(
                ordered, parent_id=parent_id, level=2
            )
        self._finish(result)
