import re

import pytest

from tagcor_ledger.app.resources import read_text_resource, resource_exists
from tagcor_ledger.ui import colors

HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}\b")


def test_styles_resource_is_packaged() -> None:
    assert resource_exists("styles.qss")
    assert "QLineEdit:focus" in read_text_resource("styles.qss")


def test_styles_define_dark_theme_colors_and_scoped_widgets() -> None:
    styles = read_text_resource("styles.qss")

    assert "QLineEdit," in styles
    assert "QComboBox," in styles
    assert f"color: {colors.TEXT};" in styles
    assert f"background-color: {colors.BG};" in styles
    assert f"selection-background-color: {colors.SELECTED};" in styles
    assert "QTabBar::tab" in styles
    assert "QFrame#sidebarRail" in styles
    assert "QListWidget#sidebarNavigation" in styles
    assert "QListWidget#backupList" in styles
    assert "QPushButton#dangerButton" in styles
    assert "QLabel#statusLabel" in styles
    assert "QPushButton#segmentButton" in styles


def test_every_colour_in_the_stylesheet_is_a_declared_token() -> None:
    """QSS 裡不得出現 `colors.py` 沒宣告的色碼。

    沒有這條守門的話，「順手調深一點」會一次一個地把畫面變回一堆沒人記得的灰，
    而且 `theme.py` 的 palette 與 QSS 會慢慢對不起來 —— 那種不一致只在某些
    原生元件上看得到，實機才會發現。
    """
    styles = read_text_resource("styles.qss")
    found = {match.group(0).upper() for match in HEX_COLOR.finditer(styles)}
    declared = {token.upper() for token in colors.ALL_TOKENS}
    assert found, "掃不到任何色碼，正規表示式壞了"
    unknown = sorted(found - declared)
    assert not unknown, f"這些色碼不在 colors.py 裡：{unknown}"


def test_amount_colours_stay_readable_on_every_surface() -> None:
    """紅綠必須在**選取列**上也讀得到 —— 選取時背景最亮，對比最差。

    只在一般背景上量對比是漏掉一半：使用者按下某一列時，那一列的金額
    正好是他最想看清楚的東西。
    """

    def channel(value: float) -> float:
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    def luminance(hex_color: str) -> float:
        raw = hex_color.lstrip("#")
        red, green, blue = (int(raw[index : index + 2], 16) for index in (0, 2, 4))
        return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)

    def contrast(first: str, second: str) -> float:
        light, dark = sorted((luminance(first), luminance(second)), reverse=True)
        return (light + 0.05) / (dark + 0.05)

    surfaces = (colors.BG, colors.SURFACE, colors.RAISED, colors.SELECTED)
    for foreground in (colors.TEXT, colors.TEXT_MUTED, colors.EXPENSE, colors.INCOME):
        for surface in surfaces:
            ratio = contrast(foreground, surface)
            assert ratio >= 4.5, f"{foreground} 在 {surface} 上只有 {ratio:.2f}:1"


@pytest.mark.parametrize(
    ("first", "second"),
    [(colors.EXPENSE, colors.INCOME), (colors.EXPENSE, colors.TEXT)],
)
def test_amount_colours_are_distinguishable_from_each_other(first: str, second: str) -> None:
    assert first != second
