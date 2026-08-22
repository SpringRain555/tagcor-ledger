"""守門：`ui/formatting.py` 的顯示規則。

這一份補的是 2026-08-22 掃出來的缺口。`ui/formatting.py` 有 438 行純函式而
**一條單元測試都沒有** —— 它的行為只被慢的 UI 測試間接碰到，而那些測試斷言的是
「表格上有沒有這個字」，不是「這個函式對這個輸入回什麼」。

覆蓋率掃描指出得更明確：`schedule_values()`、`occurrence_values()` 與
`deposit_event_values()` **從頭到尾一行都沒有執行過**，所有壞輸入的退路
（`display_date` 認不出來的字串、`_time_from_backup_id` 認不出來的資料夾名）也是。

**這裡是純字串轉換，不碰 Qt 也不碰資料庫**，所以是毫秒級的。
"""

from __future__ import annotations

from typing import Any

import pytest

from tagcor_ledger.ui.formatting import (
    backup_row_text,
    backup_state_text,
    deposit_event_values,
    deposit_term_values,
    display_date,
    display_datetime,
    group_digits,
    inbox_values,
    minor_text,
    occurrence_values,
    rate_text,
    schedule_values,
    signed_amount_text,
    template_values,
)
from tagcor_ledger.ui.formatting import _time_from_backup_id


# --- 金額 ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1200, "1,200"),
        (-1200, "-1,200"),
        ("1200", "1,200"),
        ("+1200", "+1,200"),
        ("0", "0"),
        ("1234567", "1,234,567"),
        ("  1200  ", "1,200"),  # 前後空白要吃掉
        ("12.5", "12.5"),  # 小數部分原樣保留，不做四捨五入
        ("-12.5", "-12.5"),
    ],
)
def test_grouping_digits(value: object, expected: str) -> None:
    assert group_digits(value) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["abc", "", "-", "+", "  ", "1,200"])
def test_grouping_something_that_is_not_a_number_returns_it_untouched(value: str) -> None:
    """認不出來就原樣回傳，**不要丟例外** —— 這是顯示層，炸掉會讓整張表畫不出來。

    空字串曾經是個 `IndexError`：`text[:1] in "+-"` 是**子字串**判斷，而空字串是任何
    字串的子字串，於是空輸入會進到「有正負號」那個分支再對空字串取 `[0]`。
    """
    assert group_digits(value) == value


@pytest.mark.parametrize(
    ("entry_type", "amount", "expected"),
    [
        ("expense", "85", "-85"),
        ("income", "85", "+85"),
        ("transfer", "85", "85"),  # 轉帳既不是收入也不是支出，不加號
        ("expense", "-85", "-85"),  # 已經帶號的不重複加
        ("income", "+85", "+85"),
        ("", "85", "85"),  # 認不出流向就不表態
    ],
)
def test_signing_an_amount(entry_type: str, amount: str, expected: str) -> None:
    assert signed_amount_text({"amount": amount, "entry_type": entry_type}) == expected


def test_input_boxes_get_plain_digits_without_separators() -> None:
    """`minor_text()` 的輸出會被讀回來再解析，所以**不能**有千分位。"""
    assert minor_text(1200) == "1200"
    assert minor_text("1200") == "1200"
    assert minor_text(-5) == "-5"


def test_the_two_amount_formatters_are_not_interchangeable() -> None:
    """把 `group_digits()` 的輸出塞進輸入框就解析不回來了 —— 這是它們分家的理由。"""
    assert group_digits(1200) != minor_text(1200)


@pytest.mark.parametrize(
    ("ppm", "expected"),
    [
        (None, "未填"),  # 機動利率還沒填，不是 0%
        (0, "0%"),
        (16_000, "1.6%"),
        (12_000, "1.2%"),
        (1_595, "0.1595%"),  # 牌告利率有到小數點後三、四位
        (5, "0.0005%"),
        (1_000_000, "100%"),
    ],
)
def test_rendering_an_annual_rate(ppm: int | None, expected: str) -> None:
    assert rate_text(ppm) == expected


# --- 日期 ------------------------------------------------------------------------


def test_dates_show_the_day_only_and_datetimes_show_the_minute() -> None:
    """交易的時分秒是程式補的排序值，不是使用者輸入的，所以不印。

    備份剛好相反 —— 同一天可以有好幾份，只印日期就分不出哪一份是哪一份。
    """
    stamp = "2026-08-22T12:34:56+08:00"
    assert display_date(stamp) == "2026/08/22"
    assert display_datetime(stamp) == "2026/08/22 12:34"


@pytest.mark.parametrize("value", ["not-a-date", "", "2026-13-45"])
def test_an_unparseable_timestamp_is_shown_as_it_is(value: str) -> None:
    assert display_date(value) == value
    assert display_datetime(value) == value


def test_a_backup_folder_name_carries_its_own_timestamp() -> None:
    """清單檔壞掉時，時間欄靠資料夾名字撐住 —— 而那正是要挑哪一份刪掉的時刻。"""
    assert _time_from_backup_id("backup_20260821_204129_147229") == "2026/08/21 20:41"


@pytest.mark.parametrize("name", ["backup_bad_stuff", "plain", "backup_20260821", ""])
def test_a_folder_name_that_is_not_a_backup_id_is_shown_as_it_is(name: str) -> None:
    assert _time_from_backup_id(name) == name


# --- 備份清單 --------------------------------------------------------------------


def test_a_broken_backup_says_what_is_wrong_in_chinese() -> None:
    """以前這一欄印的是 `無效：BACKUP_CHECKSUM_MISMATCH` —— 一整排英文碼。"""
    assert backup_state_text(True, None) == "可用"
    assert backup_state_text(False, "BACKUP_CHECKSUM_MISMATCH") == "不可用（內容被改過）"


