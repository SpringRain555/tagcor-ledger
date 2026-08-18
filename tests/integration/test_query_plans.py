"""守門：熱查詢不得退化成全表掃描。

十年手動記帳大約 6,000–18,000 筆，**筆數本身不是風險**。風險是查詢形狀 —— 有人加一個
篩選條件、或改一下 `ORDER BY`，索引就不再適用，於是每次翻頁都全表掃一遍。那種退化不會
讓任何測試變紅，只會讓程式一年比一年慢，慢到某天使用者放棄記帳。

做法是**攔截真正被執行的 SQL**（`sqlite3.connect` 的 trace callback），再對每一句跑
`EXPLAIN QUERY PLAN`。這樣測的是實際跑的查詢，不是測試裡另外拼一份的複製品 —— 複製品
一定會跟真的那份漂移。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.domain.models import BalanceSnapshotFilter, TransactionFilter
from tagcor_ledger.domain.money import Money
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


# **允許清單，不是禁止清單。** SQLite 的計畫報的是查詢裡的別名（`SCAN t`），不是表名，
# 所以「列出會長大的表、看有沒有被掃」這種寫法抓不到任何東西 —— 這是實際注入違規時才發現
# 的：把索引拿掉之後守門照樣通過。改成「除了這幾種以外，任何 SCAN 都算違規」。
ALLOWED_SCAN_MARKERS = (
    "VIRTUAL TABLE",  # FTS5 的比對本身就是這樣呈現的
    "transaction_fts_config",  # FTS5 內部設定表，固定一列
)

# 大小不隨使用時間增長的小表，掃它們無所謂。
SMALL_FIXED_TABLES = {"settings", "schema_migrations", "sqlite_master"}


@pytest.fixture
def store(tmp_path: Path) -> LedgerStore:
    store = LedgerStore(resolve_app_paths(tmp_path / "data"))
    account_id = store.list_accounts()[0].account_id
    parent = store.list_categories()[0].category_id
    category_id = store.list_categories(parent_id=parent)[0].category_id
    for index in range(200):
        store.create_transaction(
            transaction_id=f"txn_{index:05d}",
            entry_type="expense",
            occurred_at=f"2026-{index % 12 + 1:02d}-01T12:00:00+08:00",
            money=Money(100 + index, "TWD"),
            account_id=account_id,
            category_id=category_id,
            description=f"項目 {index}",
            source="manual",
            correlation_id=f"corr_{index}",
        )
    return store


def _capture(action: Callable[[], Any]) -> list[str]:
    """回傳 `action` 期間實際執行的 SELECT 語句。"""
    statements: list[str] = []
    original = sqlite3.connect

    def traced(*args: Any, **kwargs: Any) -> Any:
        connection = original(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    sqlite3.connect = traced  # type: ignore[assignment]
    try:
        action()
    finally:
        sqlite3.connect = original  # type: ignore[assignment]
    return [
        " ".join(statement.split())
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT")
    ]


def _plans(database: Path, statements: list[str]) -> Iterator[tuple[str, list[str]]]:
    connection = sqlite3.connect(database)
    try:
        for statement in statements:
            try:
                rows = connection.execute("EXPLAIN QUERY PLAN " + statement).fetchall()
            except sqlite3.Error:
                # FTS 的內部語句不一定能單獨 explain，跳過不算違規。
                continue
            yield statement, [str(row[-1]) for row in rows]
    finally:
        connection.close()


def _full_scans(steps: list[str]) -> list[str]:
    offenders: list[str] = []
    for step in steps:
        if not step.startswith("SCAN "):
            continue
        if any(marker in step for marker in ALLOWED_SCAN_MARKERS):
            continue
        target = step.split()[1].removeprefix("main.")
        if target in SMALL_FIXED_TABLES:
            continue
        offenders.append(step)
    return offenders


def _assert_no_growing_table_scan(store: LedgerStore, action: Callable[[], Any]) -> list[str]:
    statements = _capture(action)
    assert statements, "沒有攔截到任何查詢，攔截機制可能壞了"
    all_steps: list[str] = []
    for statement, steps in _plans(store.paths.database_path, statements):
        all_steps += steps
        offenders = _full_scans(steps)
        assert not offenders, f"全表掃描：{offenders}\nSQL：{statement[:200]}"
    return all_steps


def test_capture_actually_sees_queries(store: LedgerStore) -> None:
    """陽性對照：攔截不到 SQL 的話，底下每個測試都會空過。"""
    statements = _capture(lambda: store.list_transactions(limit=50))
    assert any("FROM transactions" in statement for statement in statements)


def test_recent_transactions_uses_an_index(store: LedgerStore) -> None:
    steps = _assert_no_growing_table_scan(store, lambda: store.list_transactions(limit=50))
    assert any("idx_transactions_status_occurred" in step for step in steps), (
        "最近交易頁沒有用到 (status, occurred_at) 索引"
    )
    # keyset 分頁的意義就在於不必為了排序把資料全撈出來排。
    assert not any("USE TEMP B-TREE FOR ORDER BY" in step for step in steps), (
        "排序退化成暫存 B-tree，keyset 分頁的效果會消失"
    )


def test_account_filter_uses_the_posting_index(store: LedgerStore) -> None:
    account_id = store.list_accounts()[0].account_id
    steps = _assert_no_growing_table_scan(
        store,
        lambda: store.list_transactions(
            limit=50, transaction_filter=TransactionFilter(account_id=account_id)
        ),
    )
    assert any("idx_postings_account_transaction" in step for step in steps)


def test_date_range_filter_does_not_scan(store: LedgerStore) -> None:
    _assert_no_growing_table_scan(
        store,
        lambda: store.list_transactions(
            limit=50,
            transaction_filter=TransactionFilter(
                date_from="2026-03-01T00:00:00+08:00",
                date_to="2026-06-30T23:59:59+08:00",
            ),
        ),
    )


def test_balance_gap_queries_do_not_scan(store: LedgerStore) -> None:
    account_id = store.list_accounts()[0].account_id
    store.create_balance_snapshot(
        snapshot_id="snap_1",
        account_id=account_id,
        observed_at="2026-06-01T12:00:00+08:00",
        actual_balance_minor=1000,
        currency="TWD",
        note="",
        correlation_id="corr_snap",
    )
    _assert_no_growing_table_scan(
        store,
        lambda: store.list_balance_gaps(
            snapshot_filter=BalanceSnapshotFilter(account_id=account_id), limit=50
        ),
    )


def test_account_balance_does_not_scan(store: LedgerStore) -> None:
    account_id = store.list_accounts()[0].account_id
    _assert_no_growing_table_scan(
        store, lambda: store.account_balance_minor(account_id)
    )


def test_full_text_search_sorts_in_memory_and_that_is_accepted(store: LedgerStore) -> None:
    """**已知特性，不是缺陷。**

    FTS5 的比對結果沒有 `occurred_at` 的順序，所以 SQLite 必須自己排一次
    （`USE TEMP B-TREE FOR ORDER BY`）。排序的成本取決於**符合搜尋條件的筆數**，
    不是整個資料表的筆數，所以在單人記帳的量級可以接受。

    這個測試把現況釘住：哪天它變了（例如有人把搜尋改成先撈全表再過濾），
    這裡會失敗，而不是靜悄悄地變慢。
    """
    statements = _capture(
        lambda: store.list_transactions(
            limit=50, transaction_filter=TransactionFilter(search="項目")
        )
    )
    steps: list[str] = []
    for _statement, plan in _plans(store.paths.database_path, statements):
        steps += plan

    assert any("transaction_fts" in step or "fts" in step.lower() for step in steps), (
        "搜尋沒有走 FTS 索引"
    )
    assert not _full_scans(steps), f"搜尋掃了會長大的資料表：{_full_scans(steps)}"
