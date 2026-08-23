"""定存的領域模型與利息試算。

## 兩個列舉決定一切

`InterestMethod`（計息方式）決定**期間內發生什麼**，`MaturityAction`（到期及轉存方式）
決定**到期那天發生什麼**。三 × 四共十二種組合，完整效果矩陣寫在
`docs/architecture/state-machines.md` §7。

## 中文名稱逐字照存單

`INTEREST_METHOD_NAMES` 與 `MATURITY_ACTION_NAMES` 的字串**是使用者在存單上看到的
那幾行字**，不是我們自己取的說明。使用者在下拉選單前面做的事就是把實體單據上的
打勾抄過來 —— 只要文字不是逐字相同，他就得自己重新推導一次對應關係，而選項 2 與
選項 4 的差別本來就只有「本金」與「本息」一個字。

唯一沒有抄進來的是選項 2 後半的「轉存成功後，本單自動失效」：那是郵局那張紙自己的
作廢規則，跟帳本要記什麼無關。**除此之外不要再縮短它們** —— v0.9.0 到 v0.23.0
之間這四個名字都是縮寫版，而 `REQ-0007` §列舉 從一開始就寫著全文。

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

from tagcor_ledger.domain.dates import add_months


PPM = Decimal(1_000_000)


class InterestMethod(StrEnum):
    """計息方式。"""

    LUMP_SUM = "lump_sum"  # 整存整付：一次存入，到期一次領本息
    MONTHLY_INTEREST = "monthly_interest"  # 存本取息：一次存入，每月領息，到期領回本金
    INSTALLMENT_SAVINGS = "installment_savings"  # 零存整付：每月存入，到期一次領本息


class MaturityAction(StrEnum):
    """到期及轉存方式。存單上是四個並排的打勾方格，順序與這裡相同。"""

    NONE = "none"  # 1 不自動轉存
    PRINCIPAL_INTEREST_TO_ACCOUNT = "principal_interest_to_account"  # 2 本金（息）自動轉存本人帳戶
    RENEW_PRINCIPAL_ONLY = "renew_principal_only"  # 3 本金無限次數自動轉期續存，利息轉存帳戶
    RENEW_PRINCIPAL_AND_INTEREST = "renew_principal_and_interest"  # 4 本息無限次數自動轉期續存


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
    """一期的狀態。

    **沒有「已到期」。** schema 的 CHECK 裡有 `'matured'`，但沒有任何程式碼寫得出它 ——
    確認到期是原子的（建立交易、收掉這一期、必要時開下一期一起發生），中間不存在
    「到期了但還沒處理」這個資料狀態。而 state-machines.md §7 的原則正是
    **不自動判定已到期**：日期到了不代表銀行處理過，也不代表使用者看過存摺。
    所以那個值從列舉這一側拿掉（v0.24.0），CHECK 那一側留著 —— 砍它要重建整張表，
    代價與收益不成比例，且允許集合比實際用到的大不會造成錯誤資料。
    """

    ACTIVE = "active"  # 存續中
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
    MaturityAction.PRINCIPAL_INTEREST_TO_ACCOUNT: "本金（息）自動轉存本人帳戶",
    MaturityAction.RENEW_PRINCIPAL_ONLY: "本金無限次數自動轉期續存，利息轉存帳戶",
    MaturityAction.RENEW_PRINCIPAL_AND_INTEREST: "本息無限次數自動轉期續存",
}
"""逐字照存單，見模組說明。改動這四個字串等於改變使用者對照單據的能力。"""

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
    account_name: str = ""
    """定存帳戶的名稱，由 store 的 JOIN 帶進來（比照 `DepositEvent.contract_name`）。

    **它一直是空的**：定存頁的「帳戶」欄從 v0.9.0 就存在，而 `_contract_view()`
    從來沒有這個 key，`deposit_contract_values()` 又寫成 `item.get("account_name", "")`
    —— 那個預設值把一整欄的空白變成了合法輸出。2026-08-23 看實機截圖才發現。
    """
    opened_on: str = ""
    """**存單上首次存入的那一天**（ISO 日期）。

    這是使用者手上那張紙印的數字，也是他在對話框裡填的東西 —— 而它多半**不等於**
    目前存續中那一期的起存日：勾了「無限次數自動轉期續存」的話郵局已經自動滾過
    好幾輪（112/11/15 存入的，2026-08-23 當下存續中的是 114/11/15 那一期，第 3 期）。

    v0.24.0 的第一版沒有這個欄位，於是對話框有一個欄位，它的正確值**不是使用者
    手上那張紙印的數字**，旁邊還要一段字解釋為什麼。那是設計沒對齊，不是使用者
    不會填。現在填的就是紙上那個數字，該滾到哪一期由 `current_term()` 算。

    跟另外兩個日期分清楚：`opened_on` 是**存單**上的，`recorded_on` 是**帳本**開始
    追蹤的那天，`DepositTerm.start_date` 是**這一期**的。三個都不一樣。
    """
    recorded_on: str = ""
    """把這份合約記進帳本的那一天（ISO 日期）。

    **這是產生待確認項目的下界**，見 `application/deposits/events.py`。既有定存本來就
    比開始記帳早，而那段期間的利息已經含在帳戶的期初餘額裡 —— 替它們產生草稿就是
    邀請使用者把同一筆錢記第二次。見 ADR-0012。

    空字串代表「不知道什麼時候記的」，此時下界不生效（舊資料的退路）。
    """


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


def suggest_maturity_interest_minor(
    *,
    interest_method: str,
    principal_minor: int,
    annual_rate_ppm: int | None,
    term_months: int,
    monthly_deposit_minor: int | None = None,
) -> int | None:
    """**到期那天還沒領到的**利息。與 `suggest_interest_minor()`（整期總額）不同。

    存本取息一律 0：它每個月都在領，到期日當天那一期也已經由 `INTEREST_PAYOUT`
    事件發過了，到期只剩本金轉回。

    v0.24.0 之前到期事件直接用整期總額當建議值，於是一份 100,000 @ 1.56% 的
    存本取息會產生 12 筆 130 元的領息（合計 1,560）**再加上**一筆建議 1,560 的
    到期利息 —— 照建議值確認下去，帳上的利息剛好是實際的兩倍。
    """
    if InterestMethod(interest_method) is InterestMethod.MONTHLY_INTEREST:
        return 0
    return suggest_interest_minor(
        interest_method=interest_method,
        principal_minor=principal_minor,
        annual_rate_ppm=annual_rate_ppm,
        term_months=term_months,
        monthly_deposit_minor=monthly_deposit_minor,
    )


def matured_principal_minor(
    *,
    interest_method: str,
    principal_minor: int,
    monthly_deposit_minor: int | None,
    term_months: int,
) -> int:
    """到期時定存帳戶裡的本金 —— 也就是要轉回去或續存下去的那一筆。

    **零存整付的本金不是 `principal_minor`。** 它一開始就是 0（見
    `test_installment_savings_ignores_the_principal_entirely`），本金是每月存入
    累積出來的。v0.24.0 之前到期直接轉 `principal_minor`，所以零存整付到期時
    「本金轉回」是一筆 **0 元**的轉帳，續存的下一期本金也是 0。

    `principal_minor` 若已經是正數就用它 —— 那是使用者在「修改所選期」自己填的，
    比程式用面額推的準（例如中間漏存過一期）。那也是這個估算值唯一的修正入口，
    因為確認到期時只問利息，不問本金。
    """
    if InterestMethod(interest_method) is not InterestMethod.INSTALLMENT_SAVINGS:
        return principal_minor
    if principal_minor > 0:
        return principal_minor
    return (monthly_deposit_minor or 0) * term_months


def current_term(
    *, opened_on: str, term_months: int, maturity_action: str, today: str
) -> tuple[str, int]:
    """`today` 當下存續中那一期的**起存日與期序**（期序從 1 起算）。

    使用者手上的存單印的是**最初**那一期（例如 112/11/15 存入、113/11/15 到期），
    而勾了「無限次數自動轉期續存」的話郵局早就自動續存過好幾輪。2026-08-23 當下
    存續中的其實是 114/11/15 – 115/11/15，**而且它是第 3 期**。

    期序不是裝飾：它是使用者對得回存單的東西（「這份定存滾過兩輪了」）。
    中間那兩期**不建立資料列** —— 它們的實際利息與當時的牌告利率都不在帳本裡，
    憑空生出兩筆空的紀錄就是捏造事實。跳號是誠實的，補號不是。

    不續存的兩種（不自動轉存、本金（息）自動轉存本人帳戶）到期就結束了，沒有
    「下一期」可以滾過去，所以一律回 `(opened_on, 1)`。

    `term_months <= 0` 會讓 `add_months()` 永遠回同一天 —— 那是一個無窮迴圈。
    UI 的 spinbox 下限是 1，但這個函式在 domain，不能靠畫面保護。
    """
    if term_months <= 0 or not renews_forever(maturity_action):
        return opened_on, 1
    start, sequence = opened_on, 1
    while add_months(start, term_months) <= today:
        start = add_months(start, term_months)
        sequence += 1
    return start, sequence


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


def renews_forever(maturity_action: str) -> bool:
    """到期會自動轉期續存（存單上寫「無限次數」的那兩種）。

    `maturity_returns_principal()` 的反面，但**兩個都留著**：一個問「本金走不走」，
    一個問「這份定存還會不會有下一期」。目前答案互補，但那是巧合而不是定義 ——
    寫成 `not maturity_returns_principal(...)` 會讓呼叫端讀起來像在問錯的問題。
    """
    return MaturityAction(maturity_action) in {
        MaturityAction.RENEW_PRINCIPAL_ONLY,
        MaturityAction.RENEW_PRINCIPAL_AND_INTEREST,
    }


def interest_goes_to_deposit_account(maturity_action: str) -> bool:
    """利息是否留在定存帳戶裡（只有本息續存會）。"""
    return MaturityAction(maturity_action) is MaturityAction.RENEW_PRINCIPAL_AND_INTEREST
