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

def test_account_balances_match_the_single_account_query(tmp_path: Path) -> None:
    """一次算完全部的那句，結果必須跟一個一個算完全相同。

    兩句 SQL 是同一段邏輯抄兩份（差別只有 `WHERE`），所以**只改一邊**是最容易犯的錯：
    畫面上的餘額會跟餘額盤點的預期值對不起來，而那種不一致看起來像帳記錯了。

    情境刻意涵蓋三種會讓兩句分歧的東西：期初餘額、轉帳（同一筆兩個 posting）、
    作廢（不該算進去）。
    """
    paths = resolve_app_paths(tmp_path / "ledger-data")
    store = LedgerStore(paths)
    bank = AccountService(paths, store).create(name="銀行", opening_balance="1000")
    bank_id = str(bank.details["account_id"])
    idle = AccountService(paths, store).create(name="沒有任何交易", opening_balance="7")
    idle_id = str(idle.details["account_id"])

    AddTransfer(paths, store).execute(
        AddTransferRequest(
            occurred_at="2026-06-24T10:00:00+08:00",
            amount="300",
            source_account_id=bank_id,
            destination_account_id="acct_cash",
        )
    )
    voided = AddTransaction(paths, store).execute(
        AddTransactionRequest(
            occurred_at="2026-06-24T11:00:00+08:00",
            entry_type="expense",
            amount="500",
            account_id=bank_id,
            category_id="cat_food_711",
        )
    )
    VoidTransaction(paths, store).execute(str(voided.details["transaction"]["transaction_id"]))

    balances = store.account_balances()
    accounts = store.list_accounts(include_archived=True)
    assert {account.account_id for account in accounts} == set(balances)
    for account in accounts:
        assert balances[account.account_id] == store.account_balance_minor(account.account_id), (
            account.name
        )

    # 陽性對照：這三個值真的不一樣，否則上面那圈等於在比一堆 0。
    assert balances[bank_id] == 700
    assert balances["acct_cash"] == 300
    assert balances[idle_id] == 7


def test_listing_accounts_opens_a_constant_number_of_connections(tmp_path: Path) -> None:
    """帳戶再多，列一次帳戶開的連線數不變。

    以前是每個帳戶各算一次餘額，而 `connect_database` 每次呼叫都開一條新連線 ＋
    四個 PRAGMA —— 列 8 個帳戶就是 9 條。這條測試量的是**連線數隨帳戶數的斜率**，
    不是絕對值，所以之後多加一句查詢也不會誤報。
    """
    paths = resolve_app_paths(tmp_path / "ledger-data")
    store = LedgerStore(paths)
    service = AccountService(paths, store)

    def connections() -> int:
        opened = 0
        original = sqlite3.connect

        def counted(*args: object, **kwargs: object) -> sqlite3.Connection:
            nonlocal opened
            opened += 1
            return original(*args, **kwargs)  # type: ignore[arg-type]

        sqlite3.connect = counted  # type: ignore[assignment]
        try:
            service.list(include_archived=True)
        finally:
            sqlite3.connect = original  # type: ignore[assignment]
        return opened

    baseline = connections()
    assert baseline > 0, "沒有攔截到任何連線，量測方式壞了"

    for index in range(7):
        assert service.create(name=f"帳戶 {index}", opening_balance="0").success
    assert len(store.list_accounts()) == 8

    assert connections() == baseline
