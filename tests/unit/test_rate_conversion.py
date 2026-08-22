"""利率的解析與顯示。**「1.6% 長什麼樣」只能有一份實作。**

2026-08-22 之前這件事有兩份：`ui/formatting/primitives.py::rate_text()` 給表格用，
`ui/pages/deposits.py::ppm_to_rate_text()` 給輸入框用 —— **核心那兩行一模一樣**：

    whole, fraction = divmod(int(ppm), 10_000)
    f"{whole}.{fraction:04d}".rstrip("0").rstrip(".")

兩者只差在外框（要不要加百分號、空值寫「未填」還是空字串）。而頁面那一份**完全沒有
測試**，於是「表格顯示 1.6%、輸入框顯示 1.6」這件事沒有任何東西保證它們一致。

`rate_to_ppm()` 一併從畫面層搬到 `domain/deposits.py` —— 它是
`Money.from_decimal_string()` 的對應物，「什麼字串算合法的利率」該由定義
`annual_rate_ppm` 的地方回答。
"""

from __future__ import annotations

from decimal import InvalidOperation

import pytest

from tagcor_ledger.domain.deposits import rate_to_ppm
from tagcor_ledger.ui.formatting import ppm_digits, rate_input_text, rate_text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.6", 16_000),
        ("1.6%", 16_000),
        ("  1.6 % ", 16_000),  # 前後空白與百分號都要吃掉
        ("0", 0),
        ("0.0000", 0),
        ("100", 1_000_000),  # 上限就是 100%
        ("0.0001", 1),  # 最小可表示的一格
        ("1.60000", 16_000),  # 多餘的零不影響
        ("", None),
        ("   ", None),
        ("%", None),  # 只有百分號等於沒填
    ],
)
def test_rate_to_ppm_reads_what_a_person_would_type(text: str, expected: int | None) -> None:
    assert rate_to_ppm(text) == expected


@pytest.mark.parametrize("text", ["一點六", "1.6.6", "abc", "1,6"])
def test_rate_to_ppm_refuses_things_that_are_not_numbers(text: str) -> None:
    """格式不對丟 `InvalidOperation` —— **不要猜一個數字回去。**

    猜錯的利率會一路算進建議利息，而使用者不會發現。
    """
    with pytest.raises(InvalidOperation):
        rate_to_ppm(text)


def test_the_parse_error_is_not_a_value_error() -> None:
    """**`InvalidOperation` 繼承 `ArithmeticError`，不是 `ValueError`。**

    這條看起來像在測標準函式庫，但它守的是呼叫端：`ui/pages/deposits.py` 兩處
    `save()` 都寫 `except (InvalidOperation, ValueError)`，有人「精簡」掉前者的話
    輸入框打錯字會直接炸到全域錯誤對話框。這一條會先紅。

    同一個形狀在這個專案出現過兩次 —— 另一次是 `NotFoundError` 繼承 `RuntimeError`
    而 15 個 handler 漏掉它（v0.21.0 修）。
    """
    assert not issubclass(InvalidOperation, ValueError)
    assert issubclass(InvalidOperation, ArithmeticError)


@pytest.mark.parametrize(
    ("ppm", "digits"),
    [
        (16_000, "1.6"),
        (0, "0"),
        (1_595, "0.1595"),
        (1, "0.0001"),
        (1_000_000, "100"),
        (10_000, "1"),
    ],
)
def test_ppm_digits_never_uses_floating_point(ppm: int, digits: str) -> None:
    """整數除法組字串，不碰二進位浮點數。`0.1595` 用 float 會變成 `0.15949999...`。"""
    assert ppm_digits(ppm) == digits


@pytest.mark.parametrize("ppm", [0, 1, 1_595, 16_000, 999_999, 1_000_000])
def test_parsing_and_formatting_are_inverses(ppm: int) -> None:
    """**互為反函數。** 輸入框顯示的字，讀回去要是同一個 ppm。

    這是這一份最重要的一條：畫面上顯示 1.6、使用者沒改就按儲存，存回去必須還是 16000。
    """
    assert rate_to_ppm(rate_input_text(ppm)) == ppm


def test_the_two_wrappers_only_differ_in_their_frame() -> None:
    """表格用的與輸入框用的，數字部分必須一模一樣。

    差別只有：表格加百分號、空值寫「未填」；輸入框不加百分號、空值是空字串
    （空字串才讀得回 `None`）。
    """
    assert rate_text(16_000) == "1.6%"
    assert rate_input_text(16_000) == "1.6"
    assert rate_text(None) == "未填"
    assert rate_input_text(None) == ""

    for ppm in (0, 1_595, 16_000, 1_000_000):
        assert rate_text(ppm) == rate_input_text(ppm) + "%"


def test_the_input_box_never_shows_a_word_the_parser_cannot_read() -> None:
    """輸入框不准出現「未填」—— 那個字讀回去會炸。

    這正是為什麼不能讓輸入框直接用 `rate_text()`。
    """
    assert rate_to_ppm(rate_input_text(None)) is None
    with pytest.raises(InvalidOperation):
        rate_to_ppm(rate_text(None))
