"""下拉選單、日期時間輸入與狀態訊息的共用操作。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, cast

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QTextCharFormat
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCalendarWidget,
    QComboBox,
    QDateEdit,
    QLabel,
    QLayout,
    QWidget,
)

from tagcor_ledger.infrastructure.clock import TAIPEI
from tagcor_ledger.ui import colors
from tagcor_ledger.ui.widgets.layout import FORM_WIDTH

CALENDAR_ROWS = 7
"""日曆格線的列數：一列星期標題 ＋ 六列日期。**六列是上限不是常態** ——
某些月份（1 號在週六、31 天）真的會用到第六列，少算一列就是最後一排被切掉。"""

CALENDAR_ROW_PADDING = 6
"""每一格在文字高度之外留的呼吸空間（px）。跟著字型算，不寫死列高。"""

MIN_YEAR = 2000
"""日期欄的下限。沒有下限時年份可以一路跑到 9999 —— 那不是任何人想輸入的值。"""

FUTURE_YEARS = 60
"""日期欄的上限：今年再往後幾年。

**這是防手滑的護欄，不是業務規則**，所以寧可寬也不要窄 —— 上限訂得太緊會把一個
合法的日期**無聲地夾**成別的值，那比讓年份跑到 9999 更糟。
定存的期長最長是 600 個月（`deposits.py` 的 `setRange(1, 600)`）＝ 50 年，
所以下限就是 50；留到 60 是給起存日本身也在未來的情況一點餘裕。
"""


def form_panel(form: QLayout, *, max_width: int = FORM_WIDTH) -> QWidget:
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

    **每一個日期欄都必須從這裡生出來**，不要自己 `QDateEdit(...)`。底下處理的那個
    誤觸問題是 Qt 與 QSS 交互作用的結果，繞過工廠的欄位就完全沒有被保護到 ——
    `tests/unit/test_architecture.py` 有一條守著。
    """
    widget = QDateEdit(value or QDate.currentDate())
    widget.setCalendarPopup(True)
    widget.setDisplayFormat("yyyy/MM/dd")

    # **關掉上下鍵，否則點欄位任何一處都會改掉年份。**
    #
    # `QStyle::SubControl` 有兩組列舉值是**同一個數字**：
    #     SC_ComboBoxFrame     == SC_SpinBoxUp   == 0x1
    #     SC_ComboBoxEditField == SC_SpinBoxDown == 0x2
    #
    # `QDateTimeEdit` 在 `calendarPopup` 模式下用 **CC_ComboBox** 做命中測試，命中結果
    # 不是 `SC_ComboBoxArrow` 時就轉給 `QAbstractSpinBox::mousePressEvent`，而後者拿
    # 同一個數字去比 `SC_SpinBoxUp` / `SC_SpinBoxDown`。於是：
    #
    # | 點在哪 | 命中回傳 | spinbox 讀成 | 結果 |
    # |---|---|---|---|
    # | 內距那一圈（框線與文字之間） | `SC_ComboBoxFrame` 0x1 | 上箭頭 | 年份 **+1** |
    # | 文字上 | `SC_ComboBoxEditField` 0x2 | 下箭頭 | 年份 **−1** |
    #
    # 平常那一圈只有 1 px 所以碰不到，但本專案的 QSS 給輸入欄 `padding: 7px 10px`
    # —— 那一圈變成 7～10 px，就在使用者伸手去點右邊箭頭的路徑上。
    # 而 `displayFormat` 以 `yyyy` 開頭，`currentSection` 預設就是年，所以動到的是年份。
    # 2026-08-21 實測：點上緣、下緣、左緣內距都是 +1，點文字正中是 −1。
    #
    # `QAbstractSpinBox::mousePressEvent` 在 `buttonSymbols == NoButtons` 時直接把
    # `stepEnabled()` 當成 `StepNone`，整條路就斷了。**日曆箭頭不受影響** ——
    # 它是 `CC_ComboBox` 畫的，也在轉交之前就先處理掉了。
    widget.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)

    # 鍵盤上下鍵與滾輪仍然可用，讓它們預設動「日」而不是「年」。
    widget.setCurrentSection(QDateEdit.Section.DaySection)

    today = QDate.currentDate()
    widget.setDateRange(QDate(MIN_YEAR, 1, 1), today.addYears(FUTURE_YEARS))
    _style_calendar(widget.calendarWidget())
    return widget


def _style_calendar(calendar: QCalendarWidget | None) -> None:
    """日曆彈出視窗裡 QSS 碰不到、或碰了也沒用的那幾件事。

    - **週數欄拿掉。** 記帳用不到第幾週，那一欄只是雜訊。
    - **格線拿掉**，維持整個介面「用留白分隔、不用線」的做法。
    - **週末不上紅字。** Qt 預設把週六日畫成紅色，但在這個程式裡紅色是「支出」的意思
      （見 `AGENTS.md` 的 UI 樣式規範）。日曆上多一抹紅只會讓那條規則變得沒有意義。
      星期標題與日期的顏色一律走色票。
    - **高度要放得下六列日期。** 有些月份真的會用到第六列，而 QSS 改了列高之後
      `QCalendarPopup` 算出來的高度會少一截 —— 2026-08-21 實測最後一排被切掉 7 px。
      這裡照字型現算，不寫死列高。
    """
    if calendar is None:
        return
    calendar.setVerticalHeaderFormat(
        QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
    )
    calendar.setGridVisible(False)

    neutral = QTextCharFormat()
    neutral.setForeground(QColor(colors.TEXT))
    for day in (
        Qt.DayOfWeek.Monday,
        Qt.DayOfWeek.Tuesday,
        Qt.DayOfWeek.Wednesday,
        Qt.DayOfWeek.Thursday,
        Qt.DayOfWeek.Friday,
        Qt.DayOfWeek.Saturday,
        Qt.DayOfWeek.Sunday,
    ):
        calendar.setWeekdayTextFormat(day, neutral)

    navigation = calendar.findChild(QWidget, "qt_calendar_navigationbar")
    header = navigation.sizeHint().height() if navigation is not None else 0
    row = calendar.fontMetrics().height() + CALENDAR_ROW_PADDING
    calendar.setMinimumHeight(header + CALENDAR_ROWS * row)


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
