"""操作設定的「類別與項目」分頁：左邊類別、右邊它底下的項目。

## 為什麼合成一頁（2026-10-05）

使用者：「兩者性質相似，而且空間足夠同時顯示兩者。」以前是兩個分頁，要看某個類別底下
有哪些項目，得切到「項目」分頁再去下拉選類別。

## 為什麼仍然是兩張表

v0.14.0 把它們拆開的理由沒有變：類別是十來個、很少動；項目是幾十個、每個月都在加。
**一張平的表兩邊都做不好** —— 舊版就是那樣漏掉「有子項目的類別沒有自己的列」，類別因此
改不了名（見 `catalog.py` 的模組說明）。所以這一頁不是把兩張表併成一張，是讓它們**並排**：

- 左邊是完整的 `CategoriesPage`：每一個類別都有自己的一列，按鈕、篩選、排序都照舊。
- 右邊是完整的 `ItemsPage`。**點左邊一個類別，右邊的「所屬類別」就切到它**，只列它底下的
  項目；右邊的下拉選「全部」看得到全部（單向，右邊不會反過來改左邊的選取）。
- 「新增項目」的所屬類別預設停在目前篩選的那一個。

## 按鈕分兩排，而且不做「窄的時候上下排」

兩個窗格各自一排按鈕放不下（類別約 590 px、項目約 720 px，2026-10-05 量的），所以各分兩排：
上排「新增、重新命名（與更改所屬類別）」、下排「封存／恢復、刪除未使用、排序設定」。
兩欄並排約 700 px。

**分頁容器的最小寬度是所有分頁裡最大的那一個**（`QStackedWidget` 的規則），而「定存」分頁
本來就要約 790 px —— 所以這一頁拿到的寬度永遠放得下兩欄。比那更窄的視窗，整個操作設定
本來就是橫向捲動（它的既有行為）。為一個永遠不會觸發的寬度寫上下排，只是多一段死碼。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.pages.catalog import CategoriesPage, ItemsPage
from tagcor_ledger.ui.widgets.forms import select_data


class CategoryItemsTab(QWidget):
    changed = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.categories = CategoriesPage(controller, button_rows=2)
        self.items = ItemsPage(controller, button_rows=2)
        self._build()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)
        for title, page in (("類別", self.categories), ("項目", self.items)):
            pane = QWidget()
            column = QVBoxLayout(pane)
            column.setContentsMargins(0, 0, 0, 0)
            label = QLabel(title)
            label.setObjectName("sectionTitle")
            column.addWidget(label)
            column.addWidget(page)
            layout.addWidget(pane)
        # 兩張表都收寬（`fit_content`），多出來的寬度留在右邊，不要把兩欄拉開。
        layout.addStretch()

        self.categories.changed.connect(self.changed.emit)
        self.items.changed.connect(self.changed.emit)
        self.categories.table.selectionModel().selectionChanged.connect(
            lambda *_: self._follow_category()
        )

    def refresh(self) -> None:
        self.categories.refresh()
        self.items.refresh()

    def _follow_category(self) -> None:
        """點左邊一個類別，右邊只列它底下的項目。

        **單向**：右邊的「所屬類別」下拉選「全部」看得到全部，但不會反過來改左邊的選取 ——
        左邊的選取同時是「重新命名、封存、刪除」的對象，被右邊改掉會按錯東西。
        """
        item = self.categories.model.selected_item(self.categories.table)
        if item is not None:
            select_data(self.items.parent_filter, str(item["category_id"]))
