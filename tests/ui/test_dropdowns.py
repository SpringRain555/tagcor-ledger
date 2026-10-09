"""下拉選單：清單開在下拉框正下方、一次最多 10 項、清單撐得下最長那一項。

三件事都是 Qt 的預設行為與這個專案的 QSS 疊在一起的結果（見 `styles.qss` 的 `QComboBox`
規則與 `forms.combo_box()`），所以這裡量的是**打開之後的 geometry**，不是設定值 ——
`maxVisibleItems` 從第一天起就是 10，只是在 Fusion 的選單模式下沒有人理它。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QStyle,
    QStyleOptionComboBox,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.ui.theme import apply_dark_theme
from tagcor_ledger.ui.widgets.forms import COMBO_VISIBLE_ITEMS, combo_box

LONG_NAME = "本金無限次數自動轉期續存，利息轉存帳戶"
"""定存的到期及轉存方式裡最長的那一個（逐字照存單，不能縮短）。"""


@pytest.fixture
def host(qtbot: Any) -> Iterator[QWidget]:
    """一個放下拉的視窗。主題一個 process 只套一次，這裡呼叫只是確保已經套過。"""
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    apply_dark_theme(app)
    widget = QWidget()
    qtbot.addWidget(widget)
    QVBoxLayout(widget)
    widget.resize(320, 560)
    widget.move(40, 20)
    yield widget


def _show(host: QWidget, combo: QComboBox) -> None:
    """靠左放，**下拉框維持自己的寬度**（第一次顯示時量出來的），跟表單裡的一樣 ——
    被版面拉滿的話，量不出「長名字比下拉框寬」那種情形。"""
    layout = host.layout()
    assert isinstance(layout, QVBoxLayout)
    layout.addWidget(combo, alignment=Qt.AlignmentFlag.AlignLeft)
    layout.addStretch()
    host.show()
    QApplication.processEvents()


def _popup_geometry(combo: QComboBox) -> tuple[int, int]:
    """打開清單，回傳 (清單上緣, 清單下緣) 的螢幕座標。呼叫端負責 `hidePopup()`。"""
    combo.showPopup()
    QApplication.processEvents()
    popup = combo.view().window()
    assert popup.isVisible(), "清單沒有打開，底下的量測都不算數"
    geometry = popup.geometry()
    return geometry.top(), geometry.bottom()


def test_the_list_opens_below_and_scrolls_after_ten_rows(host: QWidget) -> None:
    """選到最後一項再打開：清單**不動**、開在下拉框正下方、只顯示 10 列、其餘用捲軸。

    選單模式（修之前）下，選到下面的選項會把整個清單往上推、蓋住下拉框，而且 25 項全部
    攤開沒有捲軸 —— 2026-10-09 實測清單頂到螢幕上緣、624 px 高。
    """
    combo = combo_box()
    for index in range(25):
        combo.addItem(f"項目 {index + 1}")
    _show(host, combo)
    combo.setCurrentIndex(24)
    combo_top = combo.mapToGlobal(QPoint(0, 0)).y()
    combo_bottom = combo.mapToGlobal(QPoint(0, combo.height())).y()

    top, bottom = _popup_geometry(combo)
    view = combo.view()
    try:
        assert top >= combo_bottom - 1 or bottom <= combo_top + 1, (
            f"清單蓋到下拉框上了：清單 {top}–{bottom}、下拉框 {combo_top}–{combo_bottom}"
        )
        shown = view.viewport().height() / view.sizeHintForRow(0)
        assert round(shown) == COMBO_VISIBLE_ITEMS, f"一次顯示了 {shown:.1f} 列"
        assert view.verticalScrollBar().isVisible(), "超過上限要有捲軸"
        current = view.model().index(24, 0)
        assert view.selectionModel().isSelected(current), "目前那一項要反白"
        assert view.viewport().rect().contains(view.visualRect(current).center()), (
            "目前那一項要捲進可視範圍"
        )
    finally:
        combo.hidePopup()


def test_a_short_list_shows_every_row_without_a_scrollbar(host: QWidget) -> None:
    """陽性對照：上限是「最多」，不是「一律 10 列高」。三項就是三列、沒有捲軸。"""
    combo = combo_box()
    for name in ("現金", "郵局", "悠遊聯名"):
        combo.addItem(name)
    _show(host, combo)

    _popup_geometry(combo)
    view = combo.view()
    try:
        shown = view.viewport().height() / view.sizeHintForRow(0)
        assert round(shown) == 3, f"一次顯示了 {shown:.1f} 列"
        assert not view.verticalScrollBar().isVisible()
    finally:
        combo.hidePopup()


def test_the_list_is_as_wide_as_its_longest_item(host: QWidget) -> None:
    """下拉框的寬度在第一次顯示時就定了，**之後才加進來的長名字**也要整個看得到。

    選單模式會自己把清單撐寬；清單模式不會，那件事是 `combo_box()` 做的。
    """
    combo = combo_box()
    combo.addItem("現金")
    _show(host, combo)
    combo.addItem(LONG_NAME)
    view = combo.view()
    needed = view.sizeHintForColumn(0)
    assert needed > combo.width(), (
        f"前提：最長那一項（{needed} px）要比下拉框（{combo.width()} px）寬，否則這條沒在測撐寬"
    )

    _popup_geometry(combo)
    try:
        assert view.viewport().width() >= needed, (
            f"清單 {view.viewport().width()} px 放不下 {needed} px 的項目，會被從中間省略"
        )
    finally:
        combo.hidePopup()


def test_every_dropdown_in_the_window_opens_as_a_list(window: Any) -> None:
    """畫面上的每一個下拉都要是清單模式、上限 10 —— 量的是**真的建出來的那些**。

    架構測試擋的是「繞過工廠」；這一條擋的是 QSS 那一行被拿掉或寫錯（那時 Qt 不報錯，
    只是安靜地回到選單模式）。
    """
    checked = 0
    for combo in window.findChildren(QComboBox):
        option = QStyleOptionComboBox()
        combo.initStyleOption(option)
        hint = combo.style().styleHint(QStyle.StyleHint.SH_ComboBox_Popup, option, combo)
        assert hint == 0, f"{combo!r} 還是選單模式（SH_ComboBox_Popup = {hint}）"
        assert combo.maxVisibleItems() == COMBO_VISIBLE_ITEMS, repr(combo)
        checked += 1
    assert checked >= 12, f"只檢查到 {checked} 個下拉，主視窗有 15 個（2026-10-09）"
