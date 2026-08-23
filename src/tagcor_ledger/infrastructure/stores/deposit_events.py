"""定存**待確認事件**的持久化：到期、每月領息、每月存入。

**程式不會自己入帳** —— 這裡只負責把事件記下來與標記處理結果，
「該產生哪些事件」由 `application/deposits.py` 決定。
"""

from __future__ import annotations

import sqlite3
from uuid import uuid4

from tagcor_ledger.domain.deposits import DepositEvent, DepositEventStatus
from tagcor_ledger.infrastructure.clock import now_iso
from tagcor_ledger.infrastructure.database import connect_database, database_transaction
from tagcor_ledger.infrastructure.stores.base import (
    NotFoundError,
    StoreBase,
    new_correlation_id,
)


class DepositEventStore(StoreBase):
    def add_event(
        self,
        *,
        term_id: str,
        event_type: str,
        due_date: str,
        suggested_amount_minor: int | None,
        note: str = "",
    ) -> bool:
        """新增一件待確認事件。已經有同一期、同種類、同日期的就不重複建立。

        回傳是否真的新增了 —— 呼叫端靠這個數「這次產生了幾筆」。
        """
        timestamp = now_iso()
        with database_transaction(self.paths.database_path) as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO deposit_events(
                    event_id, term_id, event_type, due_date, status,
                    suggested_amount_minor, actual_amount_minor, transaction_id,
                    note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'pending', ?, NULL, NULL, ?, ?, ?)
                """,
                (
                    f"devt_{uuid4().hex}",
                    term_id,
                    event_type,
                    due_date,
                    suggested_amount_minor,
                    note,
                    timestamp,
                    timestamp,
                ),
            )
            return cursor.rowcount > 0

    def list_pending_events(self) -> list[DepositEvent]:
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                _EVENT_SELECT + " WHERE e.status = 'pending' ORDER BY e.due_date, e.event_type"
            ).fetchall()
        return [_row_to_event(row) for row in rows]

    def get_event(self, event_id: str) -> DepositEvent:
        with connect_database(self.paths.database_path) as connection:
            row = connection.execute(
                _EVENT_SELECT + " WHERE e.event_id = ?", (event_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError("DEPOSIT_EVENT_NOT_FOUND")
        return _row_to_event(row)

    def settle_event(
        self,
        event_id: str,
        *,
        status: str,
        actual_amount_minor: int | None = None,
        transaction_id: str | None = None,
    ) -> None:
        with database_transaction(self.paths.database_path) as connection:
            changed = connection.execute(
                """
                UPDATE deposit_events
                SET status = ?, actual_amount_minor = ?, transaction_id = ?, updated_at = ?
                WHERE event_id = ? AND status = ?
                """,
                (
                    status,
                    actual_amount_minor,
                    transaction_id,
                    now_iso(),
                    event_id,
                    str(DepositEventStatus.PENDING),
                ),
            ).rowcount
            if changed == 0:
                raise NotFoundError("DEPOSIT_EVENT_NOT_PENDING")
            self._audit(
                connection,
                correlation_id=new_correlation_id(),
                action="deposit_event.settle",
                entity_type="deposit_event",
                entity_id=event_id,
                details={"status": status},
            )

    def update_event_suggestion(self, event_id: str, suggested_amount_minor: int | None) -> None:
        """就地更新建議金額。

        **不用「刪掉再重生」**：重生要依賴「今天」，而使用者補利率的時候，那一期的到期日
        通常還在未來 —— 刪掉之後就再也生不回來，待確認會整列消失。
        """
        with database_transaction(self.paths.database_path) as connection:
            connection.execute(
                """
                UPDATE deposit_events
                SET suggested_amount_minor = ?, updated_at = ?
                WHERE event_id = ? AND status = 'pending'
                """,
                (suggested_amount_minor, now_iso(), event_id),
            )

    def sum_confirmed_amount(self, term_id: str, event_type: str) -> int:
        """這一期已經確認入帳的某一種事件合計多少。

        存本取息到期時 `actual_interest_minor` 該填的是**整期實際領到的利息**，而那筆
        錢是一個月一個月領走的 —— 到期事件本身的金額是 0。沒有這個查詢的話，
        `deposit_terms.actual_interest_minor` 會被寫成 0，反推出來的實際年利率也是 0，
        而那一期明明有利息。
        """
        with connect_database(self.paths.database_path) as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(actual_amount_minor), 0) AS total
                FROM deposit_events
                WHERE term_id = ? AND event_type = ? AND status = 'confirmed'
                """,
                (term_id, event_type),
            ).fetchone()
        return int(row["total"]) if row is not None else 0

    def list_pending_events_for_term(self, term_id: str) -> list[DepositEvent]:
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                _EVENT_SELECT + " WHERE e.status = 'pending' AND e.term_id = ?",
                (term_id,),
            ).fetchall()
        return [_row_to_event(row) for row in rows]


_EVENT_SELECT = """
SELECT e.event_id, e.term_id, t.contract_id, c.name AS contract_name,
       e.event_type, e.due_date, e.status, e.suggested_amount_minor,
       e.actual_amount_minor, e.transaction_id, e.note
FROM deposit_events e
JOIN deposit_terms t ON t.term_id = e.term_id
JOIN deposit_contracts c ON c.contract_id = t.contract_id
"""


def _row_to_event(row: sqlite3.Row) -> DepositEvent:
    return DepositEvent(
        event_id=str(row["event_id"]),
        term_id=str(row["term_id"]),
        contract_id=str(row["contract_id"]),
        contract_name=str(row["contract_name"]),
        event_type=str(row["event_type"]),
        due_date=str(row["due_date"]),
        status=str(row["status"]),
        suggested_amount_minor=(
            int(row["suggested_amount_minor"])
            if row["suggested_amount_minor"] is not None
            else None
        ),
        actual_amount_minor=(
            int(row["actual_amount_minor"]) if row["actual_amount_minor"] is not None else None
        ),
        transaction_id=(
            str(row["transaction_id"]) if row["transaction_id"] is not None else None
        ),
        note=str(row["note"]),
    )
