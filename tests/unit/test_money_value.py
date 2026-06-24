import pytest

from tagcor_ledger.domain.money import Money, MoneyError


def test_twd_uses_integer_minor_units() -> None:
    money = Money.from_decimal_string("120")

    assert money.amount_minor == 120
    assert money.currency == "TWD"
    assert money.to_decimal_string() == "120"


def test_twd_rejects_fractional_values() -> None:
    with pytest.raises(MoneyError):
        Money.from_decimal_string("1.5")
