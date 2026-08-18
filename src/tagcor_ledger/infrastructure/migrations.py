"""Ordered SQLite schema migrations."""

from __future__ import annotations

from collections.abc import Callable
import sqlite3

from tagcor_ledger.infrastructure.clock import now_iso


LATEST_SCHEMA_VERSION = 6
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


def migrate_v4(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS balance_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL REFERENCES accounts(account_id),
            observed_at TEXT NOT NULL,
            actual_balance_minor INTEGER NOT NULL,
            currency TEXT NOT NULL DEFAULT 'TWD',
            status TEXT NOT NULL CHECK (status IN ('active', 'voided')),
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            correlation_id TEXT NOT NULL UNIQUE
        );
        CREATE INDEX IF NOT EXISTS idx_balance_snapshots_account_observed
        ON balance_snapshots(account_id, observed_at DESC, snapshot_id DESC);
        CREATE INDEX IF NOT EXISTS idx_balance_snapshots_status_observed
        ON balance_snapshots(status, observed_at DESC, snapshot_id DESC);
        """
    )


def migrate_v5(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE IF EXISTS transaction_fts")
    connection.execute("DROP INDEX IF EXISTS idx_transactions_payee")
    _drop_column_if_exists(connection, "transactions", "payee_id")
    _drop_column_if_exists(connection, "transactions", "payee_name_snapshot")
    _drop_column_if_exists(connection, "transaction_templates", "payee_name")
    _drop_column_if_exists(connection, "recurring_schedules", "payee_name")
    _drop_column_if_exists(connection, "scheduled_occurrences", "payee_name")
    connection.execute("DROP TABLE IF EXISTS payees")
    connection.execute(
        "DELETE FROM settings WHERE key IN ('startup_backup', 'last_startup_backup_date')"
    )
    connection.executescript(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS transaction_fts USING fts5(
            transaction_id UNINDEXED,
            description,
            category,
            account,
            tokenize='unicode61'
        );
        INSERT INTO transaction_fts(transaction_id, description, category, account)
        SELECT t.transaction_id,
               t.description,
               COALESCE(GROUP_CONCAT(DISTINCT c.name), '') || ' ' ||
               COALESCE(GROUP_CONCAT(DISTINCT pc.name), '') AS category_names,
               COALESCE(GROUP_CONCAT(DISTINCT a.name), '') AS account_names
        FROM transactions t
        LEFT JOIN category_allocations ca ON ca.transaction_id = t.transaction_id
        LEFT JOIN categories c ON c.category_id = ca.category_id
        LEFT JOIN categories pc ON pc.category_id = c.parent_id
        LEFT JOIN account_postings p ON p.transaction_id = t.transaction_id
        LEFT JOIN accounts a ON a.account_id = p.account_id
        GROUP BY t.transaction_id;
        """
    )


def _drop_column_if_exists(
    connection: sqlite3.Connection,
    table: str,
    column: str,
) -> None:
    columns = {
        str(row["name"])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column in columns:
        connection.execute(f"ALTER TABLE {table} DROP COLUMN {column}")


SCHEMA_V6 = """
CREATE TABLE IF NOT EXISTS deposit_contracts (
    contract_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(account_id),
    name TEXT NOT NULL,
    interest_method TEXT NOT NULL
        CHECK (interest_method IN ('lump_sum', 'monthly_interest', 'installment_savings')),
    maturity_action TEXT NOT NULL
        CHECK (maturity_action IN (
            'none',
            'principal_interest_to_account',
            'renew_principal_only',
            'renew_principal_and_interest'
        )),
    interest_destination_account_id TEXT REFERENCES accounts(account_id),
    term_months INTEGER NOT NULL CHECK (term_months > 0),
    status TEXT NOT NULL CHECK (status IN ('active', 'closed')),
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deposit_contracts_account
ON deposit_contracts(account_id, status);

CREATE TABLE IF NOT EXISTS deposit_terms (
    term_id TEXT PRIMARY KEY,
    contract_id TEXT NOT NULL REFERENCES deposit_contracts(contract_id),
    sequence INTEGER NOT NULL,
    start_date TEXT NOT NULL,
    maturity_date TEXT NOT NULL,
    principal_minor INTEGER NOT NULL CHECK (principal_minor >= 0),
    -- 百萬分之一為單位的整數；未知時為 NULL，此時算不出建議利息但合約照樣成立。
    annual_rate_ppm INTEGER CHECK (annual_rate_ppm IS NULL OR annual_rate_ppm >= 0),
    monthly_deposit_minor INTEGER CHECK (monthly_deposit_minor IS NULL OR monthly_deposit_minor >= 0),
    actual_interest_minor INTEGER,
    status TEXT NOT NULL
        CHECK (status IN ('active', 'matured', 'renewed', 'settled', 'terminated')),
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (contract_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_deposit_terms_status_maturity
ON deposit_terms(status, maturity_date);

CREATE TABLE IF NOT EXISTS deposit_events (
    event_id TEXT PRIMARY KEY,
    term_id TEXT NOT NULL REFERENCES deposit_terms(term_id),
    event_type TEXT NOT NULL
        CHECK (event_type IN ('interest_payout', 'installment', 'maturity')),
    due_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'confirmed', 'skipped')),
    suggested_amount_minor INTEGER,
    actual_amount_minor INTEGER,
    transaction_id TEXT REFERENCES transactions(transaction_id),
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (term_id, event_type, due_date)
);
CREATE INDEX IF NOT EXISTS idx_deposit_events_status_due
ON deposit_events(status, due_date);
"""


def migrate_v6(connection: sqlite3.Connection) -> None:
    """定存合約、期與待確認事件。

    `UNIQUE (term_id, event_type, due_date)` 是重複產生的防線 —— 「產生到期項目」
    可以按很多次，同一期同一天的同一種事件只會有一列。
    """
    connection.executescript(SCHEMA_V6)


MIGRATIONS: dict[int, Migration] = {
    1: migrate_v1,
    2: migrate_v2,
    3: migrate_v3,
    4: migrate_v4,
    5: migrate_v5,
    6: migrate_v6,
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
