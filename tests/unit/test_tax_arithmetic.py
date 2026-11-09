"""稅務 ppm 比率只用整數運算的邊界測試。"""

import pytest

from tagcor_ledger.domain.tax.arithmetic import PPM, Rounding, apply_rate, rate_exceeds


@pytest.mark.parametrize(
    ("amount", "rate", "rounding", "expected"),
    [
        (0, 100_000, Rounding.FLOOR, 0),
        (20_005, 100_000, Rounding.FLOOR, 2_000),
        (20_005, 100_000, Rounding.HALF_UP, 2_001),
        (10**30, PPM, Rounding.FLOOR, 10**30),
        (10**30 + 1, PPM // 2, Rounding.HALF_UP, 5 * 10**29 + 1),
    ],
)
def test_apply_rate_uses_integer_rounding(
    amount: int, rate: int, rounding: Rounding, expected: int
) -> None:
    assert apply_rate(amount, rate, rounding) == expected


@pytest.mark.parametrize("amount, expected", [(19_999, False), (20_000, False), (20_001, True)])
def test_rate_exceeds_compares_before_rounding(amount: int, expected: bool) -> None:
    assert rate_exceeds(amount, 100_000, 2_000) is expected


@pytest.mark.parametrize(
    ("amount", "rate"),
    [(-1, 0), (0, -1), (True, 1)],
)
def test_apply_rate_rejects_negative_values_and_boolean_amounts(amount: int, rate: int) -> None:
    with pytest.raises(ValueError):
        apply_rate(amount, rate, Rounding.FLOOR)


