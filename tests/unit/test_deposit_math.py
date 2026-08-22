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
    interest_goes_to_deposit_account,
    maturity_returns_principal,
    monthly_rate,
    renewed_principal_minor,
    suggest_interest_minor,
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
    """陽性對照：新增一種到期轉存方式而沒補矩陣時，這裡先失敗。

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
