"""守門：定存的計息與到期規則。

這一份補的是 2026-08-22 掃出來的缺口 —— `renewed_principal_minor`、
`maturity_returns_principal`、`interest_goes_to_deposit_account` 在 `tests/` 底下
**一次都沒有被引用過**，而它們正是「到期那天發生什麼」的全部判準。整組 12 種組合
以前只在 `tests/integration/test_deposits.py` 裡被挑幾種走過一遍。

`domain/deposits.py` 是純函式而且**不碰資料庫**，所以這些測試是毫秒級的 ——
邊界值該窮舉就窮舉，不必挑。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tagcor_ledger.domain.deposits import (
    MAX_RATE_PPM,
    InterestMethod,
    MaturityAction,
    derive_annual_rate_ppm,
    current_term,
    interest_goes_to_deposit_account,
    matured_principal_minor,
    maturity_returns_principal,
    monthly_rate,
    renewed_principal_minor,
    renews_forever,
    suggest_interest_minor,
    suggest_maturity_interest_minor,
    suggest_monthly_interest_minor,
)

PRINCIPAL = 1_000_000  # 100 萬
RATE_PPM = 12_000  # 1.2%／年 → 月利率剛好 0.001，好對答案
MONTHS = 12
MONTHLY_DEPOSIT = 100_000

ALL_METHODS = tuple(InterestMethod)
ALL_ACTIONS = tuple(MaturityAction)


# --- 到期那天發生什麼：完整的四 × 三矩陣 ----------------------------------------

# `AGENTS.md` 與 `docs/architecture/state-machines.md` §7 寫的那張表，逐格寫成資料。
# **三欄一起寫在同一份，不是三份各自的參數化** —— 一格改錯的時候，這樣才看得出來
# 它跟同一列的其他兩欄矛盾。
MATURITY_MATRIX = {
    #                                      本金離開定存  利息留在定存  續約後的本金
    MaturityAction.NONE: (True, False, None),
    MaturityAction.PRINCIPAL_INTEREST_TO_ACCOUNT: (True, False, None),
    MaturityAction.RENEW_PRINCIPAL_ONLY: (False, False, "principal"),
    MaturityAction.RENEW_PRINCIPAL_AND_INTEREST: (False, True, "principal+interest"),
}


def test_the_matrix_covers_every_maturity_action() -> None:
    """陽性對照：新增一種到期及轉存方式而沒補矩陣時，這裡先失敗。

    少了它，底下三條會安靜地只驗現有的四種，而新加的那一種一條都沒測到。
    """
    assert set(MATURITY_MATRIX) == set(ALL_ACTIONS)
    assert len(ALL_ACTIONS) == 4


@pytest.mark.parametrize("action", ALL_ACTIONS)
def test_whether_the_principal_leaves_the_deposit_account(action: MaturityAction) -> None:
    expected, _, _ = MATURITY_MATRIX[action]
    assert maturity_returns_principal(str(action)) is expected


@pytest.mark.parametrize("action", ALL_ACTIONS)
def test_only_full_renewal_keeps_the_interest_inside_the_deposit(
    action: MaturityAction,
) -> None:
    _, expected, _ = MATURITY_MATRIX[action]
    assert interest_goes_to_deposit_account(str(action)) is expected


@pytest.mark.parametrize("action", ALL_ACTIONS)
def test_the_renewed_principal_follows_the_maturity_action(action: MaturityAction) -> None:
    interest = 7_777
    _, _, shape = MATURITY_MATRIX[action]
    result = renewed_principal_minor(
        maturity_action=str(action), principal_minor=PRINCIPAL, interest_minor=interest
    )
    if shape is None:
        assert result is None
    elif shape == "principal":
        assert result == PRINCIPAL
    else:
        assert result == PRINCIPAL + interest
        # 本息續存的重點就是**下一期的本金會變大**。少了這一句，
        # 上面那個加法寫成減法也還是「不等於 PRINCIPAL」。
        assert result > PRINCIPAL


@pytest.mark.parametrize(
    "function",
    [maturity_returns_principal, interest_goes_to_deposit_account],
)
def test_an_unknown_maturity_action_is_rejected_not_guessed(function: object) -> None:
    """認不出來就丟例外，不要靜靜回 False —— 那會讓打錯字的值看起來像「不轉存」。"""
    with pytest.raises(ValueError):
        function("not_a_real_action")  # type: ignore[operator]


def test_renewing_with_an_unknown_action_is_rejected_too() -> None:
    with pytest.raises(ValueError):
        renewed_principal_minor(
            maturity_action="not_a_real_action", principal_minor=1, interest_minor=1
        )


# --- 建議利息 -------------------------------------------------------------------


def test_monthly_rate_is_the_annual_rate_divided_by_twelve() -> None:
    assert monthly_rate(RATE_PPM) == Decimal("0.001")
    assert monthly_rate(0) == Decimal(0)


@pytest.mark.parametrize("method", ALL_METHODS)
def test_an_unknown_rate_means_no_suggestion_at_all(method: InterestMethod) -> None:
    """機動利率不預先填數字，所以「算不出來」是正常狀態，不是錯誤。

    **回 `None` 不是回 0。** 0 會被畫面印成一個看起來像答案的數字。
    """
    assert (
        suggest_interest_minor(
            interest_method=str(method),
            principal_minor=PRINCIPAL,
            annual_rate_ppm=None,
            term_months=MONTHS,
            monthly_deposit_minor=MONTHLY_DEPOSIT,
        )
        is None
    )


@pytest.mark.parametrize("method", ALL_METHODS)
@pytest.mark.parametrize("months", [0, -1])
def test_a_term_with_no_months_has_no_suggestion(method: InterestMethod, months: int) -> None:
    assert (
        suggest_interest_minor(
            interest_method=str(method),
            principal_minor=PRINCIPAL,
            annual_rate_ppm=RATE_PPM,
            term_months=months,
            monthly_deposit_minor=MONTHLY_DEPOSIT,
        )
        is None
    )


@pytest.mark.parametrize("method", ALL_METHODS)
def test_a_zero_rate_earns_exactly_zero(method: InterestMethod) -> None:
    """0% 與「還沒填」是兩件事：前者算得出來，答案是 0；後者算不出來，答案是 `None`。"""
    assert (
        suggest_interest_minor(
            interest_method=str(method),
            principal_minor=PRINCIPAL,
            annual_rate_ppm=0,
            term_months=MONTHS,
            monthly_deposit_minor=MONTHLY_DEPOSIT,
        )
        == 0
    )


def test_monthly_interest_is_simple_interest() -> None:
    """存本取息＝單利：每月領息，整期總額就是每月利息 × 月數。"""
    assert (
        suggest_interest_minor(
            interest_method=str(InterestMethod.MONTHLY_INTEREST),
            principal_minor=PRINCIPAL,
            annual_rate_ppm=RATE_PPM,
            term_months=MONTHS,
        )
        == 12_000
    )


def test_lump_sum_compounds_so_it_beats_simple_interest() -> None:
    """整存整付＝按月複利，所以同樣本金、利率、月數一定**多於**單利。

    這裡斷言的是關係不是數字 —— 進位規則調整時數字會動，但「複利大於單利」不會。
    另外釘住一個實際值，避免關係成立但兩邊都算錯。
    """
    simple = suggest_interest_minor(
        interest_method=str(InterestMethod.MONTHLY_INTEREST),
        principal_minor=PRINCIPAL,
        annual_rate_ppm=RATE_PPM,
        term_months=MONTHS,
    )
    compound = suggest_interest_minor(
        interest_method=str(InterestMethod.LUMP_SUM),
        principal_minor=PRINCIPAL,
        annual_rate_ppm=RATE_PPM,
        term_months=MONTHS,
    )
    assert simple is not None and compound is not None
    assert compound > simple
    assert compound == 12_066


def test_installment_savings_ignores_the_principal_entirely() -> None:
    """零存整付的利息只由**每月存入**決定，`principal_minor` 完全不參與計算。

    這不是巧合而是定義：那種存法一開始就沒有本金，本金是每個月累積出來的。
    傳一個天文數字的本金進去答案要一模一樣。
    """
    def interest(principal: int) -> int | None:
        return suggest_interest_minor(
            interest_method=str(InterestMethod.INSTALLMENT_SAVINGS),
            principal_minor=principal,
            annual_rate_ppm=RATE_PPM,
            term_months=MONTHS,
            monthly_deposit_minor=MONTHLY_DEPOSIT,
        )

    assert interest(0) == interest(PRINCIPAL) == interest(99_999_999) == 7_829


@pytest.mark.parametrize("monthly", [0, None])
def test_installment_savings_without_a_monthly_deposit_earns_nothing(
    monthly: int | None,
) -> None:
    assert (
        suggest_interest_minor(
            interest_method=str(InterestMethod.INSTALLMENT_SAVINGS),
            principal_minor=PRINCIPAL,
            annual_rate_ppm=RATE_PPM,
            term_months=MONTHS,
            monthly_deposit_minor=monthly,
        )
        == 0
    )


def test_the_monthly_payout_is_one_months_worth() -> None:
    assert (
        suggest_monthly_interest_minor(principal_minor=PRINCIPAL, annual_rate_ppm=RATE_PPM)
        == 1_000
    )
    assert suggest_monthly_interest_minor(principal_minor=PRINCIPAL, annual_rate_ppm=None) is None


def test_the_monthly_payout_rounds_half_up_to_whole_dollars() -> None:
    """TWD 沒有輔幣，所以進位到元；規則是 ROUND_HALF_UP 不是銀行家進位。

    本金 5,000、月利率 0.0001 → 剛好 0.5 元。`ROUND_HALF_UP` 給 1，
    Python 內建的 `round()`（銀行家進位）會給 0。
    """
    assert suggest_monthly_interest_minor(principal_minor=5_000, annual_rate_ppm=1_200) == 1


# --- 從實際利息反推年利率 --------------------------------------------------------


@pytest.mark.parametrize("method", ALL_METHODS)
def test_deriving_the_rate_round_trips_through_the_forward_calculation(
    method: InterestMethod,
) -> None:
    """反推的正確性定義**就是**「拿它再正推一次會得到同一個利息」。

    不是「反推回原本填的 ppm」—— 進位讓好幾個相鄰的 ppm 對應到同一個整數利息，
    二分搜尋找的是其中最小的那一個，所以要求還原原值是錯的期待。
    docstring 說的「反推一定與正推一致」講的是這一條。
    """
    kwargs = {
        "interest_method": str(method),
        "principal_minor": PRINCIPAL,
        "term_months": MONTHS,
        "monthly_deposit_minor": MONTHLY_DEPOSIT,
    }
    interest = suggest_interest_minor(annual_rate_ppm=RATE_PPM, **kwargs)  # type: ignore[arg-type]
    assert interest is not None

    derived = derive_annual_rate_ppm(interest_minor=interest, **kwargs)  # type: ignore[arg-type]
    assert derived is not None
    assert suggest_interest_minor(annual_rate_ppm=derived, **kwargs) == interest  # type: ignore[arg-type]


def test_no_interest_derives_a_zero_rate() -> None:
    assert (
        derive_annual_rate_ppm(
            interest_method=str(InterestMethod.LUMP_SUM),
            principal_minor=PRINCIPAL,
            interest_minor=0,
            term_months=MONTHS,
        )
        == 0
    )


def test_an_impossible_interest_derives_nothing_rather_than_the_ceiling() -> None:
    """利息大到超過 100% 年利率時回 `None`，**不是回 `MAX_RATE_PPM`**。

    回上界的話畫面會印出「實際年利率 100%」，那看起來像一個結論；
    回 `None` 才表達得出「這個數字有問題，我不猜」。金額打錯一個 0 就會走到這裡。
    """
    ceiling = suggest_interest_minor(
        interest_method=str(InterestMethod.LUMP_SUM),
        principal_minor=PRINCIPAL,
        annual_rate_ppm=MAX_RATE_PPM,
        term_months=MONTHS,
    )
    assert ceiling is not None
    assert (
        derive_annual_rate_ppm(
            interest_method=str(InterestMethod.LUMP_SUM),
            principal_minor=PRINCIPAL,
            interest_minor=ceiling + 1,
            term_months=MONTHS,
        )
        is None
    )


@pytest.mark.parametrize(
    ("principal", "interest", "months", "monthly"),
    [
        (PRINCIPAL, 100, 0, None),  # 沒有月數就沒有基準
        (PRINCIPAL, 100, -1, None),
        (PRINCIPAL, -1, MONTHS, None),  # 負利息不合理
        (0, 100, MONTHS, None),  # 沒本金也沒月存，利息無所依附
        (-5, 100, MONTHS, 0),
    ],
)
def test_nonsensical_inputs_derive_nothing(
    principal: int, interest: int, months: int, monthly: int | None
) -> None:
    assert (
        derive_annual_rate_ppm(
            interest_method=str(InterestMethod.LUMP_SUM),
            principal_minor=principal,
            interest_minor=interest,
            term_months=months,
            monthly_deposit_minor=monthly,
        )
        is None
    )


def test_installment_savings_can_be_derived_without_any_principal() -> None:
    """零存整付一開始本金就是 0，所以「沒本金」不能一律當成算不出來。

    `principal <= 0 and not monthly_deposit_minor` 這個條件裡的 `and` 是關鍵 ——
    寫成 `or` 的話零存整付整種計息方式都反推不出東西。
    """
    interest = suggest_interest_minor(
        interest_method=str(InterestMethod.INSTALLMENT_SAVINGS),
        principal_minor=0,
        annual_rate_ppm=RATE_PPM,
        term_months=MONTHS,
        monthly_deposit_minor=MONTHLY_DEPOSIT,
    )
    assert interest
    assert (
        derive_annual_rate_ppm(
            interest_method=str(InterestMethod.INSTALLMENT_SAVINGS),
            principal_minor=0,
            interest_minor=interest,
            term_months=MONTHS,
            monthly_deposit_minor=MONTHLY_DEPOSIT,
        )
        is not None
    )


# --- 到期那天還剩多少利息沒領 ---------------------------------------------------


@pytest.mark.parametrize("method", [InterestMethod.LUMP_SUM, InterestMethod.INSTALLMENT_SAVINGS])
def test_maturity_interest_equals_the_whole_term_when_nothing_was_paid_out(
    method: InterestMethod,
) -> None:
    """整存整付與零存整付期間內都沒領過息，所以到期就是整期的量。"""
    assert suggest_maturity_interest_minor(
        interest_method=str(method),
        principal_minor=PRINCIPAL,
        annual_rate_ppm=RATE_PPM,
        term_months=MONTHS,
        monthly_deposit_minor=MONTHLY_DEPOSIT,
    ) == suggest_interest_minor(
        interest_method=str(method),
        principal_minor=PRINCIPAL,
        annual_rate_ppm=RATE_PPM,
        term_months=MONTHS,
        monthly_deposit_minor=MONTHLY_DEPOSIT,
    )


def test_monthly_interest_has_nothing_left_at_maturity() -> None:
    """**這一條是 v0.24.0 修掉的重複計算。**

    存本取息每個月都領息，到期日當天那一期也由 `INTEREST_PAYOUT` 事件發過了 ——
    到期只剩本金轉回。v0.24.0 之前到期事件的建議金額是 `suggest_interest_minor()`
    算出來的**整期總額**，於是照建議值確認下去，帳上的利息剛好是實際的兩倍
    （100,000 @ 1.56% 一年：12 × 130 ＝ 1,560，加上到期又一筆 1,560）。
    """
    whole_term = suggest_interest_minor(
        interest_method=str(InterestMethod.MONTHLY_INTEREST),
        principal_minor=PRINCIPAL,
        annual_rate_ppm=RATE_PPM,
        term_months=MONTHS,
    )
    assert whole_term, "整期總額是 0 的話這條測試沒有在檢查東西"
    assert (
        suggest_maturity_interest_minor(
            interest_method=str(InterestMethod.MONTHLY_INTEREST),
            principal_minor=PRINCIPAL,
            annual_rate_ppm=RATE_PPM,
            term_months=MONTHS,
        )
        == 0
    )


# --- 到期時定存帳戶裡的本金 -----------------------------------------------------


@pytest.mark.parametrize("method", [InterestMethod.LUMP_SUM, InterestMethod.MONTHLY_INTEREST])
def test_matured_principal_is_just_the_principal_for_one_shot_deposits(
    method: InterestMethod,
) -> None:
    assert (
        matured_principal_minor(
            interest_method=str(method),
            principal_minor=PRINCIPAL,
            monthly_deposit_minor=None,
            term_months=MONTHS,
        )
        == PRINCIPAL
    )


def test_installment_savings_accumulates_its_principal_from_the_monthly_deposits() -> None:
    """**這一條是 v0.24.0 修掉的另一個計算錯誤。**

    零存整付的 `principal_minor` 一開始就是 0（見
    `test_installment_savings_ignores_the_principal_entirely`），本金是每月存入
    累積出來的。v0.24.0 之前到期直接轉 `term.principal_minor` —— 於是「本金轉回」
    是一筆 **0 元**的轉帳，續存的下一期本金也是 0。
    """
    assert (
        matured_principal_minor(
            interest_method=str(InterestMethod.INSTALLMENT_SAVINGS),
            principal_minor=0,
            monthly_deposit_minor=MONTHLY_DEPOSIT,
            term_months=MONTHS,
        )
        == MONTHLY_DEPOSIT * MONTHS
    )


def test_a_principal_the_user_filled_in_beats_the_estimate() -> None:
    """中間漏存過一期時使用者可以在「修改所選期」填實際累積的本金。

    沒有這條退路的話那個估算值就是不可修正的 —— 而確認到期時只問利息，不問本金。
    """
    assert (
        matured_principal_minor(
            interest_method=str(InterestMethod.INSTALLMENT_SAVINGS),
            principal_minor=999,
            monthly_deposit_minor=MONTHLY_DEPOSIT,
            term_months=MONTHS,
        )
        == 999
    )


# --- 目前存續中的是哪一期 -------------------------------------------------------


RENEWING = str(MaturityAction.RENEW_PRINCIPAL_ONLY)


def test_current_term_rolls_forward_past_every_matured_term() -> None:
    """存單印的是**最初**那一期，而自動轉期續存的定存早就滾過好幾輪了。

    使用者的存單：112/11/15 存入、113/11/15 到期、勾「本金無限次數自動轉期續存」。
    2026-08-23 當下真正存續中的是 2025-11-15 起的那一期，**而它是第 3 期**。

    期序不是裝飾 —— 它是使用者對得回存單的東西（「這份定存滾過兩輪了」）。
    """
    assert current_term(
        opened_on="2023-11-15", term_months=12, maturity_action=RENEWING, today="2026-08-23"
    ) == ("2025-11-15", 3)


def test_current_term_leaves_a_term_that_has_not_matured_alone() -> None:
    assert current_term(
        opened_on="2026-02-15", term_months=12, maturity_action=RENEWING, today="2026-08-23"
    ) == ("2026-02-15", 1)


def test_current_term_stops_the_moment_the_maturity_is_in_the_future() -> None:
    """到期日剛好是今天算**已經到期**，跟 `generate_due()` 的界線一致。"""
    assert current_term(
        opened_on="2025-02-15", term_months=12, maturity_action=RENEWING, today="2026-02-15"
    ) == ("2026-02-15", 2)


@pytest.mark.parametrize(
    "action", [MaturityAction.NONE, MaturityAction.PRINCIPAL_INTEREST_TO_ACCOUNT]
)
def test_a_deposit_that_does_not_renew_has_no_current_term_to_roll_to(
    action: MaturityAction,
) -> None:
    """不續存的兩種到期就結束了，**沒有下一期可以滾過去**。

    替它們算一個「目前這一期」等於捏造一份不存在的定存 —— 對話框也因此不給那顆
    「改成 ⋯」的按鈕，只說「這份定存已經結束」。
    """
    assert current_term(
        opened_on="2023-11-15", term_months=12, maturity_action=str(action), today="2026-08-23"
    ) == ("2023-11-15", 1)


def test_current_term_refuses_to_loop_forever_on_a_zero_term() -> None:
    """期長 0 會讓 `add_months()` 永遠回同一天 —— 那是一個無窮迴圈。

    UI 的 spinbox 下限是 1，所以走不到；但這個函式在 domain，不能靠畫面保護。
    """
    assert current_term(
        opened_on="2020-01-01", term_months=0, maturity_action=RENEWING, today="2026-08-23"
    ) == ("2020-01-01", 1)


def test_the_month_end_clamp_does_not_creep_across_renewals() -> None:
    """1/31 起存的定存滾過幾輪之後**還是 1/31**，不會一路退到 28 號回不去。

    `add_months()` 每次都從來源日期本身算，而這裡是拿上一次的結果再加 —— 所以
    夾取有機會累積。實際上不會：一年期的每一次加法都落在同一個月日。
    """
    start, sequence = current_term(
        opened_on="2020-01-31", term_months=12, maturity_action=RENEWING, today="2026-08-23"
    )
    assert (start, sequence) == ("2026-01-31", 7)


@pytest.mark.parametrize("action", ALL_ACTIONS)
def test_renewing_forever_is_exactly_the_two_that_do_not_return_the_principal(
    action: MaturityAction,
) -> None:
    """兩個問題不同（「本金走不走」與「還會不會有下一期」），今天的答案互補。

    **這是巧合而不是定義**，所以兩個述詞都留著 —— 但互補這件事本身值得盯著：
    哪天多一種到期方式讓兩者不再互補，這條會先失敗，提醒去看每一個呼叫端。
    """
    assert renews_forever(str(action)) is not maturity_returns_principal(str(action))
