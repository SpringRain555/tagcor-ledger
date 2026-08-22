"""交易紀錄的分頁與清除篩選。

## 為什麼分開一個檔

2026-08-22 的覆蓋率掃描顯示 `ui/pages/transactions.py` 267 行裡有 112 行沒執行到，
其中包含 `next_page()`／`previous_page()`／`clear_filters()` —— **整套翻頁沒有任何
測試走過**。這一頁是「找一筆舊帳」的唯一入口，翻頁壞掉等於找不到東西。

分頁用的是 **keyset cursor** 不是 `OFFSET`，所以錯法跟一般的分頁不一樣：
游標堆疊（`self.cursors`）記的是「每一頁的起點」，往回是退堆疊而不是重算。
堆疊管理錯了會出現「下一頁跟上一頁看到同一批資料」這種很難用眼睛發現的錯。

`test_transactions_page.py` 管的是選取連動與顏色，跟這裡不重疊。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest


# 把每頁筆數調成 20（設定裡合法的三個值之一），這樣 45 筆就是**三頁**。
#
# **一定要三頁。** 只有兩頁的話「回上一頁」與「跳回第一頁」的結果完全相同 ——
# 陽性對照證實了這件事：把 `page_index -= 1` 改成 `page_index = 0`，兩頁的測試照樣全綠。
# 第三頁才分得出「退一頁」與「回第一頁」。
PAGE_SIZE = 20
ROWS = PAGE_SIZE * 2 + 5


@pytest.fixture
def filled(window: Any) -> Any:
    """塞滿三頁的交易，讓翻頁真的有東西可翻。

    **日期各不相同** —— keyset 游標是 `(occurred_at, transaction_id)`，
    全部同一天的話會退化成只靠 id 排序，測不到真正的翻頁行為。
    """
    settings = window.controller.get_settings()
    assert window.controller.save_settings(
        replace(settings, transactions_page_size=PAGE_SIZE)
    ).success

    for index in range(ROWS):
        day = 1 + index % 28
        assert window.controller.submit(
            occurred_at=f"2026-07-{day:02d}T{index % 24:02d}:00:00+08:00",
            entry_type="expense",
            amount=str(100 + index),
            account_id="acct_cash",
            destination_account_id=None,
            category_id="cat_food_711",
            description=f"第 {index} 筆",
        ).success
    window.transactions.first_page()
    return window


def _ids(page: Any) -> list[str]:
    return [str(row["transaction_id"]) for row in page.model.items]


def test_the_next_button_is_dead_until_there_is_a_next_page(window: Any) -> None:
    """只有一頁的時候「下一頁」要是停用的 —— 按了沒反應比停用更糟。"""
    page = window.transactions
    assert not page.next_button.isEnabled()
    assert not page.previous_button.isEnabled()


def test_paging_forward_shows_a_different_set_of_rows(filled: Any) -> None:
    page = filled.transactions
    assert page.model.rowCount() == PAGE_SIZE, "第一頁應該剛好滿"
    assert page.next_button.isEnabled(), "還有下一頁"
    first = _ids(page)

    page.next_page()

    assert page.previous_button.isEnabled(), "第二頁要能往回"
    second = _ids(page)
    assert second, "第二頁是空的"
    assert not set(first) & set(second), "兩頁出現同一筆交易 —— 游標算錯了"


def test_paging_back_returns_to_exactly_the_same_rows(filled: Any) -> None:
    """往回要回到**一模一樣**的那一頁，不是「重新查一次第一頁」。"""
    page = filled.transactions
    first = _ids(page)

    page.next_page()
    page.previous_page()

    assert _ids(page) == first, "回上一頁看到的不是原本那一頁"
    assert not page.previous_button.isEnabled(), "已經在第一頁了"


def test_paging_back_from_the_third_page_lands_on_the_second(filled: Any) -> None:
    """**退一頁，不是跳回第一頁。**

    只有兩頁的時候這兩種行為結果相同 —— 所以一定要走到第三頁才分得出來。
    這條是陽性對照逼出來的：把 `page_index -= 1` 改成 `page_index = 0`，
    兩頁版本的測試照樣全綠。
    """
    page = filled.transactions
    first = _ids(page)
    page.next_page()
    second = _ids(page)
    page.next_page()
    assert page.page_index == 2, "資料量不足三頁，這條測不到東西"

    page.previous_page()

    assert page.page_index == 1
    assert _ids(page) == second, "從第三頁往回跑到別頁去了"
    assert _ids(page) != first, "退一頁變成回第一頁"


def test_previous_page_on_the_first_page_does_nothing(filled: Any) -> None:
    """在第一頁按上一頁不該讓 `page_index` 變成 -1。

    負的索引在 Python 裡是合法的（會拿到最後一個游標），所以這個錯不會丟例外 ——
    它會安靜地跳到別頁。`lessons.md` 有一條「把 current row 設成 -1，等於請 Qt
    幫你選一頁」講的是同一種形狀。
    """
    page = filled.transactions
    before = _ids(page)
    page.previous_page()
    assert page.page_index == 0
    assert _ids(page) == before


def test_next_page_at_the_end_does_nothing(window: Any) -> None:
    """沒有下一頁時按下一頁不該把游標堆疊推壞。"""
    page = window.transactions
    page.next_page()
    assert page.page_index == 0
    assert page.cursors == [None]


def test_clearing_filters_resets_every_control_and_goes_back_to_page_one(
    filled: Any,
) -> None:
    """清除篩選要**同時**清掉所有欄位並回到第一頁。

    少回第一頁的話會出現「篩選清掉了，但還停在第三頁」—— 那一頁的內容跟篩選
    對不起來，看起來像資料不見了。
    """
    page = filled.transactions
    # **先翻到第二頁再設篩選。** 反過來的話篩選結果只剩一頁，`page_index` 本來就是 0，
    # 於是「有沒有回第一頁」根本測不出來 —— 陽性對照抓到過這個假綠。
    page.next_page()
    assert page.page_index == 1

    page.search.setText("第 1 筆")
    page.date_enabled.setChecked(True)
    page.status.setCurrentIndex(1)

    page.clear_filters()

    assert page.search.text() == ""
    assert not page.date_enabled.isChecked()
    assert page.account.currentIndex() == 0
    assert page.category.currentIndex() == 0
    assert page.status.currentIndex() == 0
    assert page.page_index == 0, "清除篩選之後還停在後面的頁"
    assert page.cursors == [None], "游標堆疊沒有重設"


def test_searching_then_paging_does_not_leak_the_previous_cursor(filled: Any) -> None:
    """改了篩選就要回第一頁 —— 舊游標指的是舊結果集裡的位置。

    這是 keyset 分頁特有的錯：游標是「上一批的最後一筆」，換了篩選之後那一筆
    可能根本不在新的結果裡，翻出來的東西會莫名其妙。
    """
    page = filled.transactions
    page.next_page()
    assert page.page_index == 1

    page.search.setText("第 3 筆")
    page.first_page()

    assert page.page_index == 0
    assert page.cursors == [None]
    assert page.model.rowCount() > 0, "搜尋不該把所有東西濾光"
    assert page.model.rowCount() <= PAGE_SIZE, "搜尋結果不該超過一頁"
    # **FTS 是前綴比對**：`build_fts_query()` 把「第 3 筆」拆成 `"第"* AND "3"* AND "筆"*`，
    # 所以「第 39 筆」也會中 —— 那是對的行為，不是 bug。這裡驗的是前綴語意本身。
    for row in page.model.items:
        assert str(row["description"]).startswith("第 3"), row["description"]
