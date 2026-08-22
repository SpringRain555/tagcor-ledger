"""固定深色主題（中性純灰）。

**顏色一律從 `colors.py` 取**，這裡不出現任何寫死的色碼 —— palette 與 QSS 用的是
同一份色票，才不會出現「QSS 改了、palette 沒改」那種只在某些原生元件上看得到的殘留。
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from tagcor_ledger.app.resources import read_text_resource
from tagcor_ledger.ui import colors


APPLIED_PROPERTY = "tagcorDarkThemeApplied"
"""標記在 `QApplication` 上，代表這個 process 已經套過主題了。見 `apply_dark_theme`。"""


def apply_dark_theme(app: QApplication, *, force: bool = False) -> None:
    """套用固定的深色主題（Fusion style、字體、palette、QSS）。

    **要在任何 widget 建出來之前呼叫。** 它換掉整個 application 的字體，而表格在
    建構當下就會量自己該多寬 —— 順序反了，量到的是預設字體下的尺寸，之後不會重算。

    ## 同一個 process 只套一次

    `setFont` / `setPalette` / `setStyleSheet` 都是 **application 層級**的操作：Qt 必須
    把改變傳播給**當下活著的每一個 widget**，並重跑一次 style polish。所以這個函式的
    成本不是固定的，而是隨著 process 裡的 widget 數量長 —— 而且長得比線性還快。

    正式執行時只有一個 `MainWindow`，所以這件事看不出來（實測約 150 ms，開程式時
    付一次）。**測試裡才會爆炸**：每一條 UI 測試都建一個 `MainWindow`，而
    pytest-qt 的 `addWidget` 只保證關掉、不保證當場銷毀。2026-08-22 量到的數字是

        活著 0 個視窗 -> 建下一個要   261 ms
        活著 5 個     ->            1,614 ms
        活著 15 個    ->           12,814 ms
        活著 25 個    ->           49,705 ms

    把這個函式換成 no-op 之後同一條曲線是**平的**（115 ms -> 104 ms），所以成本
    百分之百出在這裡，不是 `MainWindow` 本身慢。整包 UI 測試因此要跑 32 分鐘。

    第二次套用在語意上是 no-op（同一份字體、同一份 palette、同一份 QSS），所以直接
    跳過。`force=True` 留給真的要重套的情況（目前沒有呼叫端）。
    """
    if not force and bool(app.property(APPLIED_PROPERTY)):
        return

    app.setStyle("Fusion")

    app.setFont(ui_font())

    app.setPalette(_build_palette())
    try:
        app.setStyleSheet(read_text_resource("styles.qss"))
    except FileNotFoundError:
        app.setStyleSheet("")
    app.setProperty(APPLIED_PROPERTY, True)


FONT_FAMILY = "Microsoft JhengHei UI"
FONT_POINT_SIZE = 12.0


def ui_font() -> QFont:
    """介面字體。

    ## 為什麼主字體是中文字型而不是 `Segoe UI Variable`

    `Segoe UI Variable` **沒有中文字形**，中文全部是 fallback 出來的。後果是：
    對它設 Medium 字重，**只有數字與英文變粗，中文完全沒變** —— 字重設定套不到
    fallback 字型上。2026-08-20 把七種組合排在一起比對時才看出來。

    介面幾乎全是中文，所以主字體直接用中文 UI 字型，字重才管得到該管的字。

    ## 為什麼是 Medium 而不是 Normal

    深色底上的淺色字看起來會比實際細（同樣的筆畫，亮字在暗底上視覺上更瘦）。
    Medium 補回來剛好，再重就顯得吵。
    """
    font = QFont(FONT_FAMILY)
    font.setPointSizeF(FONT_POINT_SIZE)
    font.setWeight(QFont.Weight.Medium)
    return font


def _build_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(colors.BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(colors.TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(colors.SURFACE))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(colors.RAISED))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(colors.RAISED))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(colors.TEXT))
    palette.setColor(QPalette.ColorRole.Text, QColor(colors.TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(colors.RAISED))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(colors.TEXT))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(colors.EXPENSE))
    # 選取是灰的，不是彩色的 —— 使用者選的是「幾乎不用彩色」。
    palette.setColor(QPalette.ColorRole.Highlight, QColor(colors.SELECTED))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(colors.TEXT))

    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(
            QPalette.ColorGroup.Disabled, role, QColor(colors.TEXT_FAINT)
        )
    return palette
