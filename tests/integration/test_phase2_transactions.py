from pathlib import Path

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.application.transactions import (
    AddTransaction,
    AddTransactionRequest,
    ListRecentTransactions,
)
from tagcor_ledger.domain.models import TagPath
from tagcor_ledger.infrastructure.csv_ledger import CsvLedgerRepository
from tagcor_ledger.infrastructure.repositories import initialize_data_store


def test_add_transaction_writes_ledger_audit_and_manifest(tmp_path: Path) -> None:
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
    ledger_path = paths.ledger_dir / "ledger_2026.csv"
    rows = CsvLedgerRepository(ledger_path).read_rows()
    assert len(rows) == 1
    assert rows[0]["amount"] == "85"
    assert rows[0]["l4_name_snapshot"] == "7-11"
    assert rows[0]["correlation_id"] == result.correlation_id
    assert (paths.log_dir / "audit.log").read_text(encoding="utf-8").strip()
    assert "data/ledger_2026.csv" in (paths.config_dir / "data_manifest.json").read_text(
        encoding="utf-8"
    )


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
