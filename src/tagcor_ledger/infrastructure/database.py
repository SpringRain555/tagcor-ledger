"""SQLite connection, schema migration, seeding, and legacy import."""

from __future__ import annotations

import csv
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Iterator
from uuid import uuid4

from tagcor_ledger.app.paths import AppPaths, ensure_directories
from tagcor_ledger.domain.money import Money


SCHEMA_VERSION = 1

SCHEMA_SQL = """
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


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def connect_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10.0)
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
        connection.executescript(SCHEMA_SQL)
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, now_iso()),
        )
        _seed_defaults(connection)
    migrate_legacy_data(paths)
    return paths.database_path


def _seed_defaults(connection: sqlite3.Connection) -> None:
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
    for key, value in (
        ("timezone", "Asia/Taipei"),
        ("default_currency", "TWD"),
        ("app_data_version", str(SCHEMA_VERSION)),
    ):
        connection.execute(
            "INSERT OR IGNORE INTO settings(key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, timestamp),
        )


def _legacy_files(paths: AppPaths) -> list[Path]:
    files = [
        paths.config_dir / "settings.json",
        paths.config_dir / "tags.json",
        paths.config_dir / "templates.json",
    ]
    if paths.ledger_dir.exists():
        files.extend(sorted(paths.ledger_dir.glob("ledger_*.csv")))
    return [path for path in files if path.is_file()]


def migrate_legacy_data(paths: AppPaths) -> dict[str, Any] | None:
    legacy_files = _legacy_files(paths)
    ledger_files = [path for path in legacy_files if path.suffix.lower() == ".csv"]
    if not ledger_files:
        return None

    fingerprint = _files_fingerprint(legacy_files)
    marker = f"legacy_import:{fingerprint}"
    with connect_database(paths.database_path) as connection:
        imported = connection.execute(
            "SELECT value FROM settings WHERE key = ?", (marker,)
        ).fetchone()
    if imported is not None:
        return {"status": "already_imported", "fingerprint": fingerprint}

    backup_dir = _backup_legacy_files(paths, legacy_files, fingerprint)
    report: dict[str, Any] = {
        "schema_version": 1,
        "fingerprint": fingerprint,
        "backup_dir": str(backup_dir),
        "imported": 0,
        "skipped": 0,
        "warnings": [],
        "created_at": now_iso(),
    }
    try:
        with database_transaction(paths.database_path) as connection:
            tags = _read_json_if_exists(paths.config_dir / "tags.json")
            tag_names = {
                str(item["tag_id"]): str(item["name"])
                for item in tags.get("tags", [])
                if isinstance(item, dict) and "tag_id" in item and "name" in item
            }
            for ledger_path in ledger_files:
                _import_ledger_file(connection, ledger_path, tag_names, report)
            connection.execute(
                "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)",
                (marker, json.dumps(report, ensure_ascii=False), now_iso()),
            )
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        _write_migration_report(paths, report)
        raise
    report["status"] = "success"
    _write_migration_report(paths, report)
    return report


def _files_fingerprint(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _backup_legacy_files(paths: AppPaths, files: list[Path], fingerprint: str) -> Path:
    backup_dir = paths.backup_dir / f"legacy-import-{datetime.now():%Y%m%d_%H%M%S}-{fingerprint[:8]}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    manifest: list[dict[str, str]] = []
    for source in files:
        relative = source.relative_to(paths.data_dir)
        target = backup_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        manifest.append({"source": relative.as_posix(), "sha256": _sha256(target)})
    (backup_dir / "backup_manifest.json").write_text(
        json.dumps({"schema_version": 1, "files": manifest}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return backup_dir


def _import_ledger_file(
    connection: sqlite3.Connection,
    ledger_path: Path,
    tag_names: dict[str, str],
    report: dict[str, Any],
) -> None:
    with ledger_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            transaction_id = str(row.get("transaction_id", "")).strip()
            if not transaction_id:
                report["warnings"].append(f"{ledger_path.name}: missing transaction_id")
                report["skipped"] += 1
                continue
            exists = connection.execute(
                "SELECT 1 FROM transactions WHERE transaction_id = ?", (transaction_id,)
            ).fetchone()
            if exists:
                report["skipped"] += 1
                continue
            _import_legacy_row(connection, row, tag_names)
            report["imported"] += 1


def _import_legacy_row(
    connection: sqlite3.Connection,
    row: dict[str, str],
    tag_names: dict[str, str],
) -> None:
    timestamp = now_iso()
    account_id = _safe_identifier("acct", row.get("l2_id", "legacy_account"))
    account_name = row.get("l2_name_snapshot") or tag_names.get(row.get("l2_id", ""), "舊帳戶")
    category_id = _safe_identifier("cat", row.get("l3_id", "legacy_category"))
    category_name = row.get("l3_name_snapshot") or tag_names.get(row.get("l3_id", ""), "未分類")
    subcategory_id = _safe_identifier("cat", row.get("l4_id", "legacy_detail"))
    subcategory_name = row.get("l4_name_snapshot") or tag_names.get(row.get("l4_id", ""), "其他")
    account_id = _ensure_account(connection, account_id, account_name, timestamp)
    category_id = _ensure_category(connection, category_id, category_name, None, 1, timestamp)
    subcategory_id = _ensure_category(
        connection,
        subcategory_id,
        subcategory_name,
        category_id,
        2,
        timestamp,
    )

    money = Money.from_decimal_string(row.get("amount", "0"), allow_zero=False)
    entry_type = row.get("entry_type", "expense")
    signed_amount = money.amount_minor if entry_type == "income" else -money.amount_minor
    correlation_id = row.get("correlation_id") or f"corr_{uuid4().hex}"
    connection.execute(
        """
        INSERT INTO transactions(
            transaction_id, revision, status, entry_type, occurred_at, recorded_at,
            updated_at, payee_name_snapshot, description, source, correlation_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, 'migration', ?)
        """,
        (
            row["transaction_id"],
            int(row.get("revision") or 1),
            row.get("status") or "active",
            entry_type,
            row["occurred_at"],
            row.get("recorded_at") or timestamp,
            row.get("updated_at") or timestamp,
            row.get("description") or "",
            correlation_id,
        ),
    )
    connection.execute(
        """
        INSERT INTO account_postings(
            posting_id, transaction_id, account_id, amount_minor, currency, sequence
        ) VALUES (?, ?, ?, ?, ?, 1)
        """,
        (f"post_{uuid4().hex}", row["transaction_id"], account_id, signed_amount, money.currency),
    )
    connection.execute(
        """
        INSERT INTO category_allocations(
            allocation_id, transaction_id, category_id, amount_minor, sequence
        ) VALUES (?, ?, ?, ?, 1)
        """,
        (f"alloc_{uuid4().hex}", row["transaction_id"], subcategory_id, money.amount_minor),
    )
    _refresh_fts(connection, row["transaction_id"])


def _safe_identifier(prefix: str, value: str) -> str:
    if value.startswith("tag_"):
        value = value[4:]
    clean = "".join(character for character in value if character.isalnum() or character == "_")
    return clean if clean.startswith(f"{prefix}_") else f"{prefix}_{clean or uuid4().hex}"


def _ensure_account(
    connection: sqlite3.Connection, account_id: str, name: str, timestamp: str
) -> str:
    existing = connection.execute(
        "SELECT account_id FROM accounts WHERE account_id = ? OR name = ? COLLATE NOCASE",
        (account_id, name),
    ).fetchone()
    if existing is not None:
        return str(existing["account_id"])
    connection.execute(
        """
        INSERT OR IGNORE INTO accounts(
            account_id, name, account_type, currency, opening_balance_minor,
            status, sort_order, created_at, updated_at
        ) VALUES (?, ?, 'cash', 'TWD', 0, 'active', 100, ?, ?)
        """,
        (account_id, name, timestamp, timestamp),
    )
    return account_id


def _ensure_category(
    connection: sqlite3.Connection,
    category_id: str,
    name: str,
    parent_id: str | None,
    level: int,
    timestamp: str,
) -> str:
    existing = connection.execute(
        """
        SELECT category_id FROM categories
        WHERE category_id = ? OR (parent_id IS ? AND name = ? COLLATE NOCASE)
        """,
        (category_id, parent_id, name),
    ).fetchone()
    if existing is not None:
        return str(existing["category_id"])
    connection.execute(
        """
        INSERT OR IGNORE INTO categories(
            category_id, parent_id, level, name, status, sort_order, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'active', 100, ?, ?)
        """,
        (category_id, parent_id, level, name, timestamp, timestamp),
    )
    return category_id


def _refresh_fts(connection: sqlite3.Connection, transaction_id: str) -> None:
    row = connection.execute(
        """
        SELECT t.transaction_id, t.payee_name_snapshot, t.description,
               COALESCE(c.name, '') AS category_name,
               COALESCE(a.name, '') AS account_name
        FROM transactions t
        LEFT JOIN category_allocations ca ON ca.transaction_id = t.transaction_id
        LEFT JOIN categories c ON c.category_id = ca.category_id
        LEFT JOIN account_postings ap ON ap.transaction_id = t.transaction_id AND ap.sequence = 1
        LEFT JOIN accounts a ON a.account_id = ap.account_id
        WHERE t.transaction_id = ?
        """,
        (transaction_id,),
    ).fetchone()
    if row is None:
        return
    connection.execute("DELETE FROM transaction_fts WHERE transaction_id = ?", (transaction_id,))
    connection.execute(
        """
        INSERT INTO transaction_fts(transaction_id, payee, description, category, account)
        VALUES (?, ?, ?, ?, ?)
        """,
        tuple(row),
    )


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _write_migration_report(paths: AppPaths, report: dict[str, Any]) -> None:
    report_path = paths.log_dir / "legacy_migration_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
