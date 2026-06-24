import pytest

from tagcor_ledger.domain.money import MoneyError, parse_decimal_string


def test_parse_decimal_string_rejects_float_like_forms() -> None:
    parse_decimal_string("120.50")

    for value in ("1e3", "1,000", "-1", "0"):
        with pytest.raises(MoneyError):
            parse_decimal_string(value)


def test_parse_decimal_string_can_allow_zero_for_templates() -> None:
    assert parse_decimal_string("0", allow_zero=True) == 0
