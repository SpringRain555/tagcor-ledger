"""為逐筆對帳保留的兩樣東西，v0.29.0（schema v15）拿掉之後就不再回來（ADR-0021）。

`EntryType.ADJUSTMENT` 與 `accounts.account_type` 從 v1 就在、從沒有人用過；REQ-0010 排在
2026-10 月底重新評估，2026-11-16 定案不做。在那之前守著它們的是 `tests/unit/test_reserved_schema.py`
（「保持沒有人用」），它的 docstring 約好兩種結論都會讓它消失 —— 這一份接手的是另一半：
**拿掉了就不要再長回來**，要回來就先寫一份 ADR 推翻 ADR-0021。
"""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.domain.models import EntryType
from tagcor_ledger.infrastructure import migrations
from tagcor_ledger.infrastructure.database import connect_database, initialize_database
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


STAMP = "2026-08-23T09:00:00+08:00"


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _build_v14_ledger(paths_root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """用**原本那幾支 migration** 照順序建一份 v14 的帳本，再放進一個帶 `account_type` 的帳戶與一筆收入。

    不手寫 v14 的 DDL：migration 是一條照順序重演的歷史，自己拼一份「v14 長這樣」的表，
    測到的是那份拼出來的東西，不是使用者手上那一份。
    """
    paths = resolve_app_paths(paths_root)
    paths.ledger_dir.mkdir(parents=True)
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "LATEST_SCHEMA_VERSION", 14)
        connection = sqlite3.connect(paths.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            assert migrations.apply_migrations(connection) == 14
            assert "account_type" in _columns(connection, "accounts")
            connection.execute(
                """
                INSERT INTO accounts(account_id, name, account_type, currency, opening_balance_minor,
                                     status, sort_order, created_at, updated_at)
                VALUES ('acct_post', '郵局', 'cash', 'TWD', 1000, 'active', 5, ?, ?)
                """,
                (STAMP, STAMP),
            )
            connection.execute(
                """
                INSERT INTO categories(category_id, parent_id, level, name, status, sort_order,
                                       created_at, updated_at)
                VALUES ('cat_income', NULL, 1, '薪資', 'active', 10, ?, ?)
                """,
                (STAMP, STAMP),
            )
            connection.execute(
                """
                INSERT INTO transactions(transaction_id, revision, status, entry_type, occurred_at,
                                         recorded_at, updated_at, description, source, correlation_id)
                VALUES ('txn_1', 1, 'active', 'income', ?, ?, ?, '', 'manual', 'corr_1')
                """,
                (STAMP, STAMP, STAMP),
            )
            connection.execute(
                "INSERT INTO account_postings(posting_id, transaction_id, account_id, amount_minor,"
                " currency, sequence) VALUES ('post_1', 'txn_1', 'acct_post', 500, 'TWD', 1)"
            )
            connection.execute(
                "INSERT INTO category_allocations(allocation_id, transaction_id, category_id,"
                " amount_minor, sequence) VALUES ('alloc_1', 'txn_1', 'cat_income', 500, 1)"
            )
            connection.commit()
        finally:
            connection.close()
    return paths_root


def test_a_v14_ledger_loses_account_type_and_keeps_everything_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _build_v14_ledger(tmp_path / "ledger-data", monkeypatch)
    paths = resolve_app_paths(root)

    initialize_database(paths)

    with connect_database(paths.database_path) as connection:
        versions = [
            int(row["version"])
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
        columns = _columns(connection, "accounts")
        account = connection.execute(
            "SELECT name, currency, opening_balance_minor, status, sort_order, created_at, updated_at"
            " FROM accounts WHERE account_id = 'acct_post'"
        ).fetchone()
        orphans = connection.execute("PRAGMA foreign_key_check").fetchall()
    assert versions == list(range(1, migrations.LATEST_SCHEMA_VERSION + 1))
    assert "account_type" not in columns
    assert tuple(account) == ("郵局", "TWD", 1000, "active", 5, STAMP, STAMP)
    assert orphans == []
    assert LedgerStore(paths).account_balances()["acct_post"] == 1500


def test_v15_reruns_safely_and_new_accounts_need_no_type(tmp_path: Path) -> None:
    """重跑 v15 不壞（欄位已經不在），而新建帳戶完全不碰那一欄 —— INSERT 寫的欄位要跟著拿掉。"""
    paths = resolve_app_paths(tmp_path / "ledger-data")
    initialize_database(paths)
    with connect_database(paths.database_path) as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 15")
    initialize_database(paths)

    store = LedgerStore(paths)
    created = store.create_account(name="現金二")
    with connect_database(paths.database_path) as connection:
        version = connection.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
        columns = _columns(connection, "accounts")
    assert int(version["v"]) == migrations.LATEST_SCHEMA_VERSION
    assert "account_type" not in columns
    assert created.account_id in {account.account_id for account in store.list_accounts()}


def test_there_are_exactly_three_entry_types() -> None:
    """收入、支出、轉帳。第四種要先有一份 ADR 推翻 ADR-0021（與 ADR-0010 對 `transfer_in`／`transfer_out` 同一條規矩）。"""
    assert {entry_type.value for entry_type in EntryType} == {"income", "expense", "transfer"}
