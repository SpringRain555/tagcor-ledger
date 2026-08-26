import re
from pathlib import Path
from unittest import mock

import pytest

from tagcor_ledger.app.resources import (
    read_text_resource,
    resource_exists,
    resource_filesystem_path,
)
from tagcor_ledger.ui import colors, theme

HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}\b")


def test_styles_resource_is_packaged() -> None:
    assert resource_exists("styles.qss")
    assert "QLineEdit:focus" in read_text_resource("styles.qss")


def test_the_check_icon_is_packaged_at_both_sizes() -> None:
    """勾號兩個尺寸都要在，而且 `@2x` 真的是兩倍。

    只給標準版的話高 DPI 螢幕上會糊 —— Qt 的 stylesheet 會照 devicePixelRatio
    自己去找 `@2x` 那一張，找不到就把 18px 那張放大。
    """
    from PySide6.QtGui import QImage

    for name, expected in (("check.png", 18), ("check@2x.png", 36)):
        assert resource_exists(name), f"{name} 不見了，跑 tools/icons/make_check_icon.py"
        path = resource_filesystem_path(name)
        assert path is not None, name
        image = QImage(str(path))
        assert not image.isNull(), f"{name} 讀不出來"
        assert image.size().width() == expected, (name, image.size().width())
        assert image.size().height() == expected, (name, image.size().height())
        # 陽性對照：真的有畫到東西，不是一張全透明的圖。
        opaque = sum(
            1
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y).alpha() > 0
        )
        assert opaque > 0, f"{name} 是全透明的 —— 產生腳本沒畫到東西"


def test_the_check_icon_placeholder_is_resolved_to_a_real_file() -> None:
    """QSS 裡的佔位字串要被換成真的檔案路徑，而且是正斜線。

    反斜線的 Windows 路徑在 `url()` 裡會解析失敗，而失敗的樣子不是報錯，是那一格
    靜靜地不畫圖 —— 跟這個勾號當初消失的方式一模一樣。
    """
    styles = read_text_resource("styles.qss")
    assert theme.CHECK_ICON_PLACEHOLDER in styles, "QSS 裡的佔位字串不見了"

    resolved = theme.resolve_stylesheet(styles)
    assert theme.CHECK_ICON_PLACEHOLDER not in resolved
    match = re.search(r"image:\s*url\(([^)]+)\)", resolved)
    assert match is not None, "代換之後找不到 image: url(...)"
    path = Path(match.group(1))
    assert path.is_file(), path
    assert "\\" not in match.group(1), f"路徑裡有反斜線：{match.group(1)}"


def test_a_missing_check_icon_drops_the_line_instead_of_leaving_it_broken() -> None:
    """取不到圖檔時整行拿掉，不要留一個壞掉的 `url()`。

    留著的話 Qt 會把 `image` 當成有指定，於是連 `background-color` 都不畫 ——
    方框會整個消失，比沒有勾號糟得多。
    """
    styles = read_text_resource("styles.qss")
    with mock.patch.object(theme, "resource_filesystem_path", return_value=None):
        resolved = theme.resolve_stylesheet(styles)

    assert theme.CHECK_ICON_PLACEHOLDER not in resolved
    # `image: none`（日曆那條）是別人的規則，不該被掃到 —— 這裡找的是有 url() 的那種。
    assert re.search(r"image:\s*url\(", resolved) is None, "壞掉的 image: url() 還留著"
    # 方框本身必須還在，否則退回的樣子比原本更糟。
    assert "QCheckBox::indicator:checked" in resolved
    assert f"background-color: {colors.PRIMARY_BG};" in resolved


def test_the_check_icon_is_drawn_in_the_background_colour() -> None:
    """勾號畫在白色方框上，顏色必須是 `colors.BG` —— 產生腳本裡那個常數不能漂掉。"""
    source = (
        Path(__file__).resolve().parents[2] / "tools" / "icons" / "make_check_icon.py"
    ).read_text(encoding="utf-8")
    assert f'COLOUR = "{colors.BG}"' in source, "產生腳本的勾號顏色與 colors.BG 不一致"


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


def channel(value: float) -> float:
    value /= 255
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    raw = hex_color.lstrip("#")
    red, green, blue = (int(raw[index : index + 2], 16) for index in (0, 2, 4))
    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)


def contrast(first: str, second: str) -> float:
    """WCAG 的對比公式。**模組層級的共用函式**，不要在測試裡再抄一份。

    2026-08-23 之前這三個是 `test_amount_colours_stay_readable_on_every_surface()`
    裡的巢狀函式；圓環的色階要用同一套算法，而複製一份的話兩邊遲早會分岔 ——
    然後其中一邊會用一個錯的公式繼續回報「通過」。
    """
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_amount_colours_stay_readable_on_every_surface() -> None:
    """紅綠必須在**選取列**上也讀得到 —— 選取時背景最亮，對比最差。

    只在一般背景上量對比是漏掉一半：使用者按下某一列時，那一列的金額
    正好是他最想看清楚的東西。
    """
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


def _block(styles: str, selector: str) -> str:
    """抓出某個 selector 的宣告區塊。找不到就讓測試自己失敗，不回空字串。"""
    start = styles.index(selector)
    return styles[styles.index("{", start) + 1 : styles.index("}", start)]


