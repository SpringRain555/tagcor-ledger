"""依序執行的 SQLite schema migration。

**schema 變更一定要新增一版**，不可以改舊的那一版 —— 改了對已經跑過那一版的
資料庫毫無效果，而那正是使用者手上那一個。
"""

from __future__ import annotations

from collections.abc import Callable
import sqlite3

from tagcor_ledger.infrastructure.clock import now_iso


LATEST_SCHEMA_VERSION = 10
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


def migrate_v7(connection: sqlite3.Connection) -> None:
    """利率類型，以及從實際利息反推出來的實際年利率。

    **必須是新的一版，不能改 v6。** 使用者的資料庫已經跑過 v6 了，改動 v6 的內容
    對他們毫無效果 —— migration 記錄下來就不會再跑第二次。

    `ALTER TABLE ... ADD COLUMN` 在 SQLite 是常數時間操作，不會重寫整張表。
    """
    _add_column_if_missing(
        connection,
        "deposit_contracts",
        "rate_type",
        "TEXT NOT NULL DEFAULT 'fixed'",
    )
    _add_column_if_missing(
        connection,
        "deposit_terms",
        "effective_rate_ppm",
        "INTEGER",
    )


def migrate_v8(connection: sqlite3.Connection) -> None:
    """移除定期收支：`scheduled_occurrences` 與 `recurring_schedules` 兩張表。

    **理由寫在 [ADR-0011](../../../docs/decisions/ADR-0011-drop-recurring-schedules.md)。**
    一句話版本：模板能表達同一件事，而定期收支唯一多出來的「到期那天主動提醒」
    對這位使用者沒有作用 —— 他的觸發點是簡訊與存摺。

    **順序不能反。** `scheduled_occurrences.schedule_id` 有一條外鍵指向
    `recurring_schedules`，先砍母表會在 `PRAGMA foreign_keys = ON` 的連線上失敗。

    **沒有東西反過來指向這兩張表。** `confirmed_transaction_id` 是從 occurrence
    指向 `transactions` 的，所以交易本身完全不受影響 —— 失去的只有
    「這筆交易是從哪一筆定期收支來的」這條線索。

    v3 建的表在這裡被砍掉，全新的資料庫因此會經歷「建了又砍」。**那是對的**：
    migration 是一條照順序重演的歷史，不是最終 schema 的宣告。回頭去改 v3
    對已經跑過 v3 的資料庫毫無效果，而那正是使用者手上那一個。
    """
    connection.executescript(
        """
        DROP TABLE IF EXISTS scheduled_occurrences;
        DROP TABLE IF EXISTS recurring_schedules;
        """
    )


def migrate_v9(connection: sqlite3.Connection) -> None:
    """`deposit_contracts.recorded_on`：把這份合約記進帳本的那一天。

    **這是產生待確認項目的下界**，見
    [ADR-0012](../../../docs/decisions/ADR-0012-deposit-events-start-at-record-date.md)。
    既有定存本來就比開始記帳早，而那段期間的利息已經含在帳戶的期初餘額裡 ——
    v0.24.0 之前一份 2025-02-15 起存的存本取息在 2026-08 記進來，會一次倒 13 筆
    日期全在過去的項目進待確認。

    **為什麼不直接讀 `created_at`。** 讀得到，第一版也真的是這樣寫的 —— 但那是一個
    技術性的稽核時間戳，而這裡要的是一條**業務規則**。兩件事綁在同一欄的代價立刻
    就出現了：`generate_due(today=...)` 特意讓測試控制「今天」，而下界卻黏在真實
    的牆上時鐘，於是十幾條原本有意義的測試同時變成「什麼都沒產生也算通過」。
    分成兩欄之後兩者都能各自被設定。

    既有的合約用 `created_at` 的日期部分回填 —— 那是當時唯一存在的事實，
    而且對這位使用者來說兩者本來就相同（他的合約都是在同一台機器上建的）。
    """
    _add_column_if_missing(
        connection,
        "deposit_contracts",
        "recorded_on",
        "TEXT NOT NULL DEFAULT ''",
    )
    connection.execute(
        "UPDATE deposit_contracts SET recorded_on = substr(created_at, 1, 10) "
        "WHERE recorded_on = ''"
    )


def migrate_v10(connection: sqlite3.Connection) -> None:
    """`deposit_contracts.opened_on`：存單上首次存入的那一天。

    v9 的 `recorded_on` 解決了「不要替我補歷史」，但沒有解決「我想記錄的那個日期
    放哪裡」。使用者手上的存單印的是 112/11/15，而目前存續中的是 114/11/15 那一期
    —— 在這一欄出現之前，對話框那個「起存日」的正確值**不是他手上那張紙印的數字**，
    旁邊還得放一段字解釋為什麼。那是設計沒對齊。

    現在填的就是紙上那個數字，該滾到哪一期由 `domain.deposits.current_term()` 算，
    而它同時算出**期序** —— 上面那個例子是第 3 期，不是第 1 期。

    既有合約用它**第一期的起存日**回填：那是當時唯一存在的事實，而且對於在這一版
    之前建檔的合約，兩者本來就相同（沒有滾期這回事，因為那時候填進去的就是一期）。

    **不合併進 v9。** v9 已經寫好，而 migration 是一條照順序重演的歷史 ——
    只要有任何一個資料庫跑過 v9，回頭改它就是無效的，而「有沒有跑過」不該靠記憶判斷。
    多一次 `ALTER TABLE ADD COLUMN` 在 SQLite 是常數時間，代價遠低於猜錯。
    """
    _add_column_if_missing(
        connection,
        "deposit_contracts",
        "opened_on",
        "TEXT NOT NULL DEFAULT ''",
    )
    connection.execute(
        """
        UPDATE deposit_contracts
        SET opened_on = COALESCE(
            (
                SELECT start_date FROM deposit_terms
                WHERE deposit_terms.contract_id = deposit_contracts.contract_id
                ORDER BY sequence
                LIMIT 1
            ),
            ''
        )
        WHERE opened_on = ''
        """
    )


def _add_column_if_missing(
    connection: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    existing = {
        str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})")
    }
    if column not in existing:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


MIGRATIONS: dict[int, Migration] = {
    1: migrate_v1,
    2: migrate_v2,
    3: migrate_v3,
    4: migrate_v4,
    5: migrate_v5,
    6: migrate_v6,
    7: migrate_v7,
    8: migrate_v8,
    9: migrate_v9,
    10: migrate_v10,
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
