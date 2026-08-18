"""餘額盤點與未解釋差額。

盤點**不建立交易、不建立 posting、不改變帳戶餘額**，它只記錄「當下實際看到多少」。
差額是算出來的：上一次盤點的實際金額（沒有的話就是期初餘額）加上這段期間的 posting
總和＝預期金額，實際金額減預期金額就是未解釋差額。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from tagcor_ledger.domain.models import (
    BalanceGap,
    BalanceSnapshot,
    BalanceSnapshotFilter,
    TransactionRecord,
)
from tagcor_ledger.infrastructure.clock import now_iso
from tagcor_ledger.infrastructure.database import connect_database, database_transaction
from tagcor_ledger.infrastructure.stores.base import NotFoundError, StoreBase


class BalanceStore(StoreBase):
    def create_balance_snapshot(
        self,
        *,
        snapshot_id: str,
        account_id: str,
        observed_at: str,
        actual_balance_minor: int,
        currency: str,
        note: str,
        correlation_id: str,
    ) -> BalanceGap:
        if actual_balance_minor < 0:
            raise ValueError("BALANCE_SNAPSHOT_NEGATIVE")
        timestamp = now_iso()
        with database_transaction(self.paths.database_path) as connection:
            self._require_active_account(connection, account_id, currency)
            connection.execute(
                """
                INSERT INTO balance_snapshots(
                    snapshot_id, account_id, observed_at, actual_balance_minor,
                    currency, status, note, created_at, updated_at, correlation_id
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    account_id,
                    observed_at,
                    actual_balance_minor,
                    currency,
                    note.strip(),
                    timestamp,
                    timestamp,
                    correlation_id,
                ),
            )
            self._audit(
                connection,
                correlation_id=correlation_id,
                action="balance_snapshot.create",
                entity_type="balance_snapshot",
                entity_id=snapshot_id,
                details={
                    "account_id": account_id,
                    "observed_at": observed_at,
                    "actual_balance_minor": actual_balance_minor,
                },
            )
        return self.get_balance_gap(snapshot_id)

    def update_balance_snapshot(
        self,
        *,
        snapshot_id: str,
        account_id: str,
        observed_at: str,
        actual_balance_minor: int,
        currency: str,
        note: str,
        correlation_id: str,
    ) -> BalanceGap:
        if actual_balance_minor < 0:
            raise ValueError("BALANCE_SNAPSHOT_NEGATIVE")
        timestamp = now_iso()
        with database_transaction(self.paths.database_path) as connection:
            self._require_active_account(connection, account_id, currency)
            changed = connection.execute(
                """
                UPDATE balance_snapshots
                SET account_id = ?, observed_at = ?, actual_balance_minor = ?,
                    currency = ?, note = ?, updated_at = ?
                WHERE snapshot_id = ? AND status = 'active'
                """,
                (
                    account_id,
                    observed_at,
                    actual_balance_minor,
                    currency,
                    note.strip(),
                    timestamp,
                    snapshot_id,
                ),
            ).rowcount
            if changed == 0:
                raise NotFoundError("BALANCE_SNAPSHOT_NOT_FOUND")
            self._audit(
                connection,
                correlation_id=correlation_id,
                action="balance_snapshot.update",
                entity_type="balance_snapshot",
                entity_id=snapshot_id,
                details={
                    "account_id": account_id,
                    "observed_at": observed_at,
                    "actual_balance_minor": actual_balance_minor,
                },
            )
        return self.get_balance_gap(snapshot_id)

    def void_balance_snapshot(self, snapshot_id: str, correlation_id: str) -> None:
        with database_transaction(self.paths.database_path) as connection:
            changed = connection.execute(
                """
                UPDATE balance_snapshots
                SET status = 'voided', updated_at = ?
                WHERE snapshot_id = ? AND status = 'active'
                """,
                (now_iso(), snapshot_id),
            ).rowcount
            if changed == 0:
                raise NotFoundError("BALANCE_SNAPSHOT_NOT_FOUND")
            self._audit(
                connection,
                correlation_id=correlation_id,
                action="balance_snapshot.void",
                entity_type="balance_snapshot",
                entity_id=snapshot_id,
                details={},
            )

    def get_balance_gap(self, snapshot_id: str) -> BalanceGap:
        with connect_database(self.paths.database_path) as connection:
            row = connection.execute(
                self._balance_snapshot_select() + " WHERE bs.snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError("BALANCE_SNAPSHOT_NOT_FOUND")
            return self._balance_gap_for_snapshot(
                connection,
                self._row_to_balance_snapshot(row),
            )

    def latest_balance_gap(self, account_id: str) -> BalanceGap | None:
        with connect_database(self.paths.database_path) as connection:
            row = connection.execute(
                self._balance_snapshot_select()
                + """
                WHERE bs.account_id = ? AND bs.status = 'active'
                ORDER BY bs.observed_at DESC, bs.snapshot_id DESC
                LIMIT 1
                """,
                (account_id,),
            ).fetchone()
            if row is None:
                return None
            return self._balance_gap_for_snapshot(
                connection,
                self._row_to_balance_snapshot(row),
            )

    def list_balance_gaps(
        self,
        *,
        snapshot_filter: BalanceSnapshotFilter | None = None,
        limit: int = 50,
    ) -> list[BalanceGap]:
        if not 1 <= limit <= 10000:
            raise ValueError("PAGE_LIMIT_INVALID")
        filters = snapshot_filter or BalanceSnapshotFilter()
        conditions: list[str] = []
        parameters: list[Any] = []
        if filters.account_id:
            conditions.append("bs.account_id = ?")
            parameters.append(filters.account_id)
        if filters.status == "active":
            conditions.append("bs.status = 'active'")
        elif filters.status == "voided":
            conditions.append("bs.status = 'voided'")
        elif filters.status != "all":
            raise ValueError("BALANCE_SNAPSHOT_STATUS_FILTER_INVALID")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = (
            self._balance_snapshot_select()
            + f" {where} ORDER BY bs.observed_at DESC, bs.snapshot_id DESC LIMIT ?"
        )
        parameters.append(limit)
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(sql, parameters).fetchall()
            return [
                self._balance_gap_for_snapshot(
                    connection,
                    self._row_to_balance_snapshot(row),
                )
                for row in rows
            ]

    def list_transactions_for_balance_gap(
        self,
        *,
        account_id: str,
        period_start: str | None,
        period_end: str,
        limit: int = 200,
    ) -> list[TransactionRecord]:
        if not 1 <= limit <= 500:
            raise ValueError("PAGE_LIMIT_INVALID")
        conditions = [
            "t.status = 'active'",
            """
            EXISTS (
                SELECT 1 FROM account_postings gp
                WHERE gp.transaction_id = t.transaction_id AND gp.account_id = ?
            )
            """,
            "t.occurred_at <= ?",
        ]
        parameters: list[Any] = [account_id, period_end]
        if period_start is not None:
            conditions.append("t.occurred_at > ?")
            parameters.append(period_start)
        where = f"WHERE {' AND '.join(conditions)}"
        sql = (
            self._transaction_select()
            + f" {where} ORDER BY t.occurred_at DESC, t.transaction_id DESC LIMIT ?"
        )
        parameters.append(limit)
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [self._row_to_transaction(row) for row in rows]

    def has_balance_snapshot_on_date(self, account_id: str, day: str) -> bool:
        with connect_database(self.paths.database_path) as connection:
            row = connection.execute(
                """
                SELECT 1 FROM balance_snapshots
                WHERE account_id = ? AND status = 'active'
                  AND observed_at >= ? AND observed_at <= ?
                LIMIT 1
                """,
                (
                    account_id,
                    f"{day}T00:00:00+08:00",
                    f"{day}T23:59:59+08:00",
                ),
            ).fetchone()
        return row is not None

    @staticmethod
    def _balance_snapshot_select() -> str:
        return """
        SELECT bs.snapshot_id, bs.account_id, a.name AS account_name,
               bs.observed_at, bs.actual_balance_minor, bs.currency,
               bs.status, bs.note, bs.created_at, bs.updated_at,
               bs.correlation_id
        FROM balance_snapshots bs
        JOIN accounts a ON a.account_id = bs.account_id
        """

    @staticmethod
    def _row_to_balance_snapshot(row: sqlite3.Row) -> BalanceSnapshot:
        return BalanceSnapshot(
            snapshot_id=str(row["snapshot_id"]),
            account_id=str(row["account_id"]),
            account_name=str(row["account_name"]),
            observed_at=str(row["observed_at"]),
            actual_balance_minor=int(row["actual_balance_minor"]),
            currency=str(row["currency"]),
            status=str(row["status"]),
            note=str(row["note"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            correlation_id=str(row["correlation_id"]),
        )

    def _balance_gap_for_snapshot(
        self,
        connection: sqlite3.Connection,
        snapshot: BalanceSnapshot,
    ) -> BalanceGap:
        account = connection.execute(
            """
            SELECT opening_balance_minor FROM accounts
            WHERE account_id = ?
            """,
            (snapshot.account_id,),
        ).fetchone()
        if account is None:
            raise NotFoundError("ACCOUNT_NOT_FOUND")
        previous = connection.execute(
            """
            SELECT snapshot_id, observed_at, actual_balance_minor
            FROM balance_snapshots
            WHERE account_id = ? AND status = 'active'
              AND observed_at < ?
            ORDER BY observed_at DESC, snapshot_id DESC
            LIMIT 1
            """,
            (snapshot.account_id, snapshot.observed_at),
        ).fetchone()
        if previous is None:
            previous_snapshot_id = None
            previous_observed_at = None
            previous_actual_balance_minor = None
            base_amount = int(account["opening_balance_minor"])
        else:
            previous_snapshot_id = str(previous["snapshot_id"])
            previous_observed_at = str(previous["observed_at"])
            previous_actual_balance_minor = int(previous["actual_balance_minor"])
            base_amount = previous_actual_balance_minor
        posting_conditions = [
            "p.account_id = ?",
            "t.status = 'active'",
            "t.occurred_at <= ?",
        ]
        parameters: list[Any] = [snapshot.account_id, snapshot.observed_at]
        if previous_observed_at is not None:
            posting_conditions.append("t.occurred_at > ?")
            parameters.append(previous_observed_at)
        posting_where = " AND ".join(posting_conditions)
        posting_row = connection.execute(
            f"""
            SELECT COALESCE(SUM(p.amount_minor), 0) AS posting_sum
            FROM account_postings p
            JOIN transactions t ON t.transaction_id = p.transaction_id
            WHERE {posting_where}
            """,
            parameters,
        ).fetchone()
        posting_sum = int(posting_row["posting_sum"]) if posting_row is not None else 0
        expected = base_amount + posting_sum
        return BalanceGap(
            snapshot=snapshot,
            previous_snapshot_id=previous_snapshot_id,
            previous_observed_at=previous_observed_at,
            previous_actual_balance_minor=previous_actual_balance_minor,
            period_start=previous_observed_at,
            period_end=snapshot.observed_at,
            posting_sum_minor=posting_sum,
            expected_balance_minor=expected,
            difference_minor=snapshot.actual_balance_minor - expected,
        )
