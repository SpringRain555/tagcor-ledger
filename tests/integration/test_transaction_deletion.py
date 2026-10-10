"""交易的「刪除」是真的移除（v13 起，ADR-0017）。

以前是 `void`：標成已刪除、紀錄留著、篩選看得到、不可復原 —— 正式會計的做法。這裡守四件事：
那一筆的每一列都真的沒了、只被它用過的帳戶與類別因此刪得掉、定存事件放手而外鍵乾淨、
舊資料庫裡的已刪除交易由 `migrate_v13` 清掉。
"""

from __future__ import annotations

from pathlib import Path
import sqlite3

from tagcor_ledger.app.paths import AppPaths, resolve_app_paths
from tagcor_ledger.application.catalogs import AccountService, CategoryService
from tagcor_ledger.application.deposits import DepositService
from tagcor_ledger.application.transaction_service import (
    AddTransaction,
    AddTransactionRequest,
    AddTransfer,
    AddTransferRequest,
    DeleteTransaction,
)
from tagcor_ledger.domain.deposits import DepositEventStatus, InterestMethod, MaturityAction
from tagcor_ledger.infrastructure.database import connect_database, initialize_database
from tagcor_ledger.infrastructure.migrations import LATEST_SCHEMA_VERSION
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore

TABLES = ("transactions", "account_postings", "category_allocations", "transaction_fts")
"""一筆交易住在這四張表裡。真的刪除要四張都清乾淨。"""


def _count(paths: AppPaths, table: str, transaction_id: str) -> int:
    with connect_database(paths.database_path) as connection:
        row = connection.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE transaction_id = ?", (transaction_id,)
        ).fetchone()
    return int(row["n"])


def _expense(paths: AppPaths, store: LedgerStore, **values: str) -> str:
    result = AddTransaction(paths, store).execute(
        AddTransactionRequest(
            occurred_at=values.pop("occurred_at", "2026-06-24T10:00:00+08:00"),
            entry_type="expense",
            amount=values.pop("amount", "85"),
            **values,
        )
    )
    assert result.success, result.message
    return str(result.details["transaction"]["transaction_id"])


def _foreign_key_violations(paths: AppPaths) -> list[tuple[object, ...]]:
    with connect_database(paths.database_path) as connection:
        return [tuple(row) for row in connection.execute("PRAGMA foreign_key_check")]


def test_deleting_removes_every_row_and_leaves_an_audit_line_without_the_amount(
    tmp_path: Path,
) -> None:
    paths = resolve_app_paths(tmp_path / "ledger")
    store = LedgerStore(paths)
    kept = _expense(paths, store, description="留著的那一筆")
    doomed = _expense(paths, store, amount="4321", description="打錯的那一筆")
    for table in TABLES:
        assert _count(paths, table, doomed) == 1, f"前提：{table} 裡要有它"

    assert DeleteTransaction(paths, store).execute(doomed).success

    for table in TABLES:
        assert _count(paths, table, doomed) == 0, f"{table} 裡還留著"
        assert _count(paths, table, kept) == 1, f"不該動到別筆：{table}"
    with connect_database(paths.database_path) as connection:
        audit = connection.execute(
            "SELECT details_json FROM audit_events "
            "WHERE entity_id = ? AND action = 'transaction.delete'",
            (doomed,),
        ).fetchall()
    assert len(audit) == 1
    assert "4321" not in str(audit[0]["details_json"]), "刪除的稽核列不記金額"

    again = DeleteTransaction(paths, store).execute(doomed)
    assert not again.success
    assert again.error_code == "TRANSACTION_NOT_FOUND", "再刪一次是找不到，不是靜靜成功"


