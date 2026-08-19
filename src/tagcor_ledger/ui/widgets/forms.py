"""下拉選單、日期時間輸入與狀態訊息的共用操作。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, cast

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QLabel,
    QLayout,
    QWidget,
)

from tagcor_ledger.infrastructure.clock import TAIPEI


FORM_MAX_WIDTH = 620


def form_panel(form: QLayout, *, max_width: int = FORM_MAX_WIDTH) -> QWidget:
    """把表單裝進有寬度上限的容器。

    視窗放大時，一個 1,400 px 寬的下拉選單不會比較好選 —— 只會讓標籤與欄位隔著
    半個螢幕，眼睛得橫著跑。表單有上限，表格才用滿寬度。
    """
    panel = QWidget()
    panel.setLayout(form)
    panel.setMaximumWidth(max_width)
    return panel


def status_label() -> QLabel:
    """建立一個會依成功／失敗換色的訊息標籤。

    以前每一頁都用 `errorLabel`（紅字）當唯一的訊息出口，於是「交易已儲存。」
    也是紅的 —— 每天最常做的動作，回饋長得像失敗。
    """
    label = QLabel()
    label.setObjectName("statusLabel")
    label.setWordWrap(True)
    return label


def show_status(label: QLabel, text: str, *, ok: bool | None = None) -> None:
    """設定訊息與狀態色。`ok=None` 表示中性提示（例如「內容已帶入」）。

    Qt 的 QSS 屬性選擇器**不會自己重新套用** —— 改了 property 之後一定要
    `unpolish` 再 `polish`，否則顏色會停在上一個狀態。
    """
    state = "" if ok is None else ("ok" if ok else "error")
    label.setProperty("state", state)
    label.setText(text)
    style = label.style()
    style.unpolish(label)
    style.polish(label)


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


def date_field(value: QDate | None = None) -> QDateEdit:
    """日期欄位。**只問到哪一天，不問幾點幾分。**

    記帳需要的精度就是「哪一天」—— 午餐是 12:07 還是 12:31 不會影響任何一個數字，
    但每記一筆都要面對一個時分欄位，那是每天都要付的成本。
    """
    widget = QDateEdit(value or QDate.currentDate())
    widget.setCalendarPopup(True)
    widget.setDisplayFormat("yyyy/MM/dd")
    return widget


def iso_from_date(widget: QDateEdit, *, keep_time_from: str | None = None) -> str:
    """畫面上的日期 → 帶時區的 ISO 時間戳。

    **資料庫仍然存完整時間戳。** 畫面只問日期，時分秒由程式補：

    - 新建：補現在的時分秒。同一天記好幾筆時，這是唯一能保住「先後順序」的東西 ——
      全部塞 00:00 的話，當天的排序就只能靠 id，看起來會是隨機的。
    - 編輯：沿用那筆原本的時分秒（`keep_time_from`）。只改個備註卻讓它跳到當天最後一筆，
      是沒有人會預期的行為。
    """
    day = cast(date, widget.date().toPython())
    clock = datetime.now(TAIPEI).time()
    if keep_time_from:
        try:
            clock = datetime.fromisoformat(keep_time_from).astimezone(TAIPEI).time()
        except ValueError:
            pass
    return datetime.combine(day, clock, tzinfo=TAIPEI).isoformat(timespec="seconds")


def iso_datetime(widget: QDateTimeEdit) -> str:
    """把畫面上的時間轉成帶時區的 ISO 字串。Qt 給的是 naive，一律當成台北時間。"""
    value = cast(datetime, widget.dateTime().toPython())
    if value.tzinfo is None:
        value = value.replace(tzinfo=TAIPEI)
    return value.astimezone(TAIPEI).isoformat(timespec="seconds")
