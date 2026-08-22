"""SQLite 連線、migration 與預設資料建立。"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from types import TracebackType
from typing import Iterator, Literal

from tagcor_ledger.app.paths import AppPaths, ensure_directories
from tagcor_ledger.infrastructure.clock import now_iso
from tagcor_ledger.infrastructure.migrations import LATEST_SCHEMA_VERSION, apply_migrations


SCHEMA_VERSION = LATEST_SCHEMA_VERSION


class ClosingConnection(sqlite3.Connection):
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


def connect_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10.0, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


@contextmanager
def database_transaction(path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect_database(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(paths: AppPaths) -> Path:
    ensure_directories(paths)
    with database_transaction(paths.database_path) as connection:
        version = apply_migrations(connection)
        _seed_defaults(connection, version)
    return paths.database_path


def _seed_defaults(connection: sqlite3.Connection, version: int) -> None:
    timestamp = now_iso()
    connection.execute(
        """
        INSERT OR IGNORE INTO accounts(
            account_id, name, account_type, currency, opening_balance_minor,
            status, sort_order, created_at, updated_at
        ) VALUES ('acct_cash', '現金', 'cash', 'TWD', 0, 'active', 10, ?, ?)
        """,
        (timestamp, timestamp),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO categories(
            category_id, parent_id, level, name, status, sort_order, created_at, updated_at
        ) VALUES ('cat_food', NULL, 1, '伙食', 'active', 10, ?, ?)
        """,
        (timestamp, timestamp),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO categories(
            category_id, parent_id, level, name, status, sort_order, created_at, updated_at
        ) VALUES ('cat_food_711', 'cat_food', 2, '7-11', 'active', 10, ?, ?)
        """,
        (timestamp, timestamp),
    )
    defaults = {
        "timezone": "Asia/Taipei",
        "default_currency": "TWD",
        "app_data_version": str(version),
        "default_account_id": "acct_cash",
        "default_entry_type": "expense",
        "transactions_page_size": "50",
        "balance_snapshot_reminder": "true",
    }
    for key, value in defaults.items():
        connection.execute(
            "INSERT OR IGNORE INTO settings(key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, timestamp),
        )
    connection.execute(
        "UPDATE settings SET value = ?, updated_at = ? WHERE key = 'app_data_version'",
        (str(version), timestamp),
    )
