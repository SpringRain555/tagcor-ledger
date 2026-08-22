"""金額值物件與解析。**整數 minor unit，禁止 float。**"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re


DECIMAL_RE = re.compile(r"^(0|[1-9]\d*)(\.\d+)?$")
CURRENCY_SCALE = {"TWD": 0}


class MoneyError(ValueError):
    """金額不合規格。**訊息是錯誤碼，不是英文句子。**

    這裡跟 `infrastructure/stores/` 用同一套約定：例外的訊息就是穩定的錯誤碼，
    翻成中文是 `application/failures.py` 的事。

    以前這些例外帶的是 `"Amount must be greater than zero."` 這種英文散文，而
    應用層會把 `str(exc)` 塞進 `details["reason"]` —— 於是使用者在一個全中文的
    畫面上看到「請檢查交易內容。（Amount must be greater than zero.）」。
    金額打錯是最常見的操作失誤，那句英文因此是整個程式最常被看到的一句話之一。
    """


@dataclass(frozen=True, slots=True)
class Money:
    """以整數 minor unit 表示的金額。

    TWD 的 scale 是 0，所以 minor unit 就是元。`currency` 欄位留著是為了讓日後要加
    別的幣別時**不必改交易介面**，也不必為了小數而改存浮點數。
    """

    amount_minor: int
    currency: str = "TWD"

    def __post_init__(self) -> None:
        if self.currency not in CURRENCY_SCALE:
            raise MoneyError("CURRENCY_UNSUPPORTED")

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
            raise MoneyError("CURRENCY_UNSUPPORTED")
        multiplier = Decimal(10) ** scale
        minor = amount * multiplier
        rounded = minor.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        if minor != rounded:
            raise MoneyError("CURRENCY_FRACTION_UNSUPPORTED")
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
        raise MoneyError("AMOUNT_NOT_A_STRING")
    if not DECIMAL_RE.fullmatch(value):
        raise MoneyError("AMOUNT_FORMAT_INVALID")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        # 沒有第二個碼：`DECIMAL_RE` 沒攔下來、`Decimal()` 又不收，對使用者來說
        # 是同一件事 ——「這串字不是合法的金額」。分兩個碼只會多一列文件。
        raise MoneyError("AMOUNT_FORMAT_INVALID") from exc
    # **這裡沒有「不能是負數」的檢查，因為輪不到它。** `DECIMAL_RE` 不收正負號，
    # 所以 `-5` 在上面就以 `AMOUNT_FORMAT_INVALID` 退掉了。以前這裡有一個
    # `if allow_zero and amount < 0: raise MoneyError("AMOUNT_NEGATIVE")` ——
    # 那個分支永遠跑不到，而它掛著一個永遠不會出現在畫面上的錯誤碼。
    # `allow_zero` 管的只有 0，不管正負。
    if not allow_zero and amount <= 0:
        raise MoneyError("AMOUNT_NOT_POSITIVE")
    return amount