def test_an_account_and_an_item_used_only_by_a_deleted_transaction_can_be_deleted(
    tmp_path: Path,
) -> None:
    """以前已刪除的交易**還在**，帳戶與類別的引用檢查不看狀態 —— 只被它用過的帳戶永遠
    刪不掉，訊息還說「已經有交易紀錄」。真的刪掉之後，它們就跟沒用過一樣。"""
    paths = resolve_app_paths(tmp_path / "ledger")
    store = LedgerStore(paths)
    accounts = AccountService(paths, store)
    categories = CategoryService(paths, store)
    account_id = str(accounts.create(name="試用帳戶", opening_balance="0").details["account_id"])
    item_id = str(categories.create(name="試用項目", parent_id="cat_food").details["category_id"])
    transaction_id = _expense(paths, store, account_id=account_id, category_id=item_id)

    # 陽性對照：交易還在的時候，兩個都刪不掉。
    blocked_account = accounts.delete(account_id)
    blocked_item = categories.delete(item_id)
    assert blocked_account.error_code == "ACCOUNT_HAS_TRANSACTIONS", blocked_account.error_code
    assert blocked_item.error_code == "CATEGORY_HAS_TRANSACTIONS", blocked_item.error_code

    assert DeleteTransaction(paths, store).execute(transaction_id).success
    assert accounts.delete(account_id).success
    assert categories.delete(item_id).success


def test_a_replaced_transfer_leaves_exactly_one_transfer_and_clean_foreign_keys(
    tmp_path: Path,
) -> None:
    paths = resolve_app_paths(tmp_path / "ledger")
    store = LedgerStore(paths)
    bank = str(
        AccountService(paths, store).create(name="郵局", opening_balance="1000").details[
            "account_id"
        ]
    )
    AddTransfer(paths, store).execute(
        AddTransferRequest(
            occurred_at="2026-06-01T10:00:00+08:00",
            amount="100",
            source_account_id=bank,
            destination_account_id="acct_cash",
        )
    )
    original = store.list_transactions(limit=10)[0][0]
    store.replace_transfer(
        original_transaction_id=original.transaction_id,
        new_transaction_id="txn_replacement",
        occurred_at="2026-06-02T10:00:00+08:00",
        money=original.money,
        source_account_id=bank,
        destination_account_id="acct_cash",
        description="",
        correlation_id="corr_replace",
    )

    records, _cursor = store.list_transactions(limit=10)
    assert [record.transaction_id for record in records] == ["txn_replacement"]
    assert _count(paths, "account_postings", original.transaction_id) == 0
    assert _foreign_key_violations(paths) == []


def test_deleting_a_deposit_posting_lets_go_of_the_event(tmp_path: Path) -> None:
    """定存確認入帳時，事件記著它產生的交易。刪掉那筆交易：事件**維持已確認**、
    `transaction_id` 放手成 NULL，外鍵乾淨 —— 跟以前作廢之後的結果一樣，那一筆待確認不會回來。"""
    paths = resolve_app_paths(tmp_path / "ledger")
    store = LedgerStore(paths)
    store.create_account(name="郵局活儲")
    store.create_account(name="郵局定存")
    accounts = {item.name: item.account_id for item in store.list_accounts()}
    service = DepositService(paths, store)
    assert service.create_contract(
        account_id=accounts["郵局定存"],
        name="郵局定存",
        interest_method=str(InterestMethod.LUMP_SUM),
        maturity_action=str(MaturityAction.NONE),
        interest_destination_account_id=accounts["郵局活儲"],
        term_months=12,
        opened_on="2026-02-15",
        principal="100000",
        annual_rate_ppm=16_000,
        recorded_on="2026-02-15",
    ).success
    service.generate_due(today="2027-02-15")
    event = store.list_pending_events()[0]
    confirmed = service.confirm(event.event_id, actual_amount_minor=1_600)
    assert confirmed.success, confirmed.message
    transaction_id = str(confirmed.details["transaction_id"])
    assert store.get_event(event.event_id).transaction_id == transaction_id, "前提：事件指著它"

    assert DeleteTransaction(paths, store).execute(transaction_id).success

    after = store.get_event(event.event_id)
    assert after.status == DepositEventStatus.CONFIRMED
    assert after.transaction_id is None
    assert _foreign_key_violations(paths) == []


