"""Money value object and parsing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re


DECIMAL_RE = re.compile(r"^(0|[1-9]\d*)(\.\d+)?$")
CURRENCY_SCALE = {"TWD": 0}


class MoneyError(ValueError):
    """Raised when a money value violates the canonical format."""


@dataclass(frozen=True, slots=True)
class Money:
    """Integer-minor-unit money representation.

    TWD currently has a scale of zero. The currency field is retained so a
    future migration can add other currencies without changing transaction
    interfaces or storing binary floating-point values.
    """

    amount_minor: int
    currency: str = "TWD"

    def __post_init__(self) -> None:
        if self.currency not in CURRENCY_SCALE:
            raise MoneyError(f"Unsupported currency: {self.currency}")

    @classmethod
    def from_decimal_string(
        cls,
        value: str,
        *,
        currency: str = "TWD",
        allow_zero: bool = False,
    ) -> "Money":
        amount = parse_decimal_string(value, allow_zero=allow_zero)
        scale = CURRENCY_SCALE.get(currency)
        if scale is None:
            raise MoneyError(f"Unsupported currency: {currency}")
        multiplier = Decimal(10) ** scale
        minor = amount * multiplier
        rounded = minor.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        if minor != rounded:
            raise MoneyError(f"{currency} does not support fractional minor units.")
        return cls(int(rounded), currency)

    def to_decimal_string(self) -> str:
        scale = CURRENCY_SCALE[self.currency]
        if scale == 0:
            return str(self.amount_minor)
        sign = "-" if self.amount_minor < 0 else ""
        digits = str(abs(self.amount_minor)).zfill(scale + 1)
        return f"{sign}{digits[:-scale]}.{digits[-scale:]}"


def parse_decimal_string(value: str, *, allow_zero: bool = False) -> Decimal:
    if not isinstance(value, str):
        raise MoneyError("Amount must be stored as a string.")
    if not DECIMAL_RE.fullmatch(value):
        raise MoneyError("Amount must be a plain Decimal string without commas or exponent.")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise MoneyError("Amount is not a valid Decimal.") from exc
    if allow_zero:
        if amount < 0:
            raise MoneyError("Amount cannot be negative.")
    elif amount <= 0:
        raise MoneyError("Amount must be greater than zero.")
    return amount
