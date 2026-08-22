"""餘額盤點的 use case 與未解釋差額計算。

**盤點不入帳**：不建立交易、不建立 posting、不改變帳戶餘額。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.application.failures import failure
from tagcor_ledger.application.result import Result, new_correlation_id
from tagcor_ledger.application.transaction_service import transaction_to_dict
from tagcor_ledger.domain.models import (
    BalanceGap,
    BalanceSnapshot,
    BalanceSnapshotFilter,
    CreateBalanceSnapshotRequest,
)
from tagcor_ledger.domain.money import Money, MoneyError
from tagcor_ledger.infrastructure.clock import today_taipei
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore, NotFoundError


@dataclass(frozen=True, slots=True)
class UpdateBalanceSnapshotRequest:
    account_id: str
    observed_at: str
    actual_balance: str
    note: str = ""
    currency: str = "TWD"


class BalanceSnapshotService:
    def __init__(self, paths: AppPaths, store: LedgerStore | None = None) -> None:
        self.paths = paths
        self.store = store or LedgerStore(paths)

    def create(self, request: CreateBalanceSnapshotRequest) -> Result:
        correlation_id = new_correlation_id()
        try:
            _validate_observed_at(request.observed_at)
            money = Money.from_decimal_string(
                request.actual_balance,
                currency=request.currency,
                allow_zero=True,
            )
            gap = self.store.create_balance_snapshot(
                snapshot_id=_new_snapshot_id(),
                account_id=request.account_id,
                observed_at=request.observed_at,
                actual_balance_minor=money.amount_minor,
                currency=money.currency,
                note=request.note,
                correlation_id=correlation_id,
            )
            return Result.ok(
                "餘額盤點已儲存。",
                details={"gap": balance_gap_to_dict(gap)},
                correlation_id=correlation_id,
            )
        except (MoneyError, ValueError) as exc:
            return failure(
                exc,
                fallback_code="BALANCE_SNAPSHOT_VALIDATION_FAILED",
                fallback_message="餘額盤點內容有問題但認不出原因。請匯出診斷資訊回報。",
                correlation_id=correlation_id,
            )
        except (sqlite3.Error, OSError) as exc:
            return Result.fail(
                "DATABASE_WRITE_FAILED",
                "餘額盤點無法寫入資料庫。請匯出診斷資訊回報。",
                details={"detail": str(exc)},
                correlation_id=correlation_id,
            )

    def update(self, snapshot_id: str, request: UpdateBalanceSnapshotRequest) -> Result:
        correlation_id = new_correlation_id()
        try:
            _validate_observed_at(request.observed_at)
            money = Money.from_decimal_string(
                request.actual_balance,
                currency=request.currency,
                allow_zero=True,
            )
            gap = self.store.update_balance_snapshot(
                snapshot_id=snapshot_id,
                account_id=request.account_id,
                observed_at=request.observed_at,
                actual_balance_minor=money.amount_minor,
                currency=money.currency,
                note=request.note,
                correlation_id=correlation_id,
            )
            return Result.ok(
                "餘額盤點已更新。",
                details={"gap": balance_gap_to_dict(gap)},
                correlation_id=correlation_id,
            )
        except (MoneyError, ValueError, NotFoundError) as exc:
            return failure(
                exc,
                fallback_code="BALANCE_SNAPSHOT_UPDATE_FAILED",
                fallback_message="餘額盤點無法更新，原因認不出來。請匯出診斷資訊回報。",
                correlation_id=correlation_id,
            )
        except sqlite3.Error as exc:
            return Result.fail(
                "DATABASE_WRITE_FAILED",
                "餘額盤點無法寫入資料庫。請匯出診斷資訊回報。",
                details={"detail": str(exc)},
                correlation_id=correlation_id,
            )

    def void(self, snapshot_id: str) -> Result:
        correlation_id = new_correlation_id()
        try:
            self.store.void_balance_snapshot(snapshot_id, correlation_id)
            return Result.ok("餘額盤點已作廢。", correlation_id=correlation_id)
        except NotFoundError as exc:
            return failure(
                exc,
                fallback_code="BALANCE_SNAPSHOT_NOT_FOUND",
                fallback_message="找不到可作廢的餘額盤點。請重新整理。",
                correlation_id=correlation_id,
            )
        except sqlite3.Error as exc:
            return Result.fail(
                "DATABASE_WRITE_FAILED",
                "餘額盤點無法作廢。請匯出診斷資訊回報。",
                details={"detail": str(exc)},
                correlation_id=correlation_id,
            )

    def list(
        self,
        *,
        account_id: str | None = None,
        status: str = "active",
        limit: int = 50,
    ) -> Result:
        try:
            gaps = self.store.list_balance_gaps(
                snapshot_filter=BalanceSnapshotFilter(account_id=account_id, status=status),
                limit=limit,
            )
            return Result.ok(
                "餘額盤點已載入。",
                details={"gaps": [balance_gap_to_dict(gap) for gap in gaps]},
            )
        except (ValueError, sqlite3.Error) as exc:
            return failure(
                exc,
                fallback_code="BALANCE_SNAPSHOT_LIST_FAILED",
                fallback_message="餘額盤點無法載入。請匯出診斷資訊回報。",
            )

    def latest_gap(self, account_id: str) -> Result:
        try:
            gap = self.store.latest_balance_gap(account_id)
            return Result.ok(
                "最近餘額盤點已載入。",
                details={"gap": balance_gap_to_dict(gap) if gap is not None else None},
            )
        except sqlite3.Error as exc:
            return Result.fail(
                "BALANCE_GAP_LOAD_FAILED",
                "最近餘額盤點無法載入。請匯出診斷資訊回報。",
                details={"detail": str(exc)},
            )

    def list_gap_transactions(
        self,
        *,
        account_id: str,
        period_start: str | None,
        period_end: str,
        limit: int = 200,
    ) -> Result:
        try:
            transactions = self.store.list_transactions_for_balance_gap(
                account_id=account_id,
                period_start=period_start,
                period_end=period_end,
                limit=limit,
            )
            return Result.ok(
                "差額期間交易已載入。",
                details={
                    "transactions": [
                        transaction_to_dict(transaction) for transaction in transactions
                    ]
                },
            )
        except (ValueError, sqlite3.Error) as exc:
            return failure(
                exc,
                fallback_code="BALANCE_GAP_TRANSACTIONS_FAILED",
                fallback_message="差額期間交易無法載入。請匯出診斷資訊回報。",
            )

    def export_csv(self, target: Path | None = None) -> Result:
        try:
            if target is None:
                target = self.paths.export_dir / (
                    f"balance_snapshots_{datetime.now():%Y%m%d_%H%M%S}.csv"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            gaps = self.store.list_balance_gaps(
                snapshot_filter=BalanceSnapshotFilter(status="all"),
                limit=10000,
            )
            fieldnames = [
                "盤點時間",
                "帳戶",
                "實際金額",
                "預期金額",
                "期間交易合計",
                "未解釋差額",
                "狀態",
                "備註",
                "盤點 ID",
            ]
            with target.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for gap in gaps:
                    writer.writerow(
                        {
                            "盤點時間": gap.snapshot.observed_at,
                            "帳戶": gap.snapshot.account_name,
                            "實際金額": _money_text(
                                gap.snapshot.actual_balance_minor,
                                gap.snapshot.currency,
                            ),
                            "預期金額": _money_text(
                                gap.expected_balance_minor,
                                gap.snapshot.currency,
                            ),
                            "期間交易合計": _money_text(
                                gap.posting_sum_minor,
                                gap.snapshot.currency,
                            ),
                            "未解釋差額": _money_text(
                                gap.difference_minor,
                                gap.snapshot.currency,
                            ),
                            "狀態": "有效" if gap.snapshot.status == "active" else "已作廢",
                            "備註": gap.snapshot.note,
                            "盤點 ID": gap.snapshot.snapshot_id,
                        }
                    )
            return Result.ok("餘額盤點 CSV 已匯出。", details={"path": str(target)})
        except (OSError, sqlite3.Error, ValueError) as exc:
            return Result.fail(
                "BALANCE_SNAPSHOT_EXPORT_FAILED",
                "餘額盤點 CSV 無法匯出。請確認匯出資料夾存在且可寫入、磁碟還有空間。",
                details={"detail": str(exc)},
            )

    def reminder_due(self, account_id: str) -> bool:
        return not self.store.has_balance_snapshot_on_date(
            account_id,
            today_taipei().isoformat(),
        )


def balance_gap_to_dict(gap: BalanceGap | None) -> dict[str, Any] | None:
    if gap is None:
        return None
    snapshot = balance_snapshot_to_dict(gap.snapshot)
    return {
        **snapshot,
        "previous_snapshot_id": gap.previous_snapshot_id,
        "previous_observed_at": gap.previous_observed_at,
        "previous_actual_balance_minor": gap.previous_actual_balance_minor,
        "period_start": gap.period_start,
        "period_end": gap.period_end,
        "posting_sum_minor": gap.posting_sum_minor,
        "posting_sum": _money_text(gap.posting_sum_minor, gap.snapshot.currency),
        "expected_balance_minor": gap.expected_balance_minor,
        "expected_balance": _money_text(gap.expected_balance_minor, gap.snapshot.currency),
        "difference_minor": gap.difference_minor,
        "difference": _money_text(gap.difference_minor, gap.snapshot.currency),
    }


def balance_snapshot_to_dict(snapshot: BalanceSnapshot) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "account_id": snapshot.account_id,
        "account_name": snapshot.account_name,
        "observed_at": snapshot.observed_at,
        "actual_balance_minor": snapshot.actual_balance_minor,
        "actual_balance": _money_text(snapshot.actual_balance_minor, snapshot.currency),
        "currency": snapshot.currency,
        "status": snapshot.status,
        "note": snapshot.note,
        "created_at": snapshot.created_at,
        "updated_at": snapshot.updated_at,
        "correlation_id": snapshot.correlation_id,
    }


def _money_text(amount_minor: int, currency: str) -> str:
    return Money(amount_minor=amount_minor, currency=currency).to_decimal_string()


def _new_snapshot_id() -> str:
    return f"snap_{uuid4().hex}"


def _validate_observed_at(value: str) -> None:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("DATETIME_TIMEZONE_REQUIRED")
