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

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.application.result import Result
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import (
    account_values,
    category_values,
    item_values,
    result_message,
)
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

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.model = RowsModel(
            list(self.HEADERS),
            self._values,
            amount_column=self.AMOUNT_COLUMN,
        )
        self.table = QTableView()
        self._build()
        self.refresh()

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

    def _filter_widgets(self) -> list[QWidget]:
        """按鈕列右側的額外控制項（目前只有「項目」分頁的類別篩選）。"""
        return []

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
        row.addStretch()
        for widget in self._filter_widgets():
            row.addWidget(widget)

        setup_table(self.table, self.model, fit_content=True, fit_rows=SETTINGS_TABLE_ROWS)
        # 「新增」不需要選取，其餘三顆都是對所選項目動作 —— 沒選就停用。
        bind_selection(self.table, rename, toggle, delete_button)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.table)
        # 表格現在是固定高度（`fit_rows`），沒有這一行的話 QVBoxLayout 會把多餘的
        # 高度平均塞進每個 widget 之間 —— 按鈕與表格會浮在分頁中間。
        layout.addStretch()

        add_button.clicked.connect(self.add_item)
        rename.clicked.connect(self.rename_selected)
        toggle.clicked.connect(self.toggle_selected)
        delete_button.clicked.connect(self.delete_selected)

    def refresh(self) -> None:
        self.model.replace_rows(self._rows())

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
        name, accepted = QInputDialog.getText(
            self,
            "重新命名",
            "名稱",
            text=str(item["name"]),
        )
        if accepted:
            self._finish(self._rename(str(item[self.ID_FIELD]), name))

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

    _values = staticmethod(account_values)

    def _rows(self) -> list[dict[str, Any]]:
        return self.controller.account_options(include_archived=True)

    def _create(self) -> Result | None:
        name, accepted = QInputDialog.getText(self, "新增帳戶", "名稱")
        if not accepted:
            return None
        balance, accepted = QInputDialog.getText(
            self, "新增帳戶", "期初餘額（TWD）", text="0"
        )
        return self.controller.create_account(name, balance) if accepted else None

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

    def _tree(self) -> list[dict[str, Any]]:
        return self.controller.category_tree(include_archived=True)

    def _rows(self) -> list[dict[str, Any]]:
        return [item for item in self._tree() if int(item["level"]) == self.LEVEL]

    def _rename(self, identifier: str, name: str) -> Result:
        return self.controller.rename_category(identifier, name)

    def _archive(self, identifier: str) -> Result:
        return self.controller.archive_category(identifier)

    def _restore(self, identifier: str) -> Result:
        return self.controller.restore_category(identifier)

    def _delete(self, identifier: str) -> Result:
        return self.controller.delete_category(identifier)


class CategoriesPage(CategoryPageBase):
    """類別（第一層）。**每一個類別都有自己的一列，不管它有沒有子項目。**"""

    HEADERS = ("類別", "項目數", "狀態")
    ADD_LABEL = "新增類別"
    LEVEL = 1

    _values = staticmethod(category_values)

    def _create(self) -> Result | None:
        name, accepted = QInputDialog.getText(self, "新增類別", "類別名稱")
        return self.controller.create_category(name) if accepted else None


class ItemsPage(CategoryPageBase):
    """項目（第二層）。上方有一個類別篩選 —— 項目一多就找不到自己要的那一個。"""

    HEADERS = ("所屬類別", "項目", "狀態")
    ADD_LABEL = "新增項目"
    LEVEL = 2

    _values = staticmethod(item_values)

    def __init__(self, controller: LedgerController) -> None:
        super().__init__(controller)
        # 訊號**最後**才接。`_build()` 與第一次 `refresh()` 都會動這個下拉，
        # 在那之前接上只會多跑一次重整。
        self.parent_filter.currentIndexChanged.connect(self.refresh)

    def _filter_widgets(self) -> list[QWidget]:
        """在這裡建下拉，不在 `__init__` 開頭 —— `QWidget.__init__` 還沒跑完之前
        往 `self` 上掛屬性是 PySide6 明確不保證的事。基底會先呼叫這裡，再呼叫
        `refresh()`，所以順序是安全的。
        """
        self.parent_filter = QComboBox()
        return [QLabel("類別"), self.parent_filter]

    def refresh(self) -> None:
        """重填篩選再列資料。**兩者用同一份 `category_tree()`**，不要各查一次。"""
        tree = self._tree()
        self._reload_filter([item for item in tree if int(item["level"]) == 1])
        selected = self.parent_filter.currentData()
        self.model.replace_rows(
            [
                item
                for item in tree
                if int(item["level"]) == 2
                and (selected is None or str(item["parent_id"]) == str(selected))
            ]
        )

    def _reload_filter(self, parents: list[dict[str, Any]]) -> None:
        """保住目前的選擇。重填下拉會發 `currentIndexChanged`，所以先擋住訊號。"""
        previous = self.parent_filter.currentData()
        self.parent_filter.blockSignals(True)
        self.parent_filter.clear()
        self.parent_filter.addItem("全部", None)
        for item in parents:
            self.parent_filter.addItem(str(item["name"]), str(item["category_id"]))
        index = self.parent_filter.findData(previous)
        self.parent_filter.setCurrentIndex(max(index, 0))
        self.parent_filter.blockSignals(False)

    def _create(self) -> Result | None:
        parents = self.controller.category_options()
        if not parents:
            QMessageBox.information(self, "沒有類別", "請先在「類別」分頁建立一個類別。")
            return None
        labels = [str(item["name"]) for item in parents]
        selected, accepted = QInputDialog.getItem(
            self, "新增項目", "上層類別", labels, editable=False
        )
        if not accepted:
            return None
        name, accepted = QInputDialog.getText(self, "新增項目", "項目名稱")
        if not accepted:
            return None
        parent_id = str(parents[labels.index(selected)]["category_id"])
        return self.controller.create_category(name, parent_id)
