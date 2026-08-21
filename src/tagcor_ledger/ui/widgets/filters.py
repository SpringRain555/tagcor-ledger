"""名冊分頁共用的篩選列。

## 為什麼要有這個東西

專案裡本來有**三份互不一致的手刻篩選列**：交易紀錄兩行九個元件、法規參考一行三個、
「項目」分頁只有一個沒有標籤的下拉。三者的行為也不一樣 —— 交易紀錄要按「套用篩選」，
另外兩個是改了就生效。

這一份給「操作設定」底下的名冊分頁用：**改了就生效**，因為那些表都不大，不需要
先按一顆按鈕。交易紀錄不改用這個，它有日期區間與 keyset 分頁，形狀本來就不同。

## 狀態預設是「全部」

名冊分頁是**管理**用的，封存的東西也要看得到 —— 不然使用者要恢復一個封存的類別時，
會先遇到「它不在清單裡」。這也維持了改版前的行為（以前一律 `include_archived=True`）。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QWidget,
)

SEARCH_WIDTH = 260
"""搜尋框的寬度上限。名冊裡的名字都很短（「早餐」「電子票證儲值」），
再寬也不會比較好打，只會把篩選列拉成一條橫貫畫面的線。"""

STATUS_OPTIONS: tuple[tuple[str, str], ...] = (
    ("全部", "all"),
    ("使用中", "active"),
    ("已封存", "archived"),
)
"""「全部」排第一，因為它是預設值 —— 見模組說明。"""


class CatalogFilterBar(QWidget):
    """搜尋 ＋ 狀態（＋ 所屬類別）。改了就發 `changed`。"""

    changed = Signal()

    def __init__(self, *, with_parent: bool = False) -> None:
        super().__init__()
        self.search = QLineEdit()
        self.status = QComboBox()
        self.parent_filter = QComboBox() if with_parent else None
        self._build()

    def _build(self) -> None:
        self.search.setPlaceholderText("搜尋名稱")
        self.search.setClearButtonEnabled(True)
        # **搜尋框有寬度上限，而且整列靠左。** 這一頁的表格用 `fit_content` 收到欄寬
        # 總和（三欄大約 460 px），篩選列若吃滿 1600 px 就會變成一條橫貫畫面的輸入框
        # 浮在一張小表上面 —— 跟 `form_panel()` 給表單設上限是同一個理由。
        self.search.setMaximumWidth(SEARCH_WIDTH)
        for label, value in STATUS_OPTIONS:
            self.status.addItem(label, value)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("搜尋"))
        layout.addWidget(self.search)
        if self.parent_filter is not None:
            layout.addSpacing(12)
            layout.addWidget(QLabel("所屬類別"))
            layout.addWidget(self.parent_filter)
        layout.addSpacing(12)
        layout.addWidget(QLabel("狀態"))
        layout.addWidget(self.status)
        layout.addStretch()

        # **改了就生效。** `textChanged` 而不是 `returnPressed` —— 這些表只有幾十列，
        # 邊打邊縮短清單比「打完再按 Enter」快，也不需要一顆「套用」按鈕。
        #
        # 要用 `lambda *_:` 把來源訊號的參數吃掉。`textChanged` 帶一個 `str`、
        # `currentIndexChanged` 帶一個 `int`，直接接到零參數的 `changed.emit` 會在
        # 事件迴圈裡丟 `TypeError: changed() only accepts 0 argument(s)` ——
        # 而**那個例外不會讓操作失敗，只會讓畫面不更新**，看起來像篩選壞掉。
        self.search.textChanged.connect(lambda *_: self.changed.emit())
        self.status.currentIndexChanged.connect(lambda *_: self.changed.emit())
        if self.parent_filter is not None:
            self.parent_filter.currentIndexChanged.connect(
                lambda *_: self.changed.emit()
            )

    def set_parents(self, parents: list[dict[str, Any]]) -> None:
        """重填「所屬類別」下拉並**保住目前的選擇**。

        重填會發 `currentIndexChanged`，所以先擋住訊號 —— 否則新增一個項目之後
        畫面會自己跳回「全部」。
        """
        combo = self.parent_filter
        if combo is None:
            return
        previous = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("全部", None)
        for item in parents:
            combo.addItem(str(item["name"]), str(item["category_id"]))
        index = combo.findData(previous)
        combo.setCurrentIndex(max(index, 0))
        combo.blockSignals(False)

    def search_text(self) -> str:
        return str(self.search.text()).strip()

    def status_value(self) -> str:
        value = self.status.currentData()
        return str(value) if isinstance(value, str) else "all"

    def parent_id(self) -> str | None:
        if self.parent_filter is None:
            return None
        value = self.parent_filter.currentData()
        return str(value) if isinstance(value, str) else None