@pytest.mark.parametrize(("code", "shown"), [("WAT", "WAT"), (None, "原因不明"), ("", "原因不明")])
def test_an_unrecognised_backup_error_still_says_something(code: str | None, shown: str) -> None:
    assert backup_state_text(False, code) == f"不可用（{shown}）"


def test_a_backup_row_falls_back_to_the_folder_name_for_its_time() -> None:
    """`created_at` 空白的那幾列正是壞掉的那幾列，而它們最需要時間。"""
    row = backup_row_text(
        {
            "path": r"D:\data\backups\backup_20260821_204129_147229",
            "created_at": "",
            "valid": False,
            "error_code": "BACKUP_MANIFEST_INVALID",
        }
    )
    assert row.startswith("2026/08/21 20:41｜不可用（清單檔壞掉）｜")
    assert row.endswith("backup_20260821_204129_147229")
    assert "D:" not in row, "完整路徑會把清單撐出一條橫向捲軸，它該待在 tooltip"


# --- 每一列 ----------------------------------------------------------------------


def test_a_template_without_an_amount_says_so_instead_of_showing_zero() -> None:
    with_amount = template_values(
        {"name": "早餐", "entry_type": "expense", "amount_minor": 85, "description": "x"}
    )
    without = template_values(
        {"name": "加油", "entry_type": "expense", "amount_minor": None, "description": ""}
    )
    assert with_amount == ["早餐", "支出", "85", "x"]
    assert without[2] == "套用時輸入"


def test_a_schedule_row_reads_as_a_sentence() -> None:
    """「每 2 月」而不是 `monthly` / `2`，而且沒有結束日要寫「無」不是空白。"""
    assert schedule_values(
        {
            "name": "房租",
            "entry_type": "expense",
            "interval_count": 2,
            "frequency": "monthly",
            "next_due_date": "2026-09-01",
            "end_date": None,
        }
    ) == ["房租", "支出", "每 2 月", "2026-09-01", "無"]


def test_an_occurrence_without_an_amount_says_it_is_not_filled_in_yet() -> None:
    pending = occurrence_values(
        {
            "due_date": "2026-09-01",
            "schedule_name": "房租",
            "entry_type": "expense",
            "amount_minor": None,
            "invalid_reason": None,
        }
    )
    assert pending == ["2026-09-01", "房租", "支出", "尚未填寫", "可確認"]

    blocked = occurrence_values(
        {
            "due_date": "2026-09-01",
            "schedule_name": "房租",
            "entry_type": "expense",
            "amount_minor": 12_000,
            "invalid_reason": "類別已封存",
        }
    )
    assert blocked[3] == "12,000"
    assert blocked[4] == "類別已封存"


def test_a_deposit_event_without_a_suggestion_points_at_the_passbook() -> None:
    """**不是印 0。** 建議值是程式試算的，權威值在存摺上；0 會被當成答案。"""
    unknown = deposit_event_values(
        {
            "due_date": "2026-09-01",
            "contract_name": "郵局一年期",
            "event_type": "maturity",
            "suggested_amount_minor": None,
        }
    )
    assert unknown == ["2026-09-01", "郵局一年期", "到期", "需照存摺填寫"]

    known = deposit_event_values(
        {
            "due_date": "2026-09-01",
            "contract_name": "郵局一年期",
            "event_type": "interest_payout",
            "suggested_amount_minor": 1_000,
        }
    )
    assert known[2] == "領息"
    assert known[3] == "1,000"


def test_a_deposit_term_prefers_the_rate_derived_from_what_actually_happened() -> None:
    """事前填的牌告利率只是預期值，反推出來的才是事實 —— 機動利率更是連填都不該填。"""
    term: dict[str, Any] = {
        "sequence": 2,
        "start_date": "2026-01-01",
        "maturity_date": "2027-01-01",
        "principal_minor": 1_000_000,
        "annual_rate_ppm": 16_000,
        "actual_interest_minor": 12_066,
        "status": "settled",
        "effective_rate_ppm": 12_000,
    }
    values = deposit_term_values(term)
    assert values[4] == "1.2%（實際）", "有實際利率就不該顯示事前填的 1.6%"

    term["effective_rate_ppm"] = None
    term["actual_interest_minor"] = None
    fallback = deposit_term_values(term)
    assert fallback[4] == "1.6%"
    assert fallback[5] == "尚未確認"


@pytest.mark.parametrize(
    ("source", "row", "expected_source", "expected_amount"),
    [
        (
            "schedule",
            {
                "due_date": "2026-09-01T00:00:00+08:00",
                "schedule_name": "房租",
                "entry_type": "expense",
                "amount_minor": 12_000,
                "invalid_reason": None,
            },
            "定期",
            "12,000",
        ),
        (
            "deposit",
            {
                "due_date": "2026-09-01T00:00:00+08:00",
                "contract_name": "郵局一年期",
                "event_type": "maturity",
                "suggested_amount_minor": None,
            },
            "定存",
            "需照存摺填寫",
        ),
    ],
)
def test_the_inbox_puts_two_different_shapes_into_one_table(
    source: str, row: dict[str, Any], expected_source: str, expected_amount: str
) -> None:
    """待確認是**一張表**，兩種來源靠「來源」欄分辨 —— 沒有那一欄就看不懂「類型」在講什麼。"""
    values = inbox_values(dict(row, source=source))
    assert len(values) == 6
    assert values[0] == "2026/09/01"
    assert values[1] == expected_source
    assert values[4] == expected_amount
