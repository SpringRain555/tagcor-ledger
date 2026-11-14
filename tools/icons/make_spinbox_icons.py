"""產生 QSpinBox 的上下箭頭 PNG，標準與 @2x 各一張。"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPolygonF

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESOURCES = PROJECT_ROOT / "src" / "tagcor_ledger" / "resources"
BASE_SIZE = 12
COLOUR = "#E8E8EA"


def draw(direction: str, size: int, path: Path) -> None:
    """畫一個置中的實心三角形箭頭。"""
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    unit = size / BASE_SIZE
    if direction == "up":
        points = ((2, 8), (10, 8), (6, 3))
    else:
        points = ((2, 4), (10, 4), (6, 9))
    polygon = QPolygonF(
        [QPointF(x * unit, y * unit) for x, y in points]
    )
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(COLOUR))
    painter.drawPolygon(polygon)
    painter.end()
    if not image.save(str(path), "PNG"):
        raise SystemExit(f"寫不出 {path}")


def main() -> int:
    for direction in ("up", "down"):
        draw(direction, BASE_SIZE, RESOURCES / f"spin-{direction}.png")
        draw(direction, BASE_SIZE * 2, RESOURCES / f"spin-{direction}@2x.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
