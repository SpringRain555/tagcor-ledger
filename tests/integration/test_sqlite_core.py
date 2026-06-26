from pathlib import Path
import sqlite3

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.application.catalogs import AccountService
from tagcor_ledger.application.transaction_service import (
    AddTransaction,
    AddTransactionRequest,
    AddTransfer,
    AddTransferRequest,
    ListTransactions,
    TransactionQuery,
    UpdateTransaction,
    UpdateTransactionRequest,
    VoidTransaction,
)
from tagcor_ledger.domain.models import TransactionFilter
from tagcor_ledger.infrastructure.maintenance import MaintenanceService
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


def test_transfer_is_balanced_and_atomic(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger-data")
    store = LedgerStore(paths)
    second = AccountService(paths, store).create(name="銀行", opening_balance="1000")
    destination_id = second.details["account_id"]

    result = AddTransfer(paths, store).execute(
        AddTransferRequest(
            occurred_at="2026-06-24T10:00:00+08:00",
            amount="300",
            source_account_id=destination_id,
            destination_account_id="acct_cash",
        )
    )

    assert result.success is True
    with sqlite3.connect(paths.database_path) as connection:
        postings = connection.execute(
            "SELECT amount_minor FROM account_postings ORDER BY sequence"
        ).fetchall()
    assert postings == [(-300,), (300,)]
    assert sum(row[0] for row in postings) == 0
    assert store.account_balance_minor(destination_id) == 700
    assert store.account_balance_minor("acct_cash") == 300

    assert AccountService(paths, store).rename(destination_id, "主要銀行").success
    assert store.list_accounts()[1].name == "主要銀行"


def test_keyset_pagination_search_and_void(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger-data")
    store = LedgerStore(paths)
    add = AddTransaction(paths, store)
    for index in range(3):
        result = add.execute(
            AddTransactionRequest(
                occurred_at=f"2026-06-2{index + 1}T10:00:00+08:00",
                entry_type="expense",
                amount=str(index + 1),
                description=f"便利商店第 {index + 1} 筆",
            )
        )
        assert result.success

    first = ListTransactions(paths, store).execute(
        TransactionQuery(
            limit=2,
            transaction_filter=TransactionFilter(search="便利商店"),
        )
    )
    assert len(first.details["transactions"]) == 2
    assert first.details["next_cursor"] is not None
    cursor = first.details["next_cursor"]
    second = ListTransactions(paths, store).execute(
        TransactionQuery(
            limit=2,
            cursor_occurred_at=cursor["occurred_at"],
            cursor_transaction_id=cursor["transaction_id"],
            transaction_filter=TransactionFilter(search="便利商店"),
        )
    )
    assert len(second.details["transactions"]) == 1

    transaction_id = first.details["transactions"][0]["transaction_id"]
    assert VoidTransaction(paths, store).execute(transaction_id).success
    assert len(ListTransactions(paths, store).execute().details["transactions"]) == 2


def test_backup_and_csv_export(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger-data")
    AddTransaction(paths).execute(
        AddTransactionRequest(
            occurred_at="2026-06-24T10:00:00+08:00",
            entry_type="expense",
            amount="85",
            description="早餐",
        )
    )
    service = MaintenanceService(paths)

    backup = service.create_backup()
    exported = service.export_transactions_csv()

    assert (backup / "ledger.sqlite3").is_file()
    assert (backup / "backup_manifest.json").is_file()
    assert exported.read_text(encoding="utf-8-sig").startswith("交易時間,流向,帳戶")


def test_update_uses_revision_and_restore_reverts_later_data(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger-data")
    store = LedgerStore(paths)
    created = AddTransaction(paths, store).execute(
        AddTransactionRequest(
            occurred_at="2026-06-24T10:00:00+08:00",
            entry_type="expense",
            amount="85",
            description="原備註",
        )
    )
    transaction = created.details["transaction"]
    updated = UpdateTransaction(paths, store).execute(
        UpdateTransactionRequest(
            transaction_id=transaction["transaction_id"],
            expected_revision=1,
            occurred_at="2026-06-24T11:00:00+08:00",
            amount="100",
            account_id="acct_cash",
            category_id="cat_food_711",
            description="新備註",
        )
    )
    assert updated.success
    assert updated.details["transaction"]["revision"] == 2
    assert store.account_balance_minor("acct_cash") == -100

    maintenance = MaintenanceService(paths)
    backup = maintenance.create_backup()
    AddTransaction(paths, store).execute(
        AddTransactionRequest(
            occurred_at="2026-06-24T12:00:00+08:00",
            entry_type="expense",
            amount="50",
        )
    )
    assert store.account_balance_minor("acct_cash") == -150

    maintenance.restore_backup(backup)

    assert LedgerStore(paths).account_balance_minor("acct_cash") == -100