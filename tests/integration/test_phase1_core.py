from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.application.catalogs import AccountService, CategoryService
from tagcor_ledger.application.settings import SettingsService
from tagcor_ledger.application.transaction_service import (
    AddTransaction,
    AddTransactionRequest,
    AddTransfer,
    AddTransferRequest,
    ReplaceTransfer,
    ReplaceTransferRequest,
)
from tagcor_ledger.domain.models import ApplicationSettings, TransactionFilter
from tagcor_ledger.infrastructure.database import connect_database, initialize_database
from tagcor_ledger.infrastructure.maintenance import MaintenanceService
from tagcor_ledger.infrastructure.migrations import LATEST_SCHEMA_VERSION, migrate_v1
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


def test_schema_v1_migrates_to_latest_and_reruns_safely(tmp_path: Path) -> None:
    """名稱不綁版本號 —— 每加一次 migration 就要改一次測試名稱是沒有意義的維護成本。"""
    paths = resolve_app_paths(tmp_path / "ledger")
    paths.ledger_dir.mkdir(parents=True)
    with sqlite3.connect(paths.database_path) as connection:
        connection.row_factory = sqlite3.Row
        migrate_v1(connection)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (1, '2026-01-01')"
        )
        connection.commit()

    initialize_database(paths)
    initialize_database(paths)

    with connect_database(paths.database_path) as connection:
        versions = [
            int(row["version"])
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        transaction_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(transactions)")
        }
        balance_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(balance_snapshots)")
        }
        payees_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'payees'"
        ).fetchone()
        fts_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(transaction_fts)")
        }
    assert versions == list(range(1, LATEST_SCHEMA_VERSION + 1))
    assert "replaces_transaction_id" in transaction_columns
    assert "actual_balance_minor" in balance_columns
    assert "payee_id" not in transaction_columns
    assert "payee_name_snapshot" not in transaction_columns
    assert payees_table is None
    assert "payee" not in fts_columns


# 電子票證（悠遊卡／一卡通／iCash）**只記儲值當下的支出**，不建帳戶、不追蹤卡內餘額。
# 決定與理由見 ADR-0006，硬規則寫在 `AGENTS.md`。
#
# 為什麼要一條測試而不是只寫在文件裡：市面產品幾乎都做「卡片歸戶」（CWMoney 的主打功能
# 逐字就是「歸戶悠遊卡、一卡通、iCash」），所以這是最容易被人順手加回來的一條。
# 而且它不會以一個功能的形式出現，會先以**一個欄位**的形式出現。
STORED_VALUE_TOKENS = (
    "stored_value",
    "prepaid",
    "card_balance",
    "easycard",
    "ipass",
    "icash",
    "ticket",
)


