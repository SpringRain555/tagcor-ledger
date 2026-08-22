"""月份與日期運算。**純函式，只依賴標準函式庫。**

定存的每一期到期日、每一次領息，以及定期收支的下一次到期，全部建立在這幾個函式上。
2026-08-22 之前它們散在 `application/deposits.py` 與
`infrastructure/stores/automation.py` 兩邊，各自是私有函式 —— 於是
「目標月份沒有那一天要退到月底」這條規則有兩份實作，而兩份都沒有直接的單元測試。

## 月底夾取只有一份實作，但有兩個 anchor

`clamped_date()` 是唯一實作「那個月裝不下就退到當月最後一天」的地方。
v0.20.0 時 `add_months()` 與 `next_due_date()` 各有一份，當時的註解說「合併要動到
正常運作的邏輯」—— **那個判斷是錯的**。兩者的差別從來不在夾取，在**誰當 anchor**，
而那是呼叫端的事：

| 呼叫端 | anchor 是什麼 | 例子 |
|---|---|---|
| `add_months()` | 來源日期自己的日 | `add_months("2026-02-28", 1)` → `2026-03-28` |
| `next_due_date()` | 起存日的日（`anchor_day`） | 2/28 起算、anchor 31 → `2026-03-31` |

**第二種是刻意的**：少了 `anchor_day`，1/31 的月繳排程會在二月被夾成 28 之後永遠
回不到 31 號。語意差留在呼叫端，實作只留一份。

## 命名

叫 `dates.py` 不叫 `calendar.py` —— 後者與標準函式庫同名，絕對匯入雖然不會出錯，
但每個讀到 `import calendar` 的人都要停下來想一秒。
"""

from __future__ import annotations

from datetime import date, timedelta


def days_in_month(year: int, month: int) -> int:
    """那個月有幾天。12 月要跨年才算得出「下個月的第一天」，所以是特例。"""
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def clamped_date(year: int, month: int, anchor_day: int) -> date:
    """那個月裝不下 `anchor_day` 就退到當月最後一天。

    **`anchor_day` 由呼叫端決定要傳什麼** —— 那正是這個模組唯一的分歧點，見模組說明。
    """
    return date(year, month, min(anchor_day, days_in_month(year, month)))


def add_months(iso_date: str, months: int) -> str:
    """加月份。目標月份沒有那一天時退到當月最後一天（1/31 加一個月是 2/28）。

    **夾取不可累積。** 每次都從 `iso_date` 本身算，所以 1/31 加兩個月是 3/31 而不是
    3/28。呼叫端也不可以拿上一次的結果再加一個月 —— 那樣日期會一路退到 28 號回不去。
    """
    base = date.fromisoformat(iso_date)
    total = base.month - 1 + months
    year = base.year + total // 12
    month = total % 12 + 1
    return clamped_date(year, month, base.day).isoformat()


def shift_days(iso_date: str, days: int) -> str:
    return (date.fromisoformat(iso_date) + timedelta(days=days)).isoformat()


def monthly_dates(start_date: str, maturity_date: str, today: str) -> list[str]:
    """從起存日到今天（不超過到期日）之間的每月同日。

    **起存日當天不算一期** —— 那天錢才剛存進去，第一期是一個月後。
    每一期都用 `add_months(start_date, n)` 從起存日重算，所以 1/31 起存的第二期
    是 3/31，不會因為二月夾成 28 就一路留在 28。
    """
    dates: list[str] = []
    index = 1
    while True:
        due = add_months(start_date, index)
        if due > maturity_date or due > today:
            break
        dates.append(due)
        index += 1
    return dates


def next_due_date(current: date, frequency: str, interval: int, anchor_day: int) -> date:
    """定期收支的下一次到期日。

    `anchor_day` 是**起存日的日**，不是 `current` 的日 —— 差別見模組說明。
    認不出來的頻率丟碼，不猜一個日期回去。
    """
    if frequency == "daily":
        return current + timedelta(days=interval)
    if frequency == "weekly":
        return current + timedelta(weeks=interval)
    if frequency == "monthly":
        month_index = current.year * 12 + current.month - 1 + interval
        year, month_zero = divmod(month_index, 12)
        return clamped_date(year, month_zero + 1, anchor_day)
    if frequency == "yearly":
        return clamped_date(current.year + interval, current.month, anchor_day)
    raise ValueError("SCHEDULE_FREQUENCY_INVALID")
