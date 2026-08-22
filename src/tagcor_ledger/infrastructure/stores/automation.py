"""模板、定期收支與待確認項目的 SQLite 持久化。

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

import calendar
from dataclasses import asdict
from datetime import date, timedelta
import sqlite3
from uuid import uuid4

from tagcor_ledger.domain.models import (
    RecurringSchedule,
    ScheduledOccurrence,
    TransactionTemplate,
)
from tagcor_ledger.domain.money import Money
from tagcor_ledger.infrastructure.clock import now_iso, today_taipei
from tagcor_ledger.infrastructure.database import connect_database, database_transaction
from tagcor_ledger.infrastructure.stores.base import StoreBase


def _new_correlation_id() -> str:
    """一次操作一個。**不要在寫稽核列的時候才生** —— 那樣同一次操作的每一列都會拿到
    不同的值，而 `correlation_id` 存在的唯一目的就是把它們串起來。"""
    return f"corr_{uuid4().hex}"


class AutomationStore(StoreBase):
    """模板／定期收支／待確認三個聚合。由 `LedgerStore` 組進去，不自己開 migration。"""

    def list_templates(self, *, include_archived: bool = False) -> list[TransactionTemplate]:
        where = "" if include_archived else "WHERE status = 'active'"
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT template_id, name, status, entry_type, account_id,
                       destination_account_id, category_id, amount_minor, currency,
                       description, sort_order
                FROM transaction_templates {where}
                ORDER BY sort_order, name COLLATE NOCASE
                """
            ).fetchall()
        return [TransactionTemplate(**dict(row)) for row in rows]

    def set_template_order(self, ordered_ids: list[str]) -> None:
        """模板的自訂順序。模板只有一組。

        **不走 `save_template()`。** 那條路會跑整套草稿驗證（帳戶、類別、金額），
        而調順序不該因為某個模板的帳戶被封存了就失敗 —— 那兩件事無關。
        """
        with database_transaction(self.paths.database_path) as connection:
            current = [
                str(row["template_id"])
                for row in connection.execute(
                    "SELECT template_id FROM transaction_templates"
                ).fetchall()
            ]
            self._apply_sort_order(
                connection,
                table="transaction_templates",
                id_column="template_id",
                current_ids=current,
                ordered_ids=ordered_ids,
            )
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action="template.reorder",
                entity_type="template",
                entity_id="all",
                details={"count": len(ordered_ids)},
            )

    def save_template(self, template: TransactionTemplate) -> TransactionTemplate:
        self._validate_draft(template)
        timestamp = now_iso()
        with database_transaction(self.paths.database_path) as connection:
            connection.execute(
                """
                INSERT INTO transaction_templates(
                    template_id, name, status, entry_type, account_id,
                    destination_account_id, category_id, amount_minor, currency,
                    description, sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(template_id) DO UPDATE SET
                    name = excluded.name, status = excluded.status,
                    entry_type = excluded.entry_type, account_id = excluded.account_id,
                    destination_account_id = excluded.destination_account_id,
                    category_id = excluded.category_id, amount_minor = excluded.amount_minor,
                    currency = excluded.currency, description = excluded.description,
                    sort_order = excluded.sort_order,
                    updated_at = excluded.updated_at
                """,
                (
                    template.template_id,
                    template.name.strip(),
                    template.status,
                    template.entry_type,
                    template.account_id,
                    template.destination_account_id,
                    template.category_id,
                    template.amount_minor,
                    template.currency,
                    template.description.strip(),
                    template.sort_order,
                    timestamp,
                    timestamp,
                ),
            )
            self._audit(
                connection,
                correlation_id=_new_correlation_id(),
                action="template.save",
                entity_type="template",
                entity_id=template.template_id,
                details=asdict(template),
            )
        return template

    def archive_template(self, template_id: str) -> None:
        with database_transaction(self.paths.database_path) as connection:
            changed = connection.execute(
                """
                UPDATE transaction_templates SET status = 'archived', updated_at = ?
                WHERE template_id = ? AND status = 'active'
                """,
                (now_iso(), template_id),
            ).rowcount
            if changed == 0:
                raise ValueError("TEMPLATE_NOT_FOUND")
            self._audit(
                connection,
                correlation_id=_new_correlation_id(),
                action="template.archive",
                entity_type="template",
                entity_id=template_id,
                details={},
            )

    def list_schedules(self, *, include_archived: bool = False) -> list[RecurringSchedule]:
        where = "" if include_archived else "WHERE status = 'active'"
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT schedule_id, name, status, entry_type, account_id,
                       destination_account_id, category_id, amount_minor, currency,
                       description, frequency, interval_count,
                       start_date, next_due_date, end_date
                FROM recurring_schedules {where}
                ORDER BY next_due_date, name COLLATE NOCASE
                """
            ).fetchall()
        return [RecurringSchedule(**dict(row)) for row in rows]

    def save_schedule(self, schedule: RecurringSchedule) -> RecurringSchedule:
        self._validate_draft(schedule)
        if schedule.frequency not in {"daily", "weekly", "monthly", "yearly"}:
            raise ValueError("SCHEDULE_FREQUENCY_INVALID")
        if schedule.interval_count < 1:
            raise ValueError("SCHEDULE_INTERVAL_INVALID")
        date.fromisoformat(schedule.start_date)
        date.fromisoformat(schedule.next_due_date)
        if schedule.end_date:
            date.fromisoformat(schedule.end_date)
        timestamp = now_iso()
        with database_transaction(self.paths.database_path) as connection:
            connection.execute(
                """
                INSERT INTO recurring_schedules(
                    schedule_id, name, status, entry_type, account_id,
                    destination_account_id, category_id, amount_minor, currency,
                    description, frequency, interval_count,
                    start_date, next_due_date, end_date, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(schedule_id) DO UPDATE SET
                    name = excluded.name, status = excluded.status,
                    entry_type = excluded.entry_type, account_id = excluded.account_id,
                    destination_account_id = excluded.destination_account_id,
                    category_id = excluded.category_id, amount_minor = excluded.amount_minor,
                    currency = excluded.currency, description = excluded.description,
                    frequency = excluded.frequency,
                    interval_count = excluded.interval_count, start_date = excluded.start_date,
                    next_due_date = excluded.next_due_date, end_date = excluded.end_date,
                    updated_at = excluded.updated_at
                """,
                (
                    schedule.schedule_id,
                    schedule.name.strip(),
                    schedule.status,
                    schedule.entry_type,
                    schedule.account_id,
                    schedule.destination_account_id,
                    schedule.category_id,
                    schedule.amount_minor,
                    schedule.currency,
                    schedule.description.strip(),
                    schedule.frequency,
                    schedule.interval_count,
                    schedule.start_date,
                    schedule.next_due_date,
                    schedule.end_date,
                    timestamp,
                    timestamp,
                ),
            )
            self._audit(
                connection,
                correlation_id=_new_correlation_id(),
                action="schedule.save",
                entity_type="schedule",
                entity_id=schedule.schedule_id,
                details=asdict(schedule),
            )
        return schedule

    def archive_schedule(self, schedule_id: str) -> None:
        with database_transaction(self.paths.database_path) as connection:
            changed = connection.execute(
                """
                UPDATE recurring_schedules SET status = 'archived', updated_at = ?
                WHERE schedule_id = ? AND status = 'active'
                """,
                (now_iso(), schedule_id),
            ).rowcount
            if changed == 0:
                raise ValueError("SCHEDULE_NOT_FOUND")
            self._audit(
                connection,
                correlation_id=_new_correlation_id(),
                action="schedule.archive",
                entity_type="schedule",
                entity_id=schedule_id,
                details={},
            )

    def generate_due_occurrences(
        self,
        *,
        through_date: str | None = None,
        limit: int = 366,
    ) -> tuple[int, bool]:
        today = date.fromisoformat(through_date) if through_date else today_taipei()
        generated = 0
        has_more = False
        with database_transaction(self.paths.database_path) as connection:
            schedules = connection.execute(
                """
                SELECT * FROM recurring_schedules
                WHERE status = 'active' AND next_due_date <= ?
                ORDER BY next_due_date
                """,
                (today.isoformat(),),
            ).fetchall()
            for row in schedules:
                due = date.fromisoformat(str(row["next_due_date"]))
                end = date.fromisoformat(str(row["end_date"])) if row["end_date"] else None
                while due <= today and (end is None or due <= end):
                    if generated >= limit:
                        has_more = True
                        break
                    timestamp = now_iso()
                    inserted = connection.execute(
                        """
                        INSERT OR IGNORE INTO scheduled_occurrences(
                            occurrence_id, schedule_id, due_date, status, entry_type,
                            account_id, destination_account_id, category_id, amount_minor,
                            currency, description, created_at, updated_at
                        ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"occ_{uuid4().hex}",
                            row["schedule_id"],
                            due.isoformat(),
                            row["entry_type"],
                            row["account_id"],
                            row["destination_account_id"],
                            row["category_id"],
                            row["amount_minor"],
                            row["currency"],
                            row["description"],
                            timestamp,
                            timestamp,
                        ),
                    )
                    generated += inserted.rowcount
                    due = next_due_date(
                        due,
                        str(row["frequency"]),
                        int(row["interval_count"]),
                        date.fromisoformat(str(row["start_date"])).day,
                    )
                connection.execute(
                    """
                    UPDATE recurring_schedules SET next_due_date = ?, updated_at = ?
                    WHERE schedule_id = ?
                    """,
                    (due.isoformat(), now_iso(), row["schedule_id"]),
                )
                if generated >= limit:
                    break
            if generated >= limit:
                remaining = connection.execute(
                    """
                    SELECT 1 FROM recurring_schedules
                    WHERE status = 'active' AND next_due_date <= ?
                      AND (end_date IS NULL OR next_due_date <= end_date)
                    LIMIT 1
                    """,
                    (today.isoformat(),),
                ).fetchone()
                has_more = remaining is not None
        return generated, has_more

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
                correlation_id=_new_correlation_id(),
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
            correlation_id = _new_correlation_id()
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
                correlation_id=_new_correlation_id(),
                action="occurrence.skip",
                entity_type="scheduled_occurrence",
                entity_id=occurrence_id,
                details={},
            )

    @staticmethod
    def _validate_draft(draft: TransactionTemplate | RecurringSchedule) -> None:
        if not draft.name.strip():
            raise ValueError("AUTOMATION_NAME_REQUIRED")
        if draft.entry_type == "transfer":
            if draft.destination_account_id is None or draft.category_id is not None:
                raise ValueError("TRANSFER_DRAFT_INVALID")
        elif draft.category_id is None or draft.destination_account_id is not None:
            raise ValueError("TRANSACTION_DRAFT_INVALID")
        if draft.amount_minor is not None and draft.amount_minor <= 0:
            raise ValueError("AUTOMATION_AMOUNT_INVALID")


def next_due_date(current: date, frequency: str, interval: int, anchor_day: int) -> date:
    if frequency == "daily":
        return current + timedelta(days=interval)
    if frequency == "weekly":
        return current + timedelta(weeks=interval)
    if frequency == "monthly":
        month_index = current.year * 12 + current.month - 1 + interval
        year, month_zero = divmod(month_index, 12)
        month = month_zero + 1
        day = min(anchor_day, calendar.monthrange(year, month)[1])
        return date(year, month, day)
    if frequency == "yearly":
        year = current.year + interval
        day = min(anchor_day, calendar.monthrange(year, current.month)[1])
        return date(year, current.month, day)
    raise ValueError("SCHEDULE_FREQUENCY_INVALID")


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
