"""以整數執行稅務比率與進位運算。"""

from enum import StrEnum


PPM = 1_000_000


class Rounding(StrEnum):
    """套用稅務比率時使用的進位方式。"""

    FLOOR = "floor"
    HALF_UP = "half_up"


def _nonnegative_integer(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} 必須是非負整數")


def apply_rate(amount: int, rate_ppm: int, rounding: Rounding) -> int:
    """依 ppm 比率計算金額，全程使用整數並套用指定進位。"""
    _nonnegative_integer(amount, "amount")
    _nonnegative_integer(rate_ppm, "rate_ppm")
    try:
        method = Rounding(rounding)
    except ValueError as exc:
        raise ValueError("不支援的進位方式") from exc

    quotient, remainder = divmod(amount * rate_ppm, PPM)
    if method is Rounding.HALF_UP and remainder * 2 >= PPM:
        return quotient + 1
    return quotient


def rate_exceeds(amount: int, rate_ppm: int, limit: int) -> bool:
    """以交叉相乘判斷未進位的費率金額是否嚴格超過上限。"""
    return amount * rate_ppm > limit * PPM
