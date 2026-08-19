"""固定深色主題（中性純灰）。

**顏色一律從 `colors.py` 取**，這裡不出現任何寫死的色碼 —— palette 與 QSS 用的是
同一份色票，才不會出現「QSS 改了、palette 沒改」那種只在某些原生元件上看得到的殘留。
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from tagcor_ledger.app.resources import read_text_resource
from tagcor_ledger.ui import colors


def apply_dark_theme(app: QApplication) -> None:
    """Apply the fixed TagCor Ledger dark theme to the Qt application."""
    app.setStyle("Fusion")

    app.setFont(ui_font())

    app.setPalette(_build_palette())
    try:
        app.setStyleSheet(read_text_resource("styles.qss"))
    except FileNotFoundError:
        app.setStyleSheet("")


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
