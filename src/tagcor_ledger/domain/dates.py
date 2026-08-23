"""月份與日期運算。**純函式，只依賴標準函式庫。**

定存的每一期到期日與每一次領息都建立在這幾個函式上。
2026-08-22 之前它們散在 `application/deposits.py` 與
`infrastructure/stores/automation.py` 兩邊，各自是私有函式 —— 於是
「目標月份沒有那一天要退到月底」這條規則有兩份實作，而兩份都沒有直接的單元測試。

## 月底夾取只有一份實作

`clamped_date()` 是唯一實作「那個月裝不下就退到當月最後一天」的地方。
v0.20.0 時 `add_months()` 與 `next_due_date()`（定期收支用的）各有一份，當時的註解說
「合併要動到正常運作的邏輯」—— **那個判斷是錯的**。兩者的差別從來不在夾取，
在**誰當 anchor**，而那是呼叫端的事。

**`next_due_date()` 在 v0.23.0 隨定期收支一起移除**
（[ADR-0011](../../../docs/decisions/ADR-0011-drop-recurring-schedules.md)），
所以現在只剩一個 anchor：`add_months()` 一律用來源日期自己的日
（`add_months("2026-02-28", 1)` → `2026-03-28`）。

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
