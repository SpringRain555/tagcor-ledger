from pathlib import Path
import sqlite3

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.application.transaction_service import (
    AddTransaction,
    AddTransactionRequest,
    ListRecentTransactions,
)
from tagcor_ledger.domain.models import TagPath
from tagcor_ledger.infrastructure.repositories import initialize_data_store


def test_add_transaction_writes_sqlite_posting_and_audit(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger-data")
    initialize_data_store(paths)
    request = AddTransactionRequest(
        occurred_at="2026-05-08T08:30:00+08:00",
        entry_type="expense",
        amount="85",
        tag_path=TagPath("tag_expense", "tag_cash", "tag_food", "tag_711"),
        description="早餐",
    )

    result = AddTransaction(paths).execute(request)

    assert result.success is True
    with sqlite3.connect(paths.database_path) as connection:
        connection.row_factory = sqlite3.Row
        transaction = connection.execute("SELECT * FROM transactions").fetchone()
        posting = connection.execute("SELECT * FROM account_postings").fetchone()
        audit = connection.execute("SELECT * FROM audit_events").fetchone()
    assert transaction["correlation_id"] == result.correlation_id
    assert posting["amount_minor"] == -85
    assert audit["action"] == "transaction.create"


def test_list_recent_transactions_returns_snapshot_name(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger-data")
    initialize_data_store(paths)
    AddTransaction(paths).execute(
        AddTransactionRequest(
            occurred_at="2026-05-08T08:30:00+08:00",
            entry_type="expense",
            amount="85",
            tag_path=TagPath("tag_expense", "tag_cash", "tag_food", "tag_711"),
            description="早餐",
        )
    )

    result = ListRecentTransactions(paths).execute()

    assert result.success is True
    transactions = result.details["transactions"]
    assert len(transactions) == 1
    assert transactions[0]["tag_path_name"] == "支出 / 現金 / 伙食 / 7-11"
    assert transactions[0]["description"] == "早餐"
