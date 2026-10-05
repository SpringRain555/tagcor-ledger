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


def test_balance_snapshot_update_delete_and_export(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger")
    store = LedgerStore(paths)
    account_id = str(
        AccountService(paths, store)
        .create(name="盤點銀行", opening_balance="500")
        .details["account_id"]
    )
    service = BalanceSnapshotService(paths, store)
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
    header = target.read_text(encoding="utf-8-sig").splitlines()[0]
    assert header.startswith("盤點時間,帳戶,實際金額")
    assert "狀態" not in header, "盤點不再有「已刪除」，狀態欄永遠是有效，不該匯出"

    deleted = service.delete(snapshot_id)
    assert deleted.success
    listed = service.list(account_id=account_id)
    assert listed.success
    assert listed.details["gaps"] == []
    # **真的刪掉**，不是標成已刪除（ADR-0015）。稽核留一列，而且不帶金額。
    with connect_database(paths.database_path) as connection:
        left = connection.execute(
            "SELECT COUNT(*) AS n FROM balance_snapshots WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchone()
        audit = connection.execute(
            "SELECT details_json FROM audit_events "
            "WHERE entity_id = ? AND action = 'balance_snapshot.delete'",
            (snapshot_id,),
        ).fetchall()
    assert int(left["n"]) == 0
    assert len(audit) == 1
    assert "actual_balance" not in str(audit[0]["details_json"])
    # 再刪一次是「找不到」，不是靜靜成功。
    again = service.delete(snapshot_id)
    assert not again.success
    assert again.error_code == "BALANCE_SNAPSHOT_NOT_FOUND"


def test_deleting_the_snapshots_frees_the_account_for_deletion(tmp_path: Path) -> None:
    """以前「刪除」只標成已刪除，而帳戶的引用檢查不看狀態 —— 刪光盤點，帳戶照樣刪不掉，
    訊息還說它「已經有交易紀錄」。真的刪掉之後，這個帳戶就跟沒用過一樣。"""
    paths = resolve_app_paths(tmp_path / "ledger")
    store = LedgerStore(paths)
    accounts = AccountService(paths, store)
    account_id = str(accounts.create(name="只盤點過", opening_balance="100").details["account_id"])
    service = BalanceSnapshotService(paths, store)
    created = service.create(
        CreateBalanceSnapshotRequest(
            account_id=account_id,
            observed_at="2026-06-01T09:00:00+08:00",
            actual_balance="100",
        )
    )
    assert created.success
    # 陽性對照：盤點還在的時候，帳戶確實刪不掉。
    assert not accounts.delete(account_id).success

    assert service.delete(str(created.details["gap"]["snapshot_id"])).success
    assert accounts.delete(account_id).success


def test_v12_removes_voided_snapshots_from_an_existing_database(tmp_path: Path) -> None:
    """舊資料庫裡標成 `voided` 的盤點，要靠 v12 才會消失；有效的一筆都不能少。

    做法同 v11 那條：**先把 v12 從 registry 刪掉**，模擬一個只跑到 v11 的資料庫 ——
    全新資料庫本來就沒有 voided 的列，那條路連 migration 都走不到。
    """
    import sqlite3

    from tagcor_ledger.infrastructure.database import initialize_database
    from tagcor_ledger.infrastructure.migrations import LATEST_SCHEMA_VERSION

    paths = resolve_app_paths(tmp_path / "data")
    initialize_database(paths)
    account_id = LedgerStore(paths).list_accounts()[0].account_id

    with sqlite3.connect(paths.database_path) as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 12")
        for snapshot_id, status in (("snap_kept", "active"), ("snap_voided", "voided")):
            connection.execute(
                """
                INSERT INTO balance_snapshots(
                    snapshot_id, account_id, observed_at, actual_balance_minor, currency,
                    status, note, created_at, updated_at, correlation_id
                ) VALUES (?, ?, '2026-06-01T09:00:00+08:00', 100, 'TWD', ?, '', '', '', ?)
                """,
                (snapshot_id, account_id, status, f"corr_{snapshot_id}"),
            )
        connection.commit()

    initialize_database(paths)

    with sqlite3.connect(paths.database_path) as connection:
        version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        left = {row[0] for row in connection.execute("SELECT snapshot_id FROM balance_snapshots")}

    assert version == LATEST_SCHEMA_VERSION
    assert left == {"snap_kept"}


def test_v11_removes_the_dead_reminder_setting_from_an_existing_database(
    tmp_path: Path,
) -> None:
    """舊資料庫裡那個沒有人再讀的設定鍵，要靠 v11 才會消失。

    **它留著不會壞任何東西** —— `settings` 是 key/value 表，多一列沒有人讀的鍵
    不影響任何查詢。正因為不會壞，所以永遠不會有人發現它已經沒有人讀了
    （[ADR-0014](../../docs/decisions/ADR-0014-drop-daily-snapshot-reminder.md)）。

    這裡刻意**先把 v11 從 registry 刪掉再插回那個鍵**，模擬一個只跑到 v10 的
    資料庫 —— 直接檢查全新資料庫沒有那個鍵是不夠的，那條路連 migration 都沒走到。
    """
    import sqlite3

    from tagcor_ledger.infrastructure.database import initialize_database
    from tagcor_ledger.infrastructure.migrations import LATEST_SCHEMA_VERSION

    paths = resolve_app_paths(tmp_path / "data")
    initialize_database(paths)

    with sqlite3.connect(paths.database_path) as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 11")
        connection.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES "
            "('balance_snapshot_reminder', 'true', '2026-01-01T00:00:00+08:00')"
        )
        connection.commit()

    initialize_database(paths)

    with sqlite3.connect(paths.database_path) as connection:
        version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        left = connection.execute(
            "SELECT COUNT(*) FROM settings WHERE key = 'balance_snapshot_reminder'"
        ).fetchone()[0]
        # 陽性對照：其他設定鍵一個都不能被掃到。
        others = connection.execute("SELECT COUNT(*) FROM settings").fetchone()[0]

    assert version == LATEST_SCHEMA_VERSION
    assert left == 0
    assert others > 0
