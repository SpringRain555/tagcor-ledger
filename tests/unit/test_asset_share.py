"""守門：資產占比圓環的計算規則。

**這裡完全不碰 Qt**，所以是毫秒級的。`build_shares()` 刻意與畫圖分開，就是為了讓
「負餘額怎麼算」「幾個以上要合併」這些真正會出錯的地方測得到 —— 用 UI 測試去斷言
「圓環上有幾片」只會慢，而且量到的是版面不是規則。
"""

from __future__ import annotations

from typing import Any

from tagcor_ledger.ui import colors
from tagcor_ledger.ui.widgets.asset_share import (
    MAX_SLICES,
    build_shares,
    ratio_text,
    slice_colors,
)


def account(name: str, balance_minor: int) -> dict[str, Any]:
    return {"name": name, "balance_minor": balance_minor, "status": "active"}


def test_slices_are_ordered_largest_first() -> None:
    """**由大到小**，而且色階跟著順序走 —— 最大的一片用最淺的灰。

    表格照的是使用者自訂順序，圓環照的是大小。兩者不必一致，因為圓環有自己的圖例；
    真正要避免的是「圓環的順序看不出理由」。
    """
    breakdown = build_shares(
        [account("撲滿", 250), account("郵局活儲", 1_000), account("現金", 500)]
    )

    assert [share.name for share in breakdown.shares] == ["郵局活儲", "現金", "撲滿"]
    assert [share.color for share in breakdown.shares] == list(slice_colors(3))
    assert breakdown.positive_total_minor == 1_750


def test_ratios_add_up_to_one() -> None:
    breakdown = build_shares([account("甲", 750), account("乙", 250)])

    assert [share.ratio for share in breakdown.shares] == [0.75, 0.25]
    assert sum(share.ratio for share in breakdown.shares) == 1.0


def test_a_zero_balance_account_gets_no_slice() -> None:
    """0 度的扇形畫不出來，列在圖例上也只是一行「0．0%」的空話。"""
    breakdown = build_shares([account("郵局活儲", 1_000), account("現金", 0)])

    assert [share.name for share in breakdown.shares] == ["郵局活儲"]
    assert breakdown.negative == ()


def test_a_negative_balance_is_reported_not_drawn() -> None:
    """**負餘額不進圓環**，但要交代出去。

    圓餅對負數沒有定義，取絕對值畫則會讓一個把錢吃掉的帳戶看起來像一份資產。
    所以它被撿出來給頁面寫成一句話 —— 與封存帳戶那一行同一個做法：不算進去，
    但也不默默不提。
    """
    breakdown = build_shares(
        [account("郵局活儲", 1_000), account("撲滿", 250), account("信用卡", -3_000)]
    )

    assert [share.name for share in breakdown.shares] == ["郵局活儲", "撲滿"]
    assert [item["name"] for item in breakdown.negative] == ["信用卡"]
    # **分母是正餘額合計，不是總資產（-1,750）。** 有負餘額時兩者不同，而百分比
    # 拿去乘總資產會對不起來 —— 所以頁面必須把這個數字寫出來。
    assert breakdown.positive_total_minor == 1_250
    assert breakdown.shares[0].ratio == 0.8


def test_nothing_positive_means_nothing_to_draw() -> None:
    """全新的帳本（每個帳戶都是 0）不該留一個空的圓框在畫面上。"""
    empty = build_shares([account("現金", 0)])
    all_negative = build_shares([account("信用卡", -500)])

    assert empty.shares == ()
    assert empty.positive_total_minor == 0
    assert all_negative.shares == ()
    assert [item["name"] for item in all_negative.negative] == ["信用卡"]


def test_no_accounts_at_all_is_not_a_crash() -> None:
    breakdown = build_shares([])

    assert breakdown.shares == ()
    assert breakdown.negative == ()
    assert breakdown.positive_total_minor == 0


def test_the_smallest_accounts_are_merged_into_others() -> None:
    """超過 `MAX_SLICES` 個帳戶時，最小的那些併成一片。

    上限等於色階數不是巧合 —— **再多一片就沒有分得出來的灰可以給它**。
    合併的是最小的那幾個，所以看得到的仍然是最重要的那幾筆。
    """
    accounts = [account(f"帳戶{index}", (index + 1) * 100) for index in range(MAX_SLICES + 3)]
    breakdown = build_shares(accounts)

    assert len(breakdown.shares) == MAX_SLICES
    last = breakdown.shares[-1]
    assert last.name == "其他（4 個帳戶）"
    # 併進去的是最小的四個：100 + 200 + 300 + 400。
    assert last.balance_minor == 1_000
    assert sum(share.balance_minor for share in breakdown.shares) == sum(
        item["balance_minor"] for item in accounts
    )
    assert abs(sum(share.ratio for share in breakdown.shares) - 1.0) < 1e-9


def test_exactly_the_maximum_is_not_merged() -> None:
    """**邊界的陽性對照。** 剛好 `MAX_SLICES` 個時不該冒出一片「其他（1 個帳戶）」。"""
    breakdown = build_shares(
        [account(f"帳戶{index}", (index + 1) * 100) for index in range(MAX_SLICES)]
    )

    assert len(breakdown.shares) == MAX_SLICES
    assert all("其他" not in share.name for share in breakdown.shares)


def test_few_slices_use_the_whole_gradient_not_just_the_top_of_it() -> None:
    """**片數少的時候色階要拉開**，不是拿前 N 個。

    拿前三階的話最大與第二大只差一個色階（對比 1.23），實機上看起來就是兩片一樣的
    淺灰 —— 而片數少正是使用者最想一眼比出來的時候。三片拿頭、中、尾；兩片拿最淺
    與最深。
    """
    assert slice_colors(1) == (colors.CHART_SLICES[0],)
    assert slice_colors(2) == (colors.CHART_SLICES[0], colors.CHART_SLICES[-1])
    assert slice_colors(3)[0] == colors.CHART_SLICES[0]
    assert slice_colors(3)[-1] == colors.CHART_SLICES[-1]
    assert slice_colors(MAX_SLICES) == colors.CHART_SLICES

    for count in range(1, MAX_SLICES + 1):
        picked = slice_colors(count)
        assert len(picked) == count
        assert len(set(picked)) == count, f"{count} 片時有重複的顏色：{picked}"
        assert set(picked) <= set(colors.CHART_SLICES)

    assert slice_colors(0) == ()


def test_percentages_always_have_one_decimal() -> None:
    """位數會跳的數字排成一欄時右邊對不齊，而這一欄就是拿來互相比較的。"""
    assert ratio_text(1.0) == "100.0%"
    assert ratio_text(0.5) == "50.0%"
    assert ratio_text(0.0035) == "0.4%"
