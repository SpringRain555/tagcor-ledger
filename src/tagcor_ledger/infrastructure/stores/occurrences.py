"""待確認項目的持久化，以及「確認入帳」。

## 為什麼確認入帳不自己寫一份「建立交易」

`confirm_occurrence` 要在**同一個 SQLite transaction** 內做兩件事：建立交易、把那一期
標成 `confirmed`。分開做會出現「狀態是 confirmed 但交易沒建出來」，那是帳本層級的錯誤。

2026-08 之前的做法是自己重寫一份寫入路徑（transactions 列 ＋ postings ＋ allocation
＋ FTS，約 70 行），因為 `create_transaction()` 會自己開一個 transaction，沒辦法塞進
外層。代價是兩份實作，而且**已經分岔**：兩份 `_refresh_fts` 的 SQL 一字不差，
但只有一份會先 `DELETE`；兩份 `_audit` 只有一份收 `correlation_id`。

現在共用的是 `StoreBase._write_transaction()` / `_write_transfer()` —— 它們**收**
`connection` 而不是自己開，所以「就寫這一筆」與「建交易＋改狀態」兩種情境都成立。
"""

from __future__ import annotations

import sqlite3
from uuid import uuid4

from tagcor_ledger.domain.models import ScheduledOccurrence
from tagcor_ledger.domain.money import Money
from tagcor_ledger.infrastructure.clock import now_iso
from tagcor_ledger.infrastructure.database import connect_database, database_transaction
from tagcor_ledger.infrastructure.stores.base import StoreBase, new_correlation_id



class OccurrenceStore(StoreBase):
    def list_occurrences(self, *, status: str = "pending") -> list[ScheduledOccurrence]:
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                """
                SELECT o.*, s.name AS schedule_name,
                       a.status AS account_status,
                       da.status AS destination_status,
                       c.status AS category_status
                FROM scheduled_occurrences o
                JOIN recurring_schedules s ON s.schedule_id = o.schedule_id
                LEFT JOIN accounts a ON a.account_id = o.account_id
                LEFT JOIN accounts da ON da.account_id = o.destination_account_id
                LEFT JOIN categories c ON c.category_id = o.category_id
                WHERE o.status = ?
                ORDER BY o.due_date, s.name COLLATE NOCASE
                """,
                (status,),
            ).fetchall()
        return [_row_to_occurrence(row) for row in rows]

    def update_occurrence(
        self,
        occurrence_id: str,
        *,
        amount_minor: int | None,
        account_id: str,
        destination_account_id: str | None,
        category_id: str | None,
        description: str,
    ) -> None:
        with database_transaction(self.paths.database_path) as connection:
            changed = connection.execute(
                """
                UPDATE scheduled_occurrences
                SET amount_minor = ?, account_id = ?, destination_account_id = ?,
                    category_id = ?, description = ?, updated_at = ?
                WHERE occurrence_id = ? AND status = 'pending'
                """,
                (
                    amount_minor,
                    account_id,
                    destination_account_id,
                    category_id,
                    description.strip(),
                    now_iso(),
                    occurrence_id,
                ),
            ).rowcount
            if changed == 0:
                raise ValueError("OCCURRENCE_NOT_PENDING")
            self._audit(
                connection,
                correlation_id=new_correlation_id(),
                action="occurrence.update",
                entity_type="scheduled_occurrence",
                entity_id=occurrence_id,
                details={"amount_minor": amount_minor},
            )

    def confirm_occurrence(self, occurrence_id: str) -> str:
        with database_transaction(self.paths.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM scheduled_occurrences WHERE occurrence_id = ?",
                (occurrence_id,),
            ).fetchone()
            if row is None or row["status"] != "pending":
                raise ValueError("OCCURRENCE_NOT_PENDING")
            invalid = _occurrence_invalid_reason(connection, row)
            if invalid:
                raise ValueError(invalid)
            if row["amount_minor"] is None or int(row["amount_minor"]) <= 0:
                raise ValueError("OCCURRENCE_AMOUNT_REQUIRED")
            transaction_id = f"txn_{uuid4().hex}"
            # 這一次操作只有一個 correlation_id：交易列、transaction.create 稽核列與
            # occurrence.confirm 稽核列全部共用它，這樣才串得回去。
            correlation_id = new_correlation_id()
            occurred_at = f"{row['due_date']}T12:00:00+08:00"
            money = Money(int(row["amount_minor"]), str(row["currency"]))
            if row["entry_type"] == "transfer":
                self._write_transfer(
                    connection,
                    transaction_id=transaction_id,
                    occurred_at=occurred_at,
                    money=money,
                    source_account_id=str(row["account_id"]),
                    destination_account_id=str(row["destination_account_id"]),
                    description=str(row["description"]),
                    source="schedule",
                    correlation_id=correlation_id,
                )
            else:
                self._write_transaction(
                    connection,
                    transaction_id=transaction_id,
                    entry_type=str(row["entry_type"]),
                    occurred_at=occurred_at,
                    money=money,
                    account_id=str(row["account_id"]),
                    category_id=str(row["category_id"]),
                    description=str(row["description"]),
                    source="schedule",
                    correlation_id=correlation_id,
                )
            connection.execute(
                """
                UPDATE scheduled_occurrences
                SET status = 'confirmed', confirmed_transaction_id = ?, updated_at = ?
                WHERE occurrence_id = ?
                """,
                (transaction_id, now_iso(), occurrence_id),
            )
            self._audit(
                connection,
                correlation_id=correlation_id,
                action="occurrence.confirm",
                entity_type="scheduled_occurrence",
                entity_id=occurrence_id,
                details={"transaction_id": transaction_id},
            )
        return transaction_id

    def skip_occurrence(self, occurrence_id: str) -> None:
        with database_transaction(self.paths.database_path) as connection:
            changed = connection.execute(
                """
                UPDATE scheduled_occurrences SET status = 'skipped', updated_at = ?
                WHERE occurrence_id = ? AND status = 'pending'
                """,
                (now_iso(), occurrence_id),
            ).rowcount
            if changed == 0:
                raise ValueError("OCCURRENCE_NOT_PENDING")
            self._audit(
                connection,
                correlation_id=new_correlation_id(),
                action="occurrence.skip",
                entity_type="scheduled_occurrence",
                entity_id=occurrence_id,
                details={},
            )