def _px(block: str, name: str) -> list[int]:
    """某個宣告裡的所有 px 值。`border-top: 1px solid #9A9AA5` 只取 1。"""
    match = re.search(rf"^\s*{name}:\s*([^;]+);", block, re.MULTILINE)
    assert match, f"區塊裡沒有 {name}：{block!r}"
    values = [int(found) for found in re.findall(r"(\d+)px", match.group(1))]
    assert values, f"{name} 裡沒有 px 值：{match.group(1)!r}"
    return values


def test_selecting_a_row_does_not_squeeze_the_text() -> None:
    """選取列多了上下框線，**內容高度必須一模一樣**。

    列高被 `verticalHeader().setDefaultSectionSize(34)` 釘死，而 Qt 的 `::item` 是
    content-box —— 直接加 2px 框線就是從文字的可用高度裡扣，中文的上下會被切掉一截。
    所以 `padding` 要同步從 7px 收成 6px：7 = 6 + 1。

    這條守的是**下一個人**：把框線加粗、或再加一條上下框線的時候，padding 沒跟著改
    的話畫面上只會是「選取的那一列字看起來怪怪的」，不會有任何東西變紅。
    """
    styles = read_text_resource("styles.qss")
    normal = _px(_block(styles, "QTableView::item {"), "padding")
    selected_block = _block(styles, "QTableView::item:selected {")
    selected = _px(selected_block, "padding")
    top = _px(selected_block, "border-top")[0]
    bottom = _px(selected_block, "border-bottom")[0]

    assert normal[0] == selected[0] + top, (
        f"上緣：一般列 padding {normal[0]}px、選取列 {selected[0]}px ＋ 框線 {top}px"
    )
    assert normal[0] == selected[0] + bottom, "下緣對不上"
    assert normal[1] == selected[1], "左右內距不該跟著改，文字會左右跳"


def test_a_selected_row_is_told_apart_by_more_than_brightness() -> None:
    """選取列**不能只靠底色**。

    `SELECTED` 對一般列底 `SURFACE` 的對比只有 1.34，而它已經是上限了 ——
    再亮一階，支出紅對選取列的對比就掉到 4.5 以下（`test_amount_colours_...` 會紅）。
    改動之前是 1.20，實機上幾乎看不出哪一列被選中。

    所以一定要有第二個線索。這裡認的是「選取列有畫框線」，不指定畫在哪一邊 ——
    上下、左側都算數，但**一條都沒有就不行**。
    """
    ratio = contrast(colors.SELECTED, colors.SURFACE)
    assert ratio < 3.0, (
        f"選取列底色現在有 {ratio:.2f}:1 —— 如果真的做得到，這條測試可以放寬，"
        "但先確認支出紅對它還有 4.5"
    )
    selected_block = _block(read_text_resource("styles.qss"), "QTableView::item:selected {")
    assert "border-" in selected_block, (
        "選取列只有底色。底色的對比只有 1.34，光靠它說不出「就是這一列」"
    )


@pytest.mark.parametrize("slice_color", colors.CHART_SLICES)
def test_every_chart_slice_is_visible_against_the_page(slice_color: str) -> None:
    """圓環的每一階對底色的對比 >= 3.0（WCAG 1.4.11 的圖形物件門檻）。

    這是「看得出有一片東西」與「看不出來」的界線，不是憑眼睛挑的。實算過
    `#5C5C66` 只有 2.73、`#45454E` 只有 1.90 —— 灰階梯度**不能**再往深處延伸，
    而「再加一階就好」正是最容易順手做的事。

    拿 `SURFACE` 與 `BG` 兩個底都量：圓環畫在頁面背景上，但這個 widget 沒有理由
    不能被放進一張卡片裡，而那時候底就換成 `SURFACE` 了。
    """
    for surface in (colors.BG, colors.SURFACE):
        ratio = contrast(slice_color, surface)
        assert ratio >= 3.0, f"{slice_color} 在 {surface} 上只有 {ratio:.2f}:1"


def test_chart_slices_are_told_apart_from_each_other() -> None:
    """相鄰兩階要真的分得出來，而且整組由淺到深。

    六階灰之間沒有色相可以幫忙，全靠明度 —— 順序亂掉或兩階太接近的話，圓環就從
    「哪一片比較大」退化成一片糊掉的灰。門檻 1.15 是相鄰兩階的對比比值。
    """
    assert len(set(colors.CHART_SLICES)) == len(colors.CHART_SLICES), "有重複的色階"
    levels = [luminance(color) for color in colors.CHART_SLICES]
    assert levels == sorted(levels, reverse=True), "色階不是由淺到深"
    for index in range(len(levels) - 1):
        ratio = (levels[index] + 0.05) / (levels[index + 1] + 0.05)
        assert ratio >= 1.15, (
            f"第 {index + 1} 與第 {index + 2} 階（{colors.CHART_SLICES[index]}／"
            f"{colors.CHART_SLICES[index + 1]}）只差 {ratio:.2f}，分不出來"
        )


def test_chart_slices_are_deliberately_not_in_the_qss_allowlist() -> None:
    """`CHART_SLICES` **不在 `ALL_TOKENS` 裡，這是刻意的不是漏加**。

    `ALL_TOKENS` 是 QSS 的允許清單，而圓環與圖例色塊全部是 `QPainter` 畫的。
    把它們加進去等於在樣式表那一側開六個沒有人要用的洞 —— 而下一個人看到
    「colors.py 裡有、ALL_TOKENS 裡沒有」的第一個反應就是去補上。
    """
    assert not set(colors.CHART_SLICES) & colors.ALL_TOKENS
