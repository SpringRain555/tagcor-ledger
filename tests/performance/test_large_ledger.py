from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from time import perf_counter

import pytest

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.application.balance import BalanceSnapshotService
from tagcor_ledger.application.catalogs import AccountService
from tagcor_ledger.application.transaction_service import AddTransaction, AddTransactionRequest
from tagcor_ledger.domain.models import CreateBalanceSnapshotRequest, TransactionFilter
from tagcor_ledger.infrastructure.database import database_transaction
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore
from tagcor_ledger.ui.controller import LedgerController


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
            description="效能測試",
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

    # 資產總覽是開啟程式的第一頁，而它的地基就是「一次算完所有帳戶餘額」。
    # 這一筆量的是那句彙總在 20 萬筆下要多久 —— 它會走過該帳戶的每一筆分錄，
    # 所以是**唯一一個成本真的跟資料量成正比**的常用查詢。
    started = perf_counter()
    accounts = AccountService(paths, store).list()
    accounts_elapsed = perf_counter() - started

    # 上面量的是地基，這一筆量的是**使用者實際會等的那件事**：切到資產總覽。
    # `overview_snapshot()` 不只算餘額，還要取定存、收件匣筆數、盤點提醒與未解釋差額，
    # 而且**每次切過去都重算一次**（刻意的：靠其他頁發訊號通知遲早會漏掉一項，
    # 而漏掉的症狀是總資產停在舊數字 —— 看起來像算錯帳）。
    # 所以「重算成本」是這個設計的前提，它必須被量著。
    controller = LedgerController(paths)
    started = perf_counter()
    overview = controller.overview_snapshot()
    overview_elapsed = perf_counter() - started

    print(
        "performance:",
        f"add={add_elapsed * 1000:.2f}ms",
        f"recent={recent_elapsed * 1000:.2f}ms",
        f"filter={filter_elapsed * 1000:.2f}ms",
        f"snapshot={snapshot_elapsed * 1000:.2f}ms",
        f"gap={gap_elapsed * 1000:.2f}ms",
        f"accounts={accounts_elapsed * 1000:.2f}ms",
        f"overview={overview_elapsed * 1000:.2f}ms",
    )
    assert overview["accounts"], "沒有帳戶就等於什麼都沒算到，門檻會變成假的"
    assert accounts.success
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
    # 實測 113ms（2026-08-20，20 萬筆）。門檻比照盤點與差額那兩筆的 0.5s ——
    # 它們同樣要走過整段分錄，量級也相近。
    assert accounts_elapsed < 0.5
    # 實測 183ms / 182ms（2026-08-20，兩次，20 萬筆）。它幾乎剛好是
    # accounts（77ms）＋ gap（100ms）—— 其餘幾項（定存、收件匣、設定）的筆數與
    # 資料量無關，所以這一頁只有兩個成本會隨帳本長大。門檻取那兩筆各自預算的和。
    assert overview_elapsed < 1.0


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
                recorded_at, updated_at, description, source, correlation_id
            ) VALUES (?, 1, 'active', 'expense', ?, ?, ?, '', 'manual', ?)
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