def test_schema_never_grows_a_stored_value_card_concept(tmp_path: Path) -> None:
    """守的是 **schema**，不是使用者怎麼命名。

    使用者要把帳戶取名叫「悠遊卡」，程式攔不住也不該攔 —— 帳戶名是使用者的資料。
    能機械檢查的是「資料庫裡有沒有長出卡內餘額這個概念」，那才是設計決定。
    """
    paths = resolve_app_paths(tmp_path / "ledger")
    paths.ledger_dir.mkdir(parents=True)
    initialize_database(paths)

    scanned: list[str] = []
    with connect_database(paths.database_path) as connection:
        objects = [
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            )
        ]
        scanned.extend(objects)
        tables = [
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for table in tables:
            scanned.extend(
                f"{table}.{row['name']}"
                for row in connection.execute(f"PRAGMA table_info({table})")
            )

    # 陽性對照：掃描壞掉時這裡先失敗，而不是讓底下的斷言在空清單上靜默通過。
    assert len(scanned) > 150, "schema 掃描沒抓到東西，守門等於沒作用"

    offenders = [
        name for name in scanned if any(token in name.lower() for token in STORED_VALUE_TOKENS)
    ]
    assert not offenders, (
        "電子票證只記儲值當下的支出，schema 不得出現卡內餘額概念（見 ADR-0006）：" f"{offenders}"
    )


def test_replace_transfer_is_atomic_and_links_old_transaction(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger")
    store = LedgerStore(paths)
    account_result = AccountService(paths, store).create(name="銀行", opening_balance="1000")
    bank_id = str(account_result.details["account_id"])
    created = AddTransfer(paths, store).execute(
        AddTransferRequest(
            occurred_at="2026-06-01T10:00:00+08:00",
            amount="100",
            source_account_id=bank_id,
            destination_account_id="acct_cash",
        )
    )
    original_id = str(created.details["transaction"]["transaction_id"])

    failed = ReplaceTransfer(paths, store).execute(
        ReplaceTransferRequest(
            original_transaction_id=original_id,
            occurred_at="2026-06-02T10:00:00+08:00",
            amount="200",
            source_account_id=bank_id,
            destination_account_id="missing",
        )
    )
    assert not failed.success
    assert store.get_transaction(original_id).status == "active"

    replaced = ReplaceTransfer(paths, store).execute(
        ReplaceTransferRequest(
            original_transaction_id=original_id,
            occurred_at="2026-06-02T10:00:00+08:00",
            amount="200",
            source_account_id=bank_id,
            destination_account_id="acct_cash",
        )
    )
    assert replaced.success
    replacement = replaced.details["transaction"]
    assert replacement["replaces_transaction_id"] == original_id
    assert store.get_transaction(original_id).status == "voided"
    assert store.account_balance_minor(bank_id) == 800
    assert store.account_balance_minor("acct_cash") == 200


def test_combined_filters_and_bidirectional_keyset_paging(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger")
    store = LedgerStore(paths)
    add = AddTransaction(paths, store)
    for day in range(1, 6):
        result = add.execute(
            AddTransactionRequest(
                occurred_at=f"2026-06-0{day}T10:00:00+08:00",
                entry_type="expense",
                amount=str(day),
                description="通勤捷運",
            )
        )
        assert result.success

    filters = TransactionFilter(
        search="通勤",
        date_from="2026-06-01T00:00:00+08:00",
        date_to="2026-06-05T23:59:59+08:00",
        account_id="acct_cash",
        category_id="cat_food",
        status="active",
    )
    first, next_cursor = store.list_transactions(limit=2, transaction_filter=filters)
    assert [item.occurred_at[8:10] for item in first] == ["05", "04"]
    assert next_cursor is not None
    second, _ = store.list_transactions(
        limit=2,
        cursor=next_cursor,
        transaction_filter=filters,
    )
    assert [item.occurred_at[8:10] for item in second] == ["03", "02"]
    previous, _ = store.list_transactions(
        limit=2,
        cursor=(second[0].occurred_at, second[0].transaction_id),
        cursor_direction="previous",
        transaction_filter=filters,
    )
    assert [item.transaction_id for item in previous] == [
        item.transaction_id for item in first
    ]


def test_archived_accounts_and_categories_can_be_restored_with_clear_rules(
    tmp_path: Path,
) -> None:
    paths = resolve_app_paths(tmp_path / "ledger")
    store = LedgerStore(paths)
    accounts = AccountService(paths, store)
    first = str(accounts.create(name="測試帳戶").details["account_id"])
    assert accounts.archive(first).success
    second = str(accounts.create(name="測試帳戶").details["account_id"])
    assert not accounts.restore(first).success
    assert accounts.archive(second).success
    assert accounts.restore(first).success

    categories = CategoryService(paths, store)
    parent = str(categories.create(name="交通").details["category_id"])
    child = str(categories.create(name="捷運", parent_id=parent).details["category_id"])
    assert categories.archive(child).success
    assert categories.archive(parent).success
    restore_child = categories.restore(child)
    assert not restore_child.success
    # 這件事以前是 `error_code="CATEGORY_RESTORE_FAILED"` ＋
    # `details["reason"]="CATEGORY_PARENT_NOT_ACTIVE"`，畫面上印成
    # 「類別／項目無法恢復；…（CATEGORY_PARENT_NOT_ACTIVE）」。現在碼就是那件事本身。
    assert restore_child.error_code == "CATEGORY_PARENT_NOT_ACTIVE"
    # 「所屬類別」不是「上層類別」—— 只有兩層，「上層」聽起來像還有第三層（見 glossary）。
    assert "所屬類別" in restore_child.message
    assert "reason" not in restore_child.details
    assert categories.restore(parent).success
    assert categories.restore(child).success


def test_settings_no_longer_contains_startup_backup(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger")
    LedgerStore(paths)
    service = SettingsService(paths)
    result = service.update(
        ApplicationSettings(
            default_account_id="acct_cash",
            default_entry_type="income",
            transactions_page_size=100,
            balance_snapshot_reminder=False,
        )
    )
    assert result.success
    settings = service.get()
    assert settings.transactions_page_size == 100
    assert settings.default_entry_type == "income"
    assert settings.balance_snapshot_reminder is False
    assert not hasattr(service, "startup_backup_due")


def test_backup_validation_restore_and_newer_schema_rejection(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger")
    add = AddTransaction(paths)
    assert add.execute(
        AddTransactionRequest(
            occurred_at="2026-06-01T10:00:00+08:00",
            entry_type="expense",
            amount="10",
        )
    ).success
    maintenance = MaintenanceService(paths)
    backup = maintenance.create_backup()
    assert maintenance.validate_backup(backup)["valid"]

    assert add.execute(
        AddTransactionRequest(
            occurred_at="2026-06-02T10:00:00+08:00",
            entry_type="expense",
            amount="20",
        )
    ).success
    maintenance.restore_backup(backup)
    assert LedgerStore(paths).account_balance_minor("acct_cash") == -10
    assert len(maintenance.list_backups()) == 1

    assert add.execute(
        AddTransactionRequest(
            occurred_at="2026-06-03T10:00:00+08:00",
            entry_type="expense",
            amount="30",
        )
    ).success
    maintenance.restore_backup(backup, create_backup_first=True)
    assert len(maintenance.list_backups()) == 2

    corrupted = maintenance.create_backup()
    with (corrupted / "ledger.sqlite3").open("ab") as handle:
        handle.write(b"corruption")
    assert (
        maintenance.validate_backup(corrupted)["error_code"]
        == "BACKUP_CHECKSUM_MISMATCH"
    )

    newer = maintenance.create_backup()
    database = newer / "ledger.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (99, 'future')"
        )
        connection.commit()
    manifest_path = newer / "backup_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sha256"] = hashlib.sha256(database.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    assert maintenance.validate_backup(newer)["error_code"] == "BACKUP_SCHEMA_TOO_NEW"
    with pytest.raises(ValueError, match="BACKUP_SCHEMA_TOO_NEW"):
        maintenance.restore_backup(newer)