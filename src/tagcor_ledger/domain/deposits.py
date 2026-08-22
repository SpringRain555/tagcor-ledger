"""定存的領域模型與利息試算。

## 兩個列舉決定一切

`InterestMethod`（計息方式）決定**期間內發生什麼**，`MaturityAction`（到期轉存方式）
決定**到期那天發生什麼**。三 × 四共十二種組合，完整效果矩陣寫在
`docs/architecture/state-machines.md` §7。

## 利率用整數存

`annual_rate_ppm` 是**百萬分之一為單位的整數**：1.60% 存成 `16000`。
理由和金額一樣 —— 這個專案禁止 float。牌告利率有到小數點後三位（例如 1.595%），
用 ppm 存得下且不會有二進位誤差。

可以是 `None`：**還沒查到牌告利率時就留空**，只是算不出建議利息，不影響記錄合約本身。

## 試算永遠只是建議

`suggest_interest_minor()` 算出來的是**建議值，不是權威值**。實際入帳金額以存摺為準，
使用者可以覆寫。理由很實際：銀行的計息基準（實際天數／一年算 365 還是 366 天／
進位到元還是角）沒有對到就會差幾塊錢，而差幾塊錢的帳本比沒有帳本更煩人。

**下列計算基準是假設，尚未查證**，已列為 Stage 6 法規參考庫的查證項目：
- 整存整付：按月複利
- 存本取息：單利，每月付息
- 零存整付：每月存入，按月複利
- 一律以「月」為單位、每月一期，不按實際天數
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum


PPM = Decimal(1_000_000)


class InterestMethod(StrEnum):
    """計息方式。"""

    LUMP_SUM = "lump_sum"  # 整存整付：一次存入，到期一次領本息
    MONTHLY_INTEREST = "monthly_interest"  # 存本取息：一次存入，每月領息，到期領回本金
    INSTALLMENT_SAVINGS = "installment_savings"  # 零存整付：每月存入，到期一次領本息


class MaturityAction(StrEnum):
    """到期轉存方式。"""

    NONE = "none"  # 不自動轉存
    PRINCIPAL_INTEREST_TO_ACCOUNT = "principal_interest_to_account"  # 本息自動轉存本人帳戶
    RENEW_PRINCIPAL_ONLY = "renew_principal_only"  # 本金自動轉期續存，利息轉存帳戶
    RENEW_PRINCIPAL_AND_INTEREST = "renew_principal_and_interest"  # 本息自動轉期續存


class RateType(StrEnum):
    """利率是固定的還是跟著牌告走。

    **機動利率不預先填數字。** 郵局的機動利率會隨牌告調整，存的當下填一個數字，
    到期時它多半已經不是那個值了 —— 那種「看起來精確但其實是舊的」比留空更糟。
    機動利率一律照存摺記實際利息，再由程式反推出這一期的實際年利率當紀錄。
    """

    FIXED = "fixed"  # 固定利率
    FLOATING = "floating"  # 機動利率


RATE_TYPE_NAMES = {
    RateType.FIXED: "固定",
    RateType.FLOATING: "機動",
}


class DepositTermStatus(StrEnum):
    ACTIVE = "active"  # 存續中
    MATURED = "matured"  # 已到期，尚未處理
    RENEWED = "renewed"  # 已續約，下一期已建立
    SETTLED = "settled"  # 已結清
    TERMINATED = "terminated"  # 已解約（中途）


class DepositEventType(StrEnum):
    INTEREST_PAYOUT = "interest_payout"  # 每月領息（存本取息）
    INSTALLMENT = "installment"  # 每月存入（零存整付）
    MATURITY = "maturity"  # 到期


class DepositEventStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    SKIPPED = "skipped"


INTEREST_METHOD_NAMES = {
    InterestMethod.LUMP_SUM: "整存整付",
    InterestMethod.MONTHLY_INTEREST: "存本取息",
    InterestMethod.INSTALLMENT_SAVINGS: "零存整付",
}

MATURITY_ACTION_NAMES = {
    MaturityAction.NONE: "不自動轉存",
    MaturityAction.PRINCIPAL_INTEREST_TO_ACCOUNT: "本息自動轉存本人帳戶",
    MaturityAction.RENEW_PRINCIPAL_ONLY: "本金自動轉期續存，利息轉存帳戶",
    MaturityAction.RENEW_PRINCIPAL_AND_INTEREST: "本息自動轉期續存",
}

DEPOSIT_EVENT_TYPE_NAMES = {
    DepositEventType.INTEREST_PAYOUT: "領息",
    DepositEventType.INSTALLMENT: "存入",
    DepositEventType.MATURITY: "到期",
}


@dataclass(frozen=True, slots=True)
class DepositContract:
    """持續性的定存關係。續約不會改這一筆，而是新增一期。"""

    contract_id: str
    account_id: str
    name: str
    interest_method: str
    maturity_action: str
    interest_destination_account_id: str | None
    term_months: int
    status: str
    note: str
    rate_type: str = "fixed"


@dataclass(frozen=True, slots=True)
class DepositTerm:
    """定存的一期。**續約產生新的一期，不修改舊的那一期。**

    這樣每次續約當時的牌告利率都留得下歷史 —— 實務上續存就是照當時的牌告利率，
    改寫舊紀錄會讓「當初是多少利率」永遠查不回來。
    """

    term_id: str
    contract_id: str
    sequence: int
    start_date: str
    maturity_date: str
    principal_minor: int
    annual_rate_ppm: int | None
    monthly_deposit_minor: int | None
    actual_interest_minor: int | None
    status: str
    note: str
    # 從實際利息反推出來的年利率。機動利率時這是唯一有意義的利率紀錄。
    effective_rate_ppm: int | None = None


@dataclass(frozen=True, slots=True)
class DepositEvent:
    """一件等待使用者確認的定存事件。**程式不會自己入帳。**"""

    event_id: str
    term_id: str
    contract_id: str
    contract_name: str
    event_type: str
    due_date: str
    status: str
    suggested_amount_minor: int | None
    actual_amount_minor: int | None
    transaction_id: str | None
    note: str


def monthly_rate(annual_rate_ppm: int) -> Decimal:
    """年利率轉月利率。單純除以 12，不做年化換算。"""
    return Decimal(annual_rate_ppm) / PPM / Decimal(12)


def rate_to_ppm(text: str) -> int | None:
    """使用者打的「1.6」或「1.6%」→ 16000 ppm。空字串回 `None`。

    **解析放在 domain，跟 `Money.from_decimal_string()` 同一個位置。** `annual_rate_ppm`
    是領域概念（整數 ppm，不碰二進位浮點數），「什麼字串算合法的利率」就該由定義那個
    概念的地方回答 —— 2026-08-22 之前這個函式住在 `ui/pages/deposits.py`，
    於是「利率長什麼樣」的知識有一半在畫面層。

    格式不對丟 `decimal.InvalidOperation`。**它繼承的是 `ArithmeticError`，不是
    `ValueError`** —— 所以呼叫端要自己列出來，`except ValueError` 接不到它。
    （`ui/pages/deposits.py` 兩處 `save()` 都寫 `except (InvalidOperation, ValueError)`，
    那不是多餘的。同一個坑 `NotFoundError` 也踩過，見 `application/failures.py`。）
    """
    clean = text.strip().rstrip("%").strip()
    if not clean:
        return None
    return int((Decimal(clean) / Decimal(100) * PPM).to_integral_value())


def suggest_interest_minor(
    *,
    interest_method: str,
    principal_minor: int,
    annual_rate_ppm: int | None,
    term_months: int,
    monthly_deposit_minor: int | None = None,
) -> int | None:
    """算出這一期的**建議**利息（整數元）。利率未知就回 `None`。

    一律用 `Decimal`，最後才進位成整數。TWD 沒有輔幣，所以進位到元。
    """
    if annual_rate_ppm is None or term_months <= 0:
        return None
    rate = monthly_rate(annual_rate_ppm)
    if rate <= 0:
        return 0

    method = InterestMethod(interest_method)
    if method is InterestMethod.MONTHLY_INTEREST:
        # 單利：每月領息，整期總額就是每月利息乘以月數。
        total = Decimal(principal_minor) * rate * Decimal(term_months)
    elif method is InterestMethod.LUMP_SUM:
        # 按月複利：到期本利和減本金。
        total = Decimal(principal_minor) * ((Decimal(1) + rate) ** term_months - Decimal(1))
    else:
        # 零存整付：每月月初存入一筆，各自複利到期末。
        deposit = Decimal(monthly_deposit_minor or 0)
        if deposit <= 0:
            return 0
        accumulated = Decimal(0)
        for month in range(term_months):
            remaining = term_months - month
            accumulated += deposit * ((Decimal(1) + rate) ** remaining)
        total = accumulated - deposit * Decimal(term_months)
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def suggest_monthly_interest_minor(
    *, principal_minor: int, annual_rate_ppm: int | None
) -> int | None:
    """存本取息每個月領多少（建議值）。"""
    if annual_rate_ppm is None:
        return None
    total = Decimal(principal_minor) * monthly_rate(annual_rate_ppm)
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# 反推時的搜尋上界。**1% 是 10,000 ppm**，所以 100% 是 1,000,000 —— 不是 100,000,000。
# 定存利率在 1–2% 這個量級，100% 已經是非常寬的天花板；超過它多半是金額打錯字。
MAX_RATE_PPM = 1_000_000


def derive_annual_rate_ppm(
    *,
    interest_method: str,
    principal_minor: int,
    interest_minor: int,
    term_months: int,
    monthly_deposit_minor: int | None = None,
) -> int | None:
    """從**實際領到的利息**反推這一期的年利率（ppm）。

    機動利率的正確用法：不預先填利率，到期照存摺輸入實際利息，再由這裡算出
    「這一期實際上等於年利率多少」存起來當紀錄。

    做法是拿 `suggest_interest_minor()` 做二分搜尋，而不是各自推導反函數。這樣有兩個
    好處：三種計息方式共用同一套邏輯（零存整付沒有簡潔的反函數），而且**反推一定與
    正推一致** —— 進位規則變了兩邊會一起變，不會各說各話。
    """
    if term_months <= 0 or interest_minor < 0:
        return None
    if principal_minor <= 0 and not monthly_deposit_minor:
        return None

    def forward(ppm: int) -> int:
        value = suggest_interest_minor(
            interest_method=interest_method,
            principal_minor=principal_minor,
            annual_rate_ppm=ppm,
            term_months=term_months,
            monthly_deposit_minor=monthly_deposit_minor,
        )
        return value if value is not None else 0

    if interest_minor == 0:
        return 0
    if forward(MAX_RATE_PPM) < interest_minor:
        return None  # 利息大到超過 100% 年利率，多半是輸入錯了

    low, high = 0, MAX_RATE_PPM
    while low < high:
        middle = (low + high) // 2
        if forward(middle) < interest_minor:
            low = middle + 1
        else:
            high = middle
    return low


def renewed_principal_minor(
    *, maturity_action: str, principal_minor: int, interest_minor: int
) -> int | None:
    """續約後下一期的本金。不續約回 `None`。"""
    action = MaturityAction(maturity_action)
    if action is MaturityAction.RENEW_PRINCIPAL_ONLY:
        return principal_minor
    if action is MaturityAction.RENEW_PRINCIPAL_AND_INTEREST:
        return principal_minor + interest_minor
    return None


def maturity_returns_principal(maturity_action: str) -> bool:
    """到期時本金是否離開定存帳戶。"""
    return MaturityAction(maturity_action) in {
        MaturityAction.NONE,
        MaturityAction.PRINCIPAL_INTEREST_TO_ACCOUNT,
    }


def interest_goes_to_deposit_account(maturity_action: str) -> bool:
    """利息是否留在定存帳戶裡（只有本息續存會）。"""
    return MaturityAction(maturity_action) is MaturityAction.RENEW_PRINCIPAL_AND_INTEREST
