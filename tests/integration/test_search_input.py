"""守門：使用者在搜尋框裡打得出來的任何東西都不該讓交易紀錄頁炸掉。

搜尋是**唯一一個把使用者輸入送進 SQL 語法層**的地方 —— 其他欄位都是綁定參數的值，
但 FTS5 的 `MATCH` 收的是一段查詢語言，而那段語言由 `build_fts_query()` 現組。

`tests/unit/test_fts_query.py` 驗的是那個組字串的函式；這一份驗的是**整條路徑**：
`TransactionFilter` → `list_transactions()` 的條件組裝 → FTS join → 真的 SQLite。
兩層都要，因為中間那層有一道自己的判斷（`if filters.search.strip():`），
而那道判斷擋的正是「空查詢會讓 FTS5 丟語法錯誤」。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.domain.models import TransactionFilter
from tagcor_ledger.domain.money import Money
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore

# FTS5 自己的語法字元、成對符號、以及一個刻意寫成「想跳出引號」的字串。
NASTY_INPUTS = [
    '"',
    '""',
    'a"b',
    "*",
    "-",
    "-便利",
    "^",
    "NEAR",
    "OR",
    "AND",
    "(",
    "()",
    '" OR 1=1 --',
    'x" OR t.description MATCH "y',
    "。",
    "，、！？",
    "...",
    "%",
    "_",
    "\\",
    "'",
    "早餐'",
]

# 只有空白的輸入不該走到 FTS —— 那會組出空查詢，而 `MATCH ''` 是 FTS5 的語法錯誤。
BLANK_INPUTS = ["", " ", "   ", "\t", "\n"]


@pytest.fixture()
def store(tmp_path: Path) -> LedgerStore:
    ledger = LedgerStore(resolve_app_paths(tmp_path / "ledger-data"))
    ledger.create_transaction(
        transaction_id="txn_probe",
        entry_type="expense",
        occurred_at="2026-08-22T12:00:00+08:00",
        money=Money(85),
        account_id="acct_cash",
        category_id="cat_food_711",
        description="早餐 便利商店",
        source="manual",
        correlation_id="corr_probe",
    )
    return ledger


@pytest.mark.parametrize("typed", NASTY_INPUTS)
def test_special_characters_in_the_search_box_never_break_the_query(
    store: LedgerStore, typed: str
) -> None:
    """打什麼都只能是「找不到」，不能是例外。

    `" OR 1=1 --` 與 `x" OR t.description MATCH "y` 是刻意寫成注入形狀的 ——
    它們應該被當成一串普通的詞去比對，而不是變成查詢語法的一部分。
    """
    rows, cursor = store.list_transactions(
        limit=10, transaction_filter=TransactionFilter(search=typed)
    )
    assert isinstance(rows, list)
    assert cursor is None or isinstance(cursor, tuple)


def test_an_injection_shaped_string_does_not_widen_the_result(store: LedgerStore) -> None:
    """陽性對照的另一半：注入形狀的字串不只是「不炸」，還必須**找不到東西**。

    只斷言不炸的話，一個把使用者輸入原樣拼進 SQL 的實作也會通過 —— 那種實作
    很可能讓 `" OR 1=1 --` 把整本帳都撈回來。
    """
    everything, _ = store.list_transactions(limit=10)
    assert len(everything) == 1, "樣本資料只有一筆，對照組才有意義"

    for typed in ('" OR 1=1 --', 'x" OR t.description MATCH "y', "*"):
        rows, _ = store.list_transactions(
            limit=10, transaction_filter=TransactionFilter(search=typed)
        )
        assert rows == [], f"「{typed}」不該比對到任何東西，卻撈回 {len(rows)} 筆"


@pytest.mark.parametrize("typed", BLANK_INPUTS)
def test_a_blank_search_lists_everything_instead_of_matching_nothing(
    store: LedgerStore, typed: str
) -> None:
    """空白＝沒有在搜尋，所以整份都要列出來。

    這條同時釘住 `list_transactions()` 裡那道 `if filters.search.strip():` ——
    少了它，空白輸入會組出空查詢送進 `MATCH`，FTS5 直接丟語法錯誤，
    而使用者只是把搜尋框清空而已。
    """
    rows, _ = store.list_transactions(
        limit=10, transaction_filter=TransactionFilter(search=typed)
    )
    assert len(rows) == 1


def test_search_still_finds_what_it_should(store: LedgerStore) -> None:
    """陽性對照：上面那些「找不到」要有意義，這裡得先證明搜尋真的會找到東西。

    少了它，一個永遠回空清單的實作可以讓這整個檔案變綠。
    """
    for typed in ("早餐", "便利", "早餐 便利商店", "現金", "伙食"):
        rows, _ = store.list_transactions(
            limit=10, transaction_filter=TransactionFilter(search=typed)
        )
        assert len(rows) == 1, f"「{typed}」應該要找得到那一筆"
