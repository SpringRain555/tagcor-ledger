"""Application-wide PySide6 dark theme."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from tagcor_ledger.app.resources import read_text_resource


def apply_dark_theme(app: QApplication) -> None:
    """Apply the fixed TagCor Ledger dark theme to the Qt application."""
    app.setStyle("Fusion")

    font = QFont("Segoe UI Variable")
    font.setPointSize(11)
    app.setFont(font)

    app.setPalette(_build_palette())
    try:
        app.setStyleSheet(read_text_resource("styles.qss"))
    except FileNotFoundError:
        app.setStyleSheet("")


def _build_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#0F172A"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#E5E7EB"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#111827"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#162033"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#1E293B"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#F8FAFC"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#E5E7EB"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#1E293B"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#E5E7EB"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#F87171"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#3B82F6"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))

    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.WindowText,
        QColor("#64748B"),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor("#64748B"),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor("#64748B"),
    )
    return palette