def _row_to_occurrence(row: sqlite3.Row) -> ScheduledOccurrence:
    invalid = None
    if row["account_status"] != "active":
        invalid = "來源帳戶已封存"
    elif row["entry_type"] == "transfer" and row["destination_status"] != "active":
        invalid = "轉入帳戶已封存"
    elif row["entry_type"] != "transfer" and row["category_status"] != "active":
        invalid = "類別已封存"
    elif row["amount_minor"] is None:
        invalid = "尚未填寫金額"
    return ScheduledOccurrence(
        occurrence_id=str(row["occurrence_id"]),
        schedule_id=str(row["schedule_id"]),
        schedule_name=str(row["schedule_name"]),
        due_date=str(row["due_date"]),
        status=str(row["status"]),
        entry_type=str(row["entry_type"]),
        account_id=str(row["account_id"]),
        destination_account_id=(
            str(row["destination_account_id"])
            if row["destination_account_id"] is not None
            else None
        ),
        category_id=str(row["category_id"]) if row["category_id"] is not None else None,
        amount_minor=int(row["amount_minor"]) if row["amount_minor"] is not None else None,
        currency=str(row["currency"]),
        description=str(row["description"]),
        invalid_reason=invalid,
    )


def _occurrence_invalid_reason(connection: sqlite3.Connection, row: sqlite3.Row) -> str | None:
    account = connection.execute(
        "SELECT status FROM accounts WHERE account_id = ?", (row["account_id"],)
    ).fetchone()
    if account is None or account["status"] != "active":
        return "ACCOUNT_NOT_ACTIVE"
    if row["entry_type"] == "transfer":
        destination = connection.execute(
            "SELECT status FROM accounts WHERE account_id = ?",
            (row["destination_account_id"],),
        ).fetchone()
        if destination is None or destination["status"] != "active":
            return "DESTINATION_ACCOUNT_NOT_ACTIVE"
    else:
        category = connection.execute(
            "SELECT status FROM categories WHERE category_id = ?", (row["category_id"],)
        ).fetchone()
        if category is None or category["status"] != "active":
            return "CATEGORY_NOT_ACTIVE"
    return None
