"""下拉選單與日期時間輸入的共用操作。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from PySide6.QtWidgets import QComboBox, QDateTimeEdit

from tagcor_ledger.infrastructure.clock import TAIPEI


def fill_combo(
    combo: QComboBox,
    items: list[dict[str, Any]],
    label_key: str,
    value_key: str,
    *,
    first: tuple[str, Any] | None = None,
) -> None:
    """重填選項並盡量保留原本選的那一個。

    重填期間必須 `blockSignals` —— 否則 `clear()` 會觸發 `currentIndexChanged`，讓連在
    上面的 handler 對著空的選單跑一次。
    """
    current = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    if first is not None:
        combo.addItem(first[0], first[1])
    for item in items:
        combo.addItem(str(item[label_key]), item[value_key])
    select_data(combo, current)
    combo.blockSignals(False)


def select_data(combo: QComboBox, value: object) -> None:
    """選到 data 等於 `value` 的那一項；找不到就維持原狀，不清空。"""
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)


def iso_datetime(widget: QDateTimeEdit) -> str:
    """把畫面上的時間轉成帶時區的 ISO 字串。Qt 給的是 naive，一律當成台北時間。"""
    value = cast(datetime, widget.dateTime().toPython())
    if value.tzinfo is None:
        value = value.replace(tzinfo=TAIPEI)
    return value.astimezone(TAIPEI).isoformat(timespec="seconds")
