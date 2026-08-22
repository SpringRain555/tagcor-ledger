"""`derive_annual_rate_ppm()` 的成本上界。

## 為什麼是「量出來然後設上界」，不是「把它改快」

`derive_annual_rate_ppm()` 拿 `suggest_interest_minor()` 做二分搜尋，
最多 20 次正推。零存整付的正推是 `O(term_months)` 次 `Decimal` 冪運算，
所以 240 期的合約反推一次約 4,800 次冪運算 —— 帳面上很嚇人。

**實測（2026-08-22，本機 20 次平均）：**

| 計息方式 | 12 期 | 60 期 | 240 期 |
|---|---|---|---|
| 整存整付 | 0.047 ms | 0.048 ms | 0.046 ms |
| 存本取息 | 0.033 ms | 0.034 ms | 0.031 ms |
| **零存整付** | 0.167 ms | 0.844 ms | **3.832 ms** |

**最壞 3.8 毫秒，而且只發生在使用者按下「用實際利息反推利率」的當下。**

迭代乘法或等比級數封閉解都能把它砍成 1/240，但 `Decimal` 的 `**` 是照 context
精度正確捨入的，換成累乘會累積誤差。**為了省 3.8 毫秒去動利息的進位，是拿正確性
換一個沒有人感受得到的數字。**

所以這條測試不是在追求快，是在**釘住現在這個量級**：以後有人把它改慢一百倍
（例如把二分搜尋換成線性掃描）會被抓到，而在那之前這件事就此關閉。

上界抓 50 ms —— 比實測的 3.8 ms 寬十倍以上，因為 CI 機器與本機的差距、
以及 `Decimal` 在不同平台的實作差異都不該讓這條變成間歇性失敗的測試。
"""

from __future__ import annotations

import os
from time import perf_counter

import pytest

from tagcor_ledger.domain.deposits import InterestMethod, derive_annual_rate_ppm

# 最貴的組合：零存整付 ＋ 20 年。郵局定存最長就是這個量級。
WORST_CASE_MONTHS = 240
BUDGET_SECONDS = 0.050


@pytest.mark.performance
@pytest.mark.skipif(
    os.environ.get("TAGCOR_RUN_PERFORMANCE") != "1",
    reason="Set TAGCOR_RUN_PERFORMANCE=1 to run the timing benchmark.",
)
def test_deriving_a_rate_stays_well_under_a_frame() -> None:
    started = perf_counter()
    ppm = derive_annual_rate_ppm(
        interest_method=str(InterestMethod.INSTALLMENT_SAVINGS),
        principal_minor=0,
        interest_minor=15_000,
        term_months=WORST_CASE_MONTHS,
        monthly_deposit_minor=5_000,
    )
    elapsed = perf_counter() - started

    assert ppm is not None, "這組參數應該推得出利率，推不出來就不是在測效能了"
    assert elapsed < BUDGET_SECONDS, (
        f"{WORST_CASE_MONTHS} 期零存整付反推花了 {elapsed * 1000:.1f} ms，"
        f"超過 {BUDGET_SECONDS * 1000:.0f} ms 的上界。"
        "2026-08-22 的實測是 3.8 ms —— 慢十倍以上表示演算法被改過了。"
    )
