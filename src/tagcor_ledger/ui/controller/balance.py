"""餘額盤點與未解釋差額。

**盤點不建立交易、不建立 posting、不改變餘額** —— 它是一個「那一刻實際數出來多少」
的快照。這一段只負責把頁面的輸入交給 `BalanceSnapshotService`。
"""

from __future__ import annotations

from typing import Any

from tagcor_ledger.application.balance import UpdateBalanceSnapshotRequest
from tagcor_ledger.application.result import Result
from tagcor_ledger.domain.models import CreateBalanceSnapshotRequest
from tagcor_ledger.ui.controller.wiring import ControllerBase


class BalanceSection(ControllerBase):
    def create_balance_snapshot(
        self,
        *,
        account_id: str,
        observed_at: str,
        actual_balance: str,
        note: str,
    ) -> Result:
        return self.balance.create(
            CreateBalanceSnapshotRequest(
                account_id=account_id,
                observed_at=observed_at,
                actual_balance=actual_balance,
                note=note,
            )
        )

    def update_balance_snapshot(
        self,
        snapshot_id: str,
        *,
        account_id: str,
        observed_at: str,
        actual_balance: str,
        note: str,
    ) -> Result:
        return self.balance.update(
            snapshot_id,
            UpdateBalanceSnapshotRequest(
                account_id=account_id,
                observed_at=observed_at,
                actual_balance=actual_balance,
                note=note,
            ),
        )

    def void_balance_snapshot(self, snapshot_id: str) -> Result:
        return self.balance.void(snapshot_id)

    def list_balance_snapshots(
        self,
        *,
        account_id: str | None = None,
        status: str = "active",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        result = self.balance.list(account_id=account_id, status=status, limit=limit)
        return self._rows(result, "gaps") if result.success else []

    def latest_balance_gap(self, account_id: str) -> dict[str, Any] | None:
        result = self.balance.latest_gap(account_id)
        gap = result.details.get("gap") if result.success else None
        return dict(gap) if isinstance(gap, dict) else None

    def list_balance_gap_transactions(
        self,
        *,
        account_id: str,
        period_start: str | None,
        period_end: str,
    ) -> list[dict[str, Any]]:
        result = self.balance.list_gap_transactions(
            account_id=account_id,
            period_start=period_start,
            period_end=period_end,
        )
        return self._rows(result, "transactions") if result.success else []

    def export_balance_snapshots_csv(self) -> Result:
        return self.balance.export_csv()
