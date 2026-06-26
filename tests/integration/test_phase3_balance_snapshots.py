from __future__ import annotations

from pathlib import Path

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.application.balance import (
    BalanceSnapshotService,
    UpdateBalanceSnapshotRequest,
)
from tagcor_ledger.application.catalogs import AccountService
from tagcor_ledger.application.transaction_service import AddTransaction, AddTransactionRequest
from tagcor_ledger.domain.models import CreateBalanceSnapshotRequest
from tagcor_ledger.infrastructure.clock import today_taipei
from tagcor_ledger.infrastructure.database import connect_database
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


def test_balance_snapshots_track_unexplained_gap_without_postings(
    tmp_path: Path,
) -> None:
    paths = resolve_app_paths(tmp_path / "ledger")
    store = LedgerStore(paths)
    account_id = str(
        AccountService(paths, store)
        .create(name="盤點現金", opening_balance="1000")
        .details["account_id"]
    )
    service = BalanceSnapshotService(paths, store)

    first = service.create(
        CreateBalanceSnapshotRequest(
            account_id=account_id,
            observed_at="2026-06-01T09:00:00+08:00",
            actual_balance="1000",
            note="第一次盤點",
        )
    )
    assert first.success
    assert first.details["gap"]["difference_minor"] == 0

    add = AddTransaction(paths, store)
    assert add.execute(
        AddTransactionRequest(
            occurred_at="2026-06-02T12:00:00+08:00",
            entry_type="expense",
            amount="100",
            account_id=account_id,
            category_id="cat_food_711",
        )
    ).success
    second = service.create(
        CreateBalanceSnapshotRequest(
            account_id=account_id,
            observed_at="2026-06-03T09:00:00+08:00",
            actual_balance="850",
            note="發現少 50",
        )
    )
    assert second.success
    assert second.details["gap"]["expected_balance_minor"] == 900
    assert second.details["gap"]["difference_minor"] == -50

    assert add.execute(
        AddTransactionRequest(
            occurred_at="2026-06-02T18:00:00+08:00",
            entry_type="expense",
            amount="50",
            account_id=account_id,
            category_id="cat_food_711",
        )
    ).success
    latest = service.latest_gap(account_id)
    assert latest.success
    assert latest.details["gap"]["expected_balance_minor"] == 850
    assert latest.details["gap"]["difference_minor"] == 0

    assert store.account_balance_minor(account_id) == 850
    with connect_database(paths.database_path) as connection:
        postings = connection.execute(
            "SELECT COUNT(*) AS count FROM account_postings WHERE account_id = ?",
            (account_id,),
        ).fetchone()
    assert postings is not None
    assert int(postings["count"]) == 2


def test_balance_snapshot_update_void_export_and_reminder(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger")
    store = LedgerStore(paths)
    account_id = str(
        AccountService(paths, store)
        .create(name="盤點銀行", opening_balance="500")
        .details["account_id"]
    )
    service = BalanceSnapshotService(paths, store)
    assert service.reminder_due(account_id)
    today = today_taipei().isoformat()

    created = service.create(
        CreateBalanceSnapshotRequest(
            account_id=account_id,
            observed_at=f"{today}T08:00:00+08:00",
            actual_balance="500",
            note="啟動後盤點",
        )
    )
    assert created.success
    snapshot_id = str(created.details["gap"]["snapshot_id"])
    assert not service.reminder_due(account_id)

    updated = service.update(
        snapshot_id,
        UpdateBalanceSnapshotRequest(
            account_id=account_id,
            observed_at=f"{today}T08:30:00+08:00",
            actual_balance="450",
            note="修正盤點",
        ),
    )
    assert updated.success
    assert updated.details["gap"]["difference_minor"] == -50

    target = paths.export_dir / "balance.csv"
    exported = service.export_csv(target)
    assert exported.success
    assert target.read_text(encoding="utf-8-sig").startswith("盤點時間,帳戶,實際金額")

    voided = service.void(snapshot_id)
    assert voided.success
    listed = service.list(account_id=account_id, status="active")
    assert listed.success
    assert listed.details["gaps"] == []
