from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from time import perf_counter

import pytest

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.application.balance import BalanceSnapshotService
from tagcor_ledger.application.transaction_service import AddTransaction, AddTransactionRequest
from tagcor_ledger.domain.models import CreateBalanceSnapshotRequest, TransactionFilter
from tagcor_ledger.infrastructure.database import database_transaction
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


@pytest.mark.performance
@pytest.mark.skipif(
    os.environ.get("TAGCOR_RUN_PERFORMANCE") != "1",
    reason="Set TAGCOR_RUN_PERFORMANCE=1 to run the 200,000-row benchmark.",
)
def test_large_ledger_common_operations_meet_latency_budget(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger-data")
    store = LedgerStore(paths)
    _seed_transactions(paths, 200_000)

    started = perf_counter()
    result = AddTransaction(paths, store).execute(
        AddTransactionRequest(
            occurred_at="2026-06-24T20:00:00+08:00",
            entry_type="expense",
            amount="85",
            payee_name="效能測試",
        )
    )
    add_elapsed = perf_counter() - started

    started = perf_counter()
    recent, _ = store.list_transactions(limit=50)
    recent_elapsed = perf_counter() - started

    started = perf_counter()
    filtered, _ = store.list_transactions(
        limit=50,
        transaction_filter=TransactionFilter(
            account_id="acct_cash",
            category_id="cat_food",
        ),
    )
    filter_elapsed = perf_counter() - started

    balance = BalanceSnapshotService(paths, store)
    started = perf_counter()
    snapshot = balance.create(
        CreateBalanceSnapshotRequest(
            account_id="acct_cash",
            observed_at="2026-06-24T21:00:00+08:00",
            actual_balance="0",
            note="效能測試",
        )
    )
    snapshot_elapsed = perf_counter() - started

    started = perf_counter()
    latest_gap = balance.latest_gap("acct_cash")
    gap_elapsed = perf_counter() - started

    print(
        "performance:",
        f"add={add_elapsed * 1000:.2f}ms",
        f"recent={recent_elapsed * 1000:.2f}ms",
        f"filter={filter_elapsed * 1000:.2f}ms",
        f"snapshot={snapshot_elapsed * 1000:.2f}ms",
        f"gap={gap_elapsed * 1000:.2f}ms",
    )
    assert result.success
    assert snapshot.success
    assert latest_gap.success
    assert len(recent) == 50
    assert len(filtered) == 50
    assert add_elapsed < 0.2
    assert recent_elapsed < 0.3
    assert filter_elapsed < 0.5
    assert snapshot_elapsed < 0.5
    assert gap_elapsed < 0.5


def _seed_transactions(paths, count: int) -> None:
    base = datetime(2020, 1, 1, tzinfo=timezone.utc)
    transactions = []
    postings = []
    allocations = []
    for index in range(count):
        transaction_id = f"txn_perf_{index:08d}"
        occurred_at = (base + timedelta(minutes=index)).isoformat()
        transactions.append(
            (
                transaction_id,
                occurred_at,
                occurred_at,
                occurred_at,
                f"corr_perf_{index:08d}",
            )
        )
        postings.append(
            (
                f"post_perf_{index:08d}",
                transaction_id,
                -1,
            )
        )
        allocations.append(
            (
                f"alloc_perf_{index:08d}",
                transaction_id,
            )
        )
    with database_transaction(paths.database_path) as connection:
        connection.executemany(
            """
            INSERT INTO transactions(
                transaction_id, revision, status, entry_type, occurred_at,
                recorded_at, updated_at, payee_name_snapshot, description,
                source, correlation_id
            ) VALUES (?, 1, 'active', 'expense', ?, ?, ?, '', '', 'manual', ?)
            """,
            transactions,
        )
        connection.executemany(
            """
            INSERT INTO account_postings(
                posting_id, transaction_id, account_id, amount_minor, currency, sequence
            ) VALUES (?, ?, 'acct_cash', ?, 'TWD', 1)
            """,
            postings,
        )
        connection.executemany(
            """
            INSERT INTO category_allocations(
                allocation_id, transaction_id, category_id, amount_minor, sequence
            ) VALUES (?, ?, 'cat_food_711', 1, 1)
            """,
            allocations,
        )
