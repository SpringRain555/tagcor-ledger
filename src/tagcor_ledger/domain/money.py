"""Money parsing and validation."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re


DECIMAL_RE = re.compile(r"^(0|[1-9]\d*)(\.\d+)?$")


class MoneyError(ValueError):
    """Raised when a money value violates the canonical format."""


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