def test_v13_removes_voided_transactions_from_an_existing_database(tmp_path: Path) -> None:
    """舊資料庫裡標成 `voided` 的交易，要靠 v13 才會消失；有效的一筆都不能少。

    做法同 v12 那條：**先把 v13 從 registry 刪掉**，模擬一個只跑到 v12 的資料庫，再用 SQL
    擺回舊版會留下的三種形狀 —— 刪掉的支出、被替換掉的舊轉帳（新的那筆用
    `replaces_transaction_id` 指著它）、定存確認後又被刪掉的那一筆（事件指著它）。
    全新資料庫本來就沒有 voided 的列，那條路連 migration 都走不到。
    """
    paths = resolve_app_paths(tmp_path / "ledger")
    store = LedgerStore(paths)
    kept = _expense(paths, store, description="留著")
    voided_expense = _expense(paths, store, description="刪掉的")
    bank = str(
        AccountService(paths, store).create(name="郵局", opening_balance="1000").details[
            "account_id"
        ]
    )
    for day in ("01", "02"):
        assert AddTransfer(paths, store).execute(
            AddTransferRequest(
                occurred_at=f"2026-06-{day}T10:00:00+08:00",
                amount="100",
                source_account_id=bank,
                destination_account_id="acct_cash",
            )
        ).success
    transfers = sorted(
        (record for record in store.list_transactions(limit=50)[0] if record.entry_type == "transfer"),
        key=lambda record: record.occurred_at,
    )
    old_transfer, new_transfer = (record.transaction_id for record in transfers)
    store.create_account(name="郵局定存")
    deposit_account = {item.name: item.account_id for item in store.list_accounts()}["郵局定存"]
    service = DepositService(paths, store)
    assert service.create_contract(
        account_id=deposit_account,
        name="郵局定存",
        interest_method=str(InterestMethod.LUMP_SUM),
        maturity_action=str(MaturityAction.NONE),
        interest_destination_account_id=bank,
        term_months=12,
        opened_on="2026-02-15",
        principal="100000",
        annual_rate_ppm=16_000,
        recorded_on="2026-02-15",
    ).success
    service.generate_due(today="2027-02-15")
    event = store.list_pending_events()[0]
    confirmed = service.confirm(event.event_id, actual_amount_minor=1_600)
    assert confirmed.success, confirmed.message
    deposit_posting = str(confirmed.details["transaction_id"])

    voided = (voided_expense, old_transfer, deposit_posting)
    with sqlite3.connect(paths.database_path) as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 13")
        connection.executemany(
            "UPDATE transactions SET status = 'voided' WHERE transaction_id = ?",
            [(transaction_id,) for transaction_id in voided],
        )
        connection.execute(
            "UPDATE transactions SET replaces_transaction_id = ? WHERE transaction_id = ?",
            (old_transfer, new_transfer),
        )
        connection.commit()

    initialize_database(paths)

    with connect_database(paths.database_path) as connection:
        version = connection.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
        replaces = connection.execute(
            "SELECT replaces_transaction_id AS r FROM transactions WHERE transaction_id = ?",
            (new_transfer,),
        ).fetchone()
        left_voided = connection.execute(
            "SELECT COUNT(*) AS n FROM transactions WHERE status = 'voided'"
        ).fetchone()
    assert int(version["v"]) == LATEST_SCHEMA_VERSION == 13
    assert int(left_voided["n"]) == 0
    for transaction_id in voided:
        for table in TABLES:
            assert _count(paths, table, transaction_id) == 0, (table, transaction_id)
    for transaction_id in (kept, new_transfer):
        assert _count(paths, "transactions", transaction_id) == 1, f"有效的不該被清掉：{transaction_id}"
    assert replaces["r"] is None, "替換關係改留在稽核列，欄位要清空"
    event_after = store.get_event(event.event_id)
    assert event_after.status == DepositEventStatus.CONFIRMED
    assert event_after.transaction_id is None
    assert _foreign_key_violations(paths) == []
