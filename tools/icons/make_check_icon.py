"""產生勾選框的勾號 PNG（`check.png` 與 `check@2x.png`）。

## 為什麼需要一個圖檔

QSS 一旦碰了 `QCheckBox::indicator`，Fusion 就不再畫自己的勾號 —— 跟
`QComboBox::drop-down` 那個坑是同一個機制。而**整段不覆寫也不行**：Fusion 的方框
外框色是 `palette.window().darker(140)` 推導的，本專案的 Window 是 `#0D0D0F`，
於是外框在深色底上完全看不見，未勾選的那一格會變成一片空白。

所以是「方框」與「勾號」二選一，除非給它一張圖。實測過的兩條死路：

- **SVG**：`image: url(...svg)` 什麼都不畫。這個環境沒有 Qt SVG image plugin
  （`QImageReader.supportedImageFormats()` 裡沒有 `svg`），而它是 PySide6 的
  選配元件，不該讓畫面正確性依賴它裝了沒有。
- **data URI**：QSS 的 `url()` 不支援 `data:image/png;base64,...`，實測不畫。

PNG 是唯一可行的。**兩個尺寸都要**：Qt 的 stylesheet 會照 devicePixelRatio 自己去找
`@2x` 那一張，只給一張的話高 DPI 螢幕上會糊。

## 為什麼是腳本而不是用繪圖軟體畫

兩個尺寸必須是同一個形狀等比例放大 —— 手畫的話 `@2x` 那張的線寬遲早會跟標準版
對不起來，而那種差異只在高 DPI 螢幕上看得到。要改形狀就改這裡的座標再重跑。

```powershell
& $env:TAGCOR_PYTHON tools/icons/make_check_icon.py
```

（正斜線是刻意的：docstring 不是 raw string，Windows 路徑裡的反斜線加大寫 U
會被當成 unicode escape 而整個檔案語法錯誤。）

`tests/unit/test_resources.py` 會驗兩個檔案都在、尺寸正確、而且真的有畫到東西。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESOURCES = PROJECT_ROOT / "src" / "tagcor_ledger" / "resources"

BASE_SIZE = 18
"""QSS 裡 `QCheckBox::indicator` 的寬高。改那邊要一起改這裡。"""

COLOUR = "#0D0D0F"
"""`colors.BG`。勾號畫在**白色**的已勾選方框上，所以用底色才夠深。

這個值刻意寫死而不是 import `colors` —— 這支腳本不在執行期跑，讓它依賴 UI 層
只是為了少寫一行字串。`test_resources.py` 會比對它與 `colors.BG` 一致。
"""


def draw(size: int, path: Path) -> None:
    """畫一個透明底的勾號。座標以 18px 為基準等比例縮放，線寬也是。"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    unit = size / BASE_SIZE
    stroke = QPainterPath()
    stroke.moveTo(4.2 * unit, 9.4 * unit)
    stroke.lineTo(7.4 * unit, 12.6 * unit)
    stroke.lineTo(13.8 * unit, 5.6 * unit)
    pen = QPen(QColor(COLOUR), 2.2 * unit)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawPath(stroke)
    painter.end()
    if not pixmap.save(str(path), "PNG"):
        raise SystemExit(f"寫不出 {path}")
    print(f"{path.name}: {size}x{size}, {path.stat().st_size} bytes")


def main() -> int:
    QApplication([])
    draw(BASE_SIZE, RESOURCES / "check.png")
    draw(BASE_SIZE * 2, RESOURCES / "check@2x.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
