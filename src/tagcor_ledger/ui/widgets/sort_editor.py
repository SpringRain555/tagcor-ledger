"""多層排序的設定面板：由上而下三層，每層一個欄位與升／降。

## 為什麼是固定三層，不是可以無限新增

三層以外的層級**分不出任何勝負** —— 每一份清單最後都會自動接上「名稱、id」當
tiebreaker，而名稱在同一組之內本來就唯一。做成可新增、可刪除、可上下移的動態列表，
是為了一個不存在的需求多蓋三顆按鈕。

三列固定在畫面上還有一個好處：**你一眼就看得到「現在總共排了幾層」**，不必先數。

## 「（不使用）」不是佔位符，它就是答案

第二、三層預設是「（不使用）」。使用者只想照名稱排的時候，第一層選名稱、後面兩列
不動就結束了 —— 不需要先去刪掉什麼。組規格時把「（不使用）」濾掉，順序照畫面由上
而下，所以中間留空也不會出事。

## 重複的欄位

同一個欄位選兩次，第二次不可能再分出勝負。這裡**不擋**（擋了要嘛得停用選項、要嘛
得跳警告，兩種都比問題本身吵），由 `base.order_by()` 在組 SQL 時跳過重複的那一層。
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QLabel,
    QWidget,
)

from tagcor_ledger.domain.models import SortLevel

LEVELS = 3
"""畫面上固定幾層。理由見模組說明。"""

NONE_FIELD = ""
"""「（不使用）」那一項的值。空字串永遠不會是白名單裡的 key。"""

DIRECTIONS: tuple[tuple[str, bool], ...] = (("升冪", False), ("降冪", True))
"""**不要寫「正序／反序」或「A→Z」。** 這幾頁排的東西有文字也有數字，
升冪／降冪對兩者都成立。"""


class SortEditor(QWidget):
    """三層排序的設定面板。改了就發 `changed`（不會自己存）。"""

    changed = Signal()

    def __init__(self, fields: Sequence[tuple[str, str]]) -> None:
        """`fields` 是 `(顯示文字, 欄位 key)`，順序就是下拉裡的順序。

        key 必須是那個 store 的白名單裡有的值 —— 這裡不檢查，
        因為認不出來的欄位在組 SQL 時本來就會被跳過（見 `base.order_by()`）。
        """
        super().__init__()
        self._fields = list(fields)
        self.field_boxes: list[QComboBox] = []
        self.direction_boxes: list[QComboBox] = []
        self._build()

    def _build(self) -> None:
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.addWidget(QLabel("排序方式"), 0, 0, 1, 3)
        for row in range(LEVELS):
            field_box = QComboBox()
            if row > 0:
                field_box.addItem("（不使用）", NONE_FIELD)
            for label, key in self._fields:
                field_box.addItem(label, key)
            direction_box = QComboBox()
            for label, descending in DIRECTIONS:
                direction_box.addItem(label, descending)
            field_box.currentIndexChanged.connect(lambda *_: self._emit())
            direction_box.currentIndexChanged.connect(lambda *_: self._emit())
            self.field_boxes.append(field_box)
            self.direction_boxes.append(direction_box)
            grid.addWidget(QLabel(f"{row + 1}."), row + 1, 0)
            grid.addWidget(field_box, row + 1, 1)
            grid.addWidget(direction_box, row + 1, 2)
        grid.setColumnStretch(1, 1)

    def _emit(self) -> None:
        # 「（不使用）」的那一列，方向選單沒有意義 —— 停用它，不要留一個轉得動
        # 但不影響任何東西的下拉。
        for field_box, direction_box in zip(
            self.field_boxes, self.direction_boxes, strict=True
        ):
            direction_box.setEnabled(bool(field_box.currentData()))
        self.changed.emit()

    def set_spec(self, spec: Sequence[SortLevel]) -> None:
        """把規格填回畫面。認不出來的欄位跳過 —— 跟組 SQL 時同一條規則。

        重填期間必須 `blockSignals`，否則每填一格就發一次 `changed`，
        接在上面的預覽會對著一份填到一半的規格重算。
        """
        known = {key for _label, key in self._fields}
        usable = [level for level in spec if level.field in known][:LEVELS]
        for row in range(LEVELS):
            field_box = self.field_boxes[row]
            direction_box = self.direction_boxes[row]
            field_box.blockSignals(True)
            direction_box.blockSignals(True)
            if row < len(usable):
                field_box.setCurrentIndex(max(field_box.findData(usable[row].field), 0))
                direction_box.setCurrentIndex(
                    max(direction_box.findData(usable[row].descending), 0)
                )
            else:
                field_box.setCurrentIndex(max(field_box.findData(NONE_FIELD), 0))
                direction_box.setCurrentIndex(0)
            field_box.blockSignals(False)
            direction_box.blockSignals(False)
        self._emit()

    def spec(self) -> tuple[SortLevel, ...]:
        """畫面上的規格，由上而下，「（不使用）」濾掉。"""
        levels: list[SortLevel] = []
        for field_box, direction_box in zip(
            self.field_boxes, self.direction_boxes, strict=True
        ):
            field = str(field_box.currentData() or "")
            if not field:
                continue
            levels.append(
                SortLevel(field=field, descending=bool(direction_box.currentData()))
            )
        return tuple(levels)

    def uses_custom(self) -> bool:
        """規格裡有沒有用到自訂順序（拖曳排出來的那一份）。

        沒有的話，拖曳的結果不會顯示在清單上 —— 對話框要明講，不然使用者會以為
        拖曳壞掉了。
        """
        return any(level.field.endswith("custom") for level in self.spec())
