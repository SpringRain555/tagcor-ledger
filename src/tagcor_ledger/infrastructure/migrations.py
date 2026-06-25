"""Ordered SQLite schema migrations."""

from __future__ import annotations

from collections.abc import Callable
import sqlite3

from tagcor_ledger.infrastructure.clock import now_iso


LATEST_SCHEMA_VERSION = 3
Migration = Callable[[sqlite3.Connection], None]


SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE,
    account_type TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'TWD',
    opening_balance_minor INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('active', 'archived')),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_active_name
ON accounts(name) WHERE status = 'active';
CREATE TABLE IF NOT EXISTS categories (
    category_id TEXT PRIMARY KEY,
    parent_id TEXT REFERENCES categories(category_id),
    level INTEGER NOT NULL CHECK (level IN (1, 2)),
    name TEXT NOT NULL COLLATE NOCASE,
    status TEXT NOT NULL CHECK (status IN ('active', 'archived')),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((level = 1 AND parent_id IS NULL) OR (level = 2 AND parent_id IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_sibling_name
ON categories(COALESCE(parent_id, ''), name) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id, status, sort_order);
CREATE TABLE IF NOT EXISTS payees (
    payee_id TEXT PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('active', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL CHECK (status IN ('active', 'voided')),
    entry_type TEXT NOT NULL CHECK (entry_type IN ('income', 'expense', 'transfer', 'adjustment')),
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payee_id TEXT REFERENCES payees(payee_id),
    payee_name_snapshot TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    correlation_id TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_transactions_occurred
ON transactions(occurred_at DESC, transaction_id DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_status_occurred
ON transactions(status, occurred_at DESC, transaction_id DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_payee ON transactions(payee_id);
CREATE TABLE IF NOT EXISTS account_postings (
    posting_id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL REFERENCES transactions(transaction_id),
    account_id TEXT NOT NULL REFERENCES accounts(account_id),
    amount_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    UNIQUE(transaction_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_postings_account_transaction
ON account_postings(account_id, transaction_id);
CREATE TABLE IF NOT EXISTS category_allocations (
    allocation_id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL REFERENCES transactions(transaction_id),
    category_id TEXT NOT NULL REFERENCES categories(category_id),
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    sequence INTEGER NOT NULL DEFAULT 1,
    UNIQUE(transaction_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_allocations_category_transaction
ON category_allocations(category_id, transaction_id);
CREATE TABLE IF NOT EXISTS audit_events (
    audit_id TEXT PRIMARY KEY,
    occurred_at TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    result TEXT NOT NULL,
    details_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_entity
ON audit_events(entity_type, entity_id, occurred_at DESC);
CREATE VIRTUAL TABLE IF NOT EXISTS transaction_fts USING fts5(
    transaction_id UNINDEXED,
    payee,
    description,
    category,
    account,
    tokenize='unicode61'
);
"""


def migrate_v1(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_V1)


def migrate_v2(connection: sqlite3.Connection) -> None:
    columns = {
        str(row["name"])
        for row in connection.execute("PRAGMA table_info(transactions)").fetchall()
    }
    if "replaces_transaction_id" not in columns:
        connection.execute(
            "ALTER TABLE transactions ADD COLUMN replaces_transaction_id TEXT "
            "REFERENCES transactions(transaction_id)"
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_transactions_replaces "
        "ON transactions(replaces_transaction_id)"
    )


def migrate_v3(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS transaction_templates (
            template_id TEXT PRIMARY KEY,
            name TEXT NOT NULL COLLATE NOCASE,
            status TEXT NOT NULL CHECK (status IN ('active', 'archived')),
            entry_type TEXT NOT NULL CHECK (entry_type IN ('income', 'expense', 'transfer')),
            account_id TEXT NOT NULL REFERENCES accounts(account_id),
            destination_account_id TEXT REFERENCES accounts(account_id),
            category_id TEXT REFERENCES categories(category_id),
            amount_minor INTEGER,
            currency TEXT NOT NULL DEFAULT 'TWD',
            payee_name TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 100,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (
                (entry_type = 'transfer' AND destination_account_id IS NOT NULL
                 AND category_id IS NULL)
                OR
                (entry_type IN ('income', 'expense') AND destination_account_id IS NULL
                 AND category_id IS NOT NULL)
            )
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_templates_active_name
        ON transaction_templates(name) WHERE status = 'active';

        CREATE TABLE IF NOT EXISTS recurring_schedules (
            schedule_id TEXT PRIMARY KEY,
            name TEXT NOT NULL COLLATE NOCASE,
            status TEXT NOT NULL CHECK (status IN ('active', 'archived')),
            entry_type TEXT NOT NULL CHECK (entry_type IN ('income', 'expense', 'transfer')),
            account_id TEXT NOT NULL REFERENCES accounts(account_id),
            destination_account_id TEXT REFERENCES accounts(account_id),
            category_id TEXT REFERENCES categories(category_id),
            amount_minor INTEGER,
            currency TEXT NOT NULL DEFAULT 'TWD',
            payee_name TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            frequency TEXT NOT NULL CHECK (frequency IN ('daily', 'weekly', 'monthly', 'yearly')),
            interval_count INTEGER NOT NULL CHECK (interval_count >= 1),
            start_date TEXT NOT NULL,
            next_due_date TEXT NOT NULL,
            end_date TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (
                (entry_type = 'transfer' AND destination_account_id IS NOT NULL
                 AND category_id IS NULL)
                OR
                (entry_type IN ('income', 'expense') AND destination_account_id IS NULL
                 AND category_id IS NOT NULL)
            )
        );
        CREATE INDEX IF NOT EXISTS idx_schedules_due
        ON recurring_schedules(status, next_due_date);

        CREATE TABLE IF NOT EXISTS scheduled_occurrences (
            occurrence_id TEXT PRIMARY KEY,
            schedule_id TEXT NOT NULL REFERENCES recurring_schedules(schedule_id),
            due_date TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('pending', 'confirmed', 'skipped')),
            entry_type TEXT NOT NULL CHECK (entry_type IN ('income', 'expense', 'transfer')),
            account_id TEXT NOT NULL REFERENCES accounts(account_id),
            destination_account_id TEXT REFERENCES accounts(account_id),
            category_id TEXT REFERENCES categories(category_id),
            amount_minor INTEGER,
            currency TEXT NOT NULL DEFAULT 'TWD',
            payee_name TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            confirmed_transaction_id TEXT REFERENCES transactions(transaction_id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(schedule_id, due_date)
        );
        CREATE INDEX IF NOT EXISTS idx_occurrences_status_due
        ON scheduled_occurrences(status, due_date);
        """
    )


MIGRATIONS: dict[int, Migration] = {
    1: migrate_v1,
    2: migrate_v2,
    3: migrate_v3,
}


def apply_migrations(connection: sqlite3.Connection) -> int:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied = {
        int(row["version"])
        for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
    }
    if applied and max(applied) > LATEST_SCHEMA_VERSION:
        raise RuntimeError("DATABASE_SCHEMA_TOO_NEW")
    for version in range(1, LATEST_SCHEMA_VERSION + 1):
        if version in applied:
            continue
        MIGRATIONS[version](connection)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (version, now_iso()),
        )
    return LATEST_SCHEMA_VERSION
