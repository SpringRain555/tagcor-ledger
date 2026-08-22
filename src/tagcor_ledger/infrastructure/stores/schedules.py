"""定期收支的持久化，以及「產生到期項目」那一段。

UI 上叫「定期收支」，schema 仍是 `recurring_schedules` —— 那是兩件事，見 glossary。

`generate_due_occurrences()` 放在這裡而不是 `occurrences.py`：它的迴圈跑的是排程、
改的是排程自己的 `next_due_date`，待確認項目是它的**產出**而不是它的主題。
"""

from __future__ import annotations

from datetime import date
from dataclasses import asdict
from uuid import uuid4

from tagcor_ledger.domain.dates import next_due_date
from tagcor_ledger.domain.models import RecurringSchedule
from tagcor_ledger.infrastructure.clock import now_iso, today_taipei
from tagcor_ledger.infrastructure.database import connect_database, database_transaction
from tagcor_ledger.infrastructure.stores.base import StoreBase, new_correlation_id
from tagcor_ledger.infrastructure.stores.drafts import validate_draft



class ScheduleStore(StoreBase):
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
        validate_draft(schedule)
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
                correlation_id=new_correlation_id(),
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
                correlation_id=new_correlation_id(),
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
