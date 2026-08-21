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
#
# `accounts` 是照「記帳越久會不會變多」判定的：它的筆數等於你有幾個銀行帳戶，
# 是 O(10) 而且**跟記了幾年沒有關係**。列出所有帳戶餘額本來就得走過每一列
# （`list_accounts` 也一樣），所以那個 SCAN 不是退化。
# 真正要守的是它 JOIN 過去的 `account_postings` 與 `transactions` —— 那兩張會長大。
SMALL_FIXED_TABLES = {
    "settings",
    "schema_migrations",
    "sqlite_master",
    "accounts",
    # `categories` 跟 `accounts` 同一個理由：它的筆數等於你**建了幾個類別與項目**，
    # 是 O(100)，而且**跟記了幾年沒有關係**。名冊分頁的搜尋、狀態與排序都下推到 SQL
    # （2026-08-21），那句查詢會 SCAN `categories` 兩次（本體與 parent 的 LEFT JOIN）
    # 加一個算子項目數的相關子查詢 —— 在這個量級上那不是退化。
    #
    # **會長大的是 `category_allocations`**（每筆交易一列），而那張表不在這句查詢裡。
    "categories",
    # 類別樹要 self-join（本體 ＋ 上層 ＋ 算子項目數的子查詢），所以**非用別名不可**，
    # 而 `EXPLAIN QUERY PLAN` 報的是別名不是表名（見本檔開頭與 data-model.md）。
    # 別名刻意取成帶表名的 `category_*`，這幾條白名單才說得出自己在放行什麼 ——
    # 叫 `node` / `parent` / `item` 的話，日後任何一句查詢隨手用同一個別名就被放行了。
    "category_node",
    "category_parent",
    "category_item",
}


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


def test_all_account_balances_do_not_scan_the_growing_tables(store: LedgerStore) -> None:
    """一次算完所有帳戶時，交易與分錄仍然要走索引。

    這一句是資產總覽的地基（開啟程式第一眼就跑它）。天真的寫法是拿掉 `WHERE` 之後
    順手把 JOIN 也改成子查詢或 `IN`，那會變成每算一個帳戶就掃一次 `account_postings`。
    """
    steps = _assert_no_growing_table_scan(store, store.account_balances)
    assert any("idx_postings_account_transaction" in step for step in steps), (
        "餘額彙總沒有用到 (account_id, transaction_id) 索引"
    )
    # 計畫必須認得出表名。這句刻意不用別名，否則 `SCAN accounts` 會變成 `SCAN a`，
    # 上面那圈就什麼都判斷不了（見 `ALLOWED_SCAN_MARKERS` 的說明）。
    assert any(step.startswith("SCAN accounts") for step in steps), (
        "計畫裡看不到 accounts —— 多半是有人在 SQL 裡加了表格別名"
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


def test_category_tree_filter_and_sort_run_in_sql(store: LedgerStore) -> None:
    """名冊分頁的搜尋、狀態、所屬類別與排序**都要在 SQL 裡**，而且不得掃到會長大的表。

    `categories` 本身被掃是接受的（見 `SMALL_FIXED_TABLES` 的說明）—— 這一條真正
    要守的是「有人日後為了做搜尋而 JOIN 進 `category_allocations` 或 `transactions`」。

    順便當成 `CATEGORY_SORT_KEYS` 的煙霧測試：每一個 key 都要能真的組出一句合法 SQL。
    """
    from tagcor_ledger.domain.models import CategoryTreeFilter
    from tagcor_ledger.infrastructure.stores.categories import CATEGORY_SORT_KEYS

    checked = 0
    for sort_key in CATEGORY_SORT_KEYS:
        for descending in (False, True):
            tree_filter = CategoryTreeFilter(
                level=2,
                search="7",
                status="active",
                sort_key=sort_key,
                descending=descending,
            )
            _assert_no_growing_table_scan(
                store, lambda f=tree_filter: store.list_category_tree(tree_filter=f)
            )
            checked += 1
    assert checked == len(CATEGORY_SORT_KEYS) * 2, checked


def test_an_unknown_sort_key_falls_back_instead_of_reaching_sql(store: LedgerStore) -> None:
    """**`sort_key` 只能是白名單裡的值。** 未知的值退回預設，不是拼進 `ORDER BY`。

    那是唯一一個把字串拼進 SQL 的地方，所以它必須是封閉的清單 —— 這條測試就是
    在證明「畫面送什麼進來都不會變成 SQL 片段」。
    """
    from tagcor_ledger.domain.models import CategoryTreeFilter

    injected = CategoryTreeFilter(sort_key="node.name; DROP TABLE categories")
    rows = store.list_category_tree(tree_filter=injected)
    assert rows, "退回預設排序之後應該照樣列得出東西"
    # 表還在，而且內容沒變。
    assert store.list_categories(), "categories 被動到了"
