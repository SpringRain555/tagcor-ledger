"""守門：ISO 日期字串上的月份運算。

這一份補的是 2026-08-22 掃出來的缺口。`add_months()` 的「目標月份沒有那一天就退到
當月最後一天」只寫在 docstring 裡，`monthly_dates()` 則是連一條測試都沒有 ——
而定存的每一期到期日、每一次領息與每一次續存都建立在這兩個函式上。

（`next_due_date()` 的月底與閏年已經有直接測試，在
`tests/integration/test_phase2_automation.py`；那一份不重複，只在這裡補它缺的
「未知頻率」與「每日」兩格。）

**M2 這幾個函式會搬到 `domain/dates.py`。** 到時候只有下面的 import 行會變 ——
那一行 diff 就是「搬移沒有改行為」的證據。
"""

from __future__ import annotations

from datetime import date

import pytest

from tagcor_ledger.domain.dates import (
    add_months,
    days_in_month,
    monthly_dates,
    next_due_date,
)


# --- 加月份 ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        ("2026-01-31", 1, "2026-02-28"),  # 2 月沒有 31 號，退到月底
        ("2028-01-31", 1, "2028-02-29"),  # 閏年退到 29 不是 28
        ("2026-01-31", 13, "2027-02-28"),  # 跨年之後照樣夾
        ("2026-12-15", 1, "2027-01-15"),  # 12 月加一個月要跨年
        ("2026-01-31", 12, "2027-01-31"),  # 整整一年回到同一天
        ("2026-01-31", 24, "2028-01-31"),
        ("2026-08-22", 0, "2026-08-22"),  # 加 0 是原地
        ("2026-03-31", -1, "2026-02-28"),  # 往回也要夾（`monthly_dates` 不用，但別人可能會）
        ("2026-05-31", 1, "2026-06-30"),  # 小月
    ],
)
def test_adding_months_clamps_to_the_end_of_the_target_month(
    start: str, months: int, expected: str
) -> None:
    assert add_months(start, months) == expected


def test_clamping_is_not_cumulative() -> None:
    """**1/31 加一個月是 2/28，但 1/31 加兩個月是 3/31，不是 3/28。**

    逐月遞推（拿上一次的結果再加一個月）會讓日期一路退到 28 號回不去 ——
    那是這種運算最典型的錯法，而它在第二期才看得出來。
    """
    assert add_months("2026-01-31", 1) == "2026-02-28"
    assert add_months("2026-01-31", 2) == "2026-03-31"
    assert add_months(add_months("2026-01-31", 1), 1) == "2026-03-28", (
        "這一行示範的正是錯法：拿夾過的結果再加，就回不到 31 號了"
    )


@pytest.mark.parametrize(
    ("year", "month", "expected"),
    [(2026, 1, 31), (2026, 2, 28), (2028, 2, 29), (2026, 4, 30), (2026, 12, 31)],
)
def test_days_in_month(year: int, month: int, expected: int) -> None:
    """12 月是特例（要跨年才算得出下個月的第一天），所以一定要有那一格。"""
    assert days_in_month(year, month) == expected


# --- 每月同日 --------------------------------------------------------------------


def test_monthly_dates_stop_at_today() -> None:
    """只產生**已經發生**的期數。到期日在未來的那幾期還不該出現在待確認裡。"""
    assert monthly_dates("2026-01-01", "2026-12-01", "2026-03-15") == [
        "2026-02-01",
        "2026-03-01",
    ]


def test_monthly_dates_stop_at_maturity_even_if_today_is_much_later() -> None:
    assert monthly_dates("2026-01-01", "2026-03-01", "2026-12-31") == [
        "2026-02-01",
        "2026-03-01",
    ]


def test_the_start_date_itself_is_not_a_payout() -> None:
    """第一期是起存日的**一個月後**，不是起存日當天 —— 那天錢才剛存進去。"""
    assert monthly_dates("2026-01-01", "2026-12-01", "2026-01-31") == []


@pytest.mark.parametrize(
    ("start", "maturity", "today"),
    [
        ("2026-01-01", "2026-12-01", "2025-01-01"),  # 今天早於起存日
        ("2026-01-01", "2026-01-01", "2026-06-01"),  # 起存即到期
    ],
)
def test_a_term_with_nothing_due_yet_produces_no_dates(
    start: str, maturity: str, today: str
) -> None:
    assert monthly_dates(start, maturity, today) == []


def test_monthly_dates_do_not_drift_off_the_month_end() -> None:
    """1/31 起存的第二期要回到 3/31，不能因為 2 月夾成 28 就一路留在 28。

    這一條與 `test_clamping_is_not_cumulative` 是同一個危險的兩個層次：
    上面驗運算本身，這裡驗**呼叫端沒有把它用成遞推**。
    """
    assert monthly_dates("2026-01-31", "2026-12-31", "2026-04-01") == [
        "2026-02-28",
        "2026-03-31",
    ]


# --- 定期收支的下一次到期 ---------------------------------------------------------


def test_daily_and_weekly_intervals_are_plain_addition() -> None:
    assert next_due_date(date(2026, 1, 1), "daily", 1, 1) == date(2026, 1, 2)
    assert next_due_date(date(2026, 1, 1), "daily", 10, 1) == date(2026, 1, 11)
    assert next_due_date(date(2026, 2, 26), "daily", 3, 26) == date(2026, 3, 1)


def test_an_unknown_frequency_is_refused_not_guessed() -> None:
    """認不出來就丟碼。靜靜回一個日期會讓壞掉的排程一直產生錯的到期日。"""
    with pytest.raises(ValueError, match="SCHEDULE_FREQUENCY_INVALID"):
        next_due_date(date(2026, 1, 1), "fortnightly", 1, 1)
