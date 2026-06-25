"""SQLite persistence for templates and recurring schedules."""

from __future__ import annotations

import calendar
from dataclasses import asdict
from datetime import date, timedelta
import json
import sqlite3
from uuid import uuid4

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.domain.models import (
    RecurringSchedule,
    ScheduledOccurrence,
    TransactionTemplate,
)
from tagcor_ledger.infrastructure.clock import now_iso, today_taipei
from tagcor_ledger.infrastructure.database import (
    connect_database,
    database_transaction,
    initialize_database,
)


class AutomationStore:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        initialize_database(paths)

    def list_templates(self, *, include_archived: bool = False) -> list[TransactionTemplate]:
        where = "" if include_archived else "WHERE status = 'active'"
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT template_id, name, status, entry_type, account_id,
                       destination_account_id, category_id, amount_minor, currency,
                       payee_name, description, sort_order
                FROM transaction_templates {where}
                ORDER BY sort_order, name COLLATE NOCASE
                """
            ).fetchall()
        return [TransactionTemplate(**dict(row)) for row in rows]

    def save_template(self, template: TransactionTemplate) -> TransactionTemplate:
        self._validate_draft(template)
        timestamp = now_iso()
        with database_transaction(self.paths.database_path) as connection:
            connection.execute(
                """
                INSERT INTO transaction_templates(
                    template_id, name, status, entry_type, account_id,
                    destination_account_id, category_id, amount_minor, currency,
                    payee_name, description, sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(template_id) DO UPDATE SET
                    name = excluded.name, status = excluded.status,
                    entry_type = excluded.entry_type, account_id = excluded.account_id,
                    destination_account_id = excluded.destination_account_id,
                    category_id = excluded.category_id, amount_minor = excluded.amount_minor,
                    currency = excluded.currency, payee_name = excluded.payee_name,
                    description = excluded.description, sort_order = excluded.sort_order,
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
                    template.payee_name.strip(),
                    template.description.strip(),
                    template.sort_order,
                    timestamp,
                    timestamp,
                ),
            )
            _audit(
                connection,
                "template.save",
                "template",
                template.template_id,
                asdict(template),
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
            _audit(connection, "template.archive", "template", template_id, {})

    def list_schedules(self, *, include_archived: bool = False) -> list[RecurringSchedule]:
        where = "" if include_archived else "WHERE status = 'active'"
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT schedule_id, name, status, entry_type, account_id,
                       destination_account_id, category_id, amount_minor, currency,
                       payee_name, description, frequency, interval_count,
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
                    payee_name, description, frequency, interval_count,
                    start_date, next_due_date, end_date, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(schedule_id) DO UPDATE SET
                    name = excluded.name, status = excluded.status,
                    entry_type = excluded.entry_type, account_id = excluded.account_id,
                    destination_account_id = excluded.destination_account_id,
                    category_id = excluded.category_id, amount_minor = excluded.amount_minor,
                    currency = excluded.currency, payee_name = excluded.payee_name,
                    description = excluded.description, frequency = excluded.frequency,
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
                    schedule.payee_name.strip(),
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
            _audit(
                connection,
                "schedule.save",
                "schedule",
                schedule.schedule_id,
                asdict(schedule),
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
            _audit(connection, "schedule.archive", "schedule", schedule_id, {})

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
                            currency, payee_name, description, created_at, updated_at
                        ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                            row["payee_name"],
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
        payee_name: str,
        description: str,
    ) -> None:
        with database_transaction(self.paths.database_path) as connection:
            changed = connection.execute(
                """
                UPDATE scheduled_occurrences
                SET amount_minor = ?, account_id = ?, destination_account_id = ?,
                    category_id = ?, payee_name = ?, description = ?, updated_at = ?
                WHERE occurrence_id = ? AND status = 'pending'
                """,
                (
                    amount_minor,
                    account_id,
                    destination_account_id,
                    category_id,
                    payee_name.strip(),
                    description.strip(),
                    now_iso(),
                    occurrence_id,
                ),
            ).rowcount
            if changed == 0:
                raise ValueError("OCCURRENCE_NOT_PENDING")
            _audit(
                connection,
                "occurrence.update",
                "scheduled_occurrence",
                occurrence_id,
                {"amount_minor": amount_minor},
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
            correlation_id = f"corr_{uuid4().hex}"
            timestamp = now_iso()
            payee_id = _upsert_payee(connection, str(row["payee_name"]), timestamp)
            connection.execute(
                """
                INSERT INTO transactions(
                    transaction_id, revision, status, entry_type, occurred_at,
                    recorded_at, updated_at, payee_id, payee_name_snapshot,
                    description, source, correlation_id
                ) VALUES (?, 1, 'active', ?, ?, ?, ?, ?, ?, ?, 'schedule', ?)
                """,
                (
                    transaction_id,
                    row["entry_type"],
                    f"{row['due_date']}T12:00:00+08:00",
                    timestamp,
                    timestamp,
                    payee_id,
                    row["payee_name"],
                    row["description"],
                    correlation_id,
                ),
            )
            amount = int(row["amount_minor"])
            if row["entry_type"] == "transfer":
                connection.executemany(
                    """
                    INSERT INTO account_postings(
                        posting_id, transaction_id, account_id, amount_minor, currency, sequence
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            f"post_{uuid4().hex}",
                            transaction_id,
                            row["account_id"],
                            -amount,
                            row["currency"],
                            1,
                        ),
                        (
                            f"post_{uuid4().hex}",
                            transaction_id,
                            row["destination_account_id"],
                            amount,
                            row["currency"],
                            2,
                        ),
                    ],
                )
            else:
                signed = amount if row["entry_type"] == "income" else -amount
                connection.execute(
                    """
                    INSERT INTO account_postings(
                        posting_id, transaction_id, account_id, amount_minor, currency, sequence
                    ) VALUES (?, ?, ?, ?, ?, 1)
                    """,
                    (
                        f"post_{uuid4().hex}",
                        transaction_id,
                        row["account_id"],
                        signed,
                        row["currency"],
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO category_allocations(
                        allocation_id, transaction_id, category_id, amount_minor, sequence
                    ) VALUES (?, ?, ?, ?, 1)
                    """,
                    (f"alloc_{uuid4().hex}", transaction_id, row["category_id"], amount),
                )
            _refresh_fts(connection, transaction_id)
            connection.execute(
                """
                UPDATE scheduled_occurrences
                SET status = 'confirmed', confirmed_transaction_id = ?, updated_at = ?
                WHERE occurrence_id = ?
                """,
                (transaction_id, timestamp, occurrence_id),
            )
            _audit(
                connection,
                "occurrence.confirm",
                "scheduled_occurrence",
                occurrence_id,
                {"transaction_id": transaction_id},
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
            _audit(
                connection,
                "occurrence.skip",
                "scheduled_occurrence",
                occurrence_id,
                {},
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
        invalid = "分類已封存"
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
        payee_name=str(row["payee_name"]),
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


def _upsert_payee(
    connection: sqlite3.Connection, payee_name: str, timestamp: str
) -> str | None:
    clean = payee_name.strip()
    if not clean:
        return None
    row = connection.execute(
        "SELECT payee_id FROM payees WHERE name = ? COLLATE NOCASE", (clean,)
    ).fetchone()
    if row is not None:
        return str(row["payee_id"])
    payee_id = f"payee_{uuid4().hex}"
    connection.execute(
        """
        INSERT INTO payees(payee_id, name, status, created_at, updated_at)
        VALUES (?, ?, 'active', ?, ?)
        """,
        (payee_id, clean, timestamp, timestamp),
    )
    return payee_id


def _refresh_fts(connection: sqlite3.Connection, transaction_id: str) -> None:
    row = connection.execute(
        """
        SELECT t.payee_name_snapshot, t.description,
               COALESCE(GROUP_CONCAT(DISTINCT c.name), '') AS category_names,
               COALESCE(GROUP_CONCAT(DISTINCT a.name), '') AS account_names
        FROM transactions t
        LEFT JOIN category_allocations ca ON ca.transaction_id = t.transaction_id
        LEFT JOIN categories c ON c.category_id = ca.category_id
        LEFT JOIN account_postings p ON p.transaction_id = t.transaction_id
        LEFT JOIN accounts a ON a.account_id = p.account_id
        WHERE t.transaction_id = ?
        GROUP BY t.transaction_id
        """,
        (transaction_id,),
    ).fetchone()
    if row is None:
        return
    connection.execute(
        """
        INSERT INTO transaction_fts(transaction_id, payee, description, category, account)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            transaction_id,
            row["payee_name_snapshot"],
            row["description"],
            row["category_names"],
            row["account_names"],
        ),
    )


def _audit(
    connection: sqlite3.Connection,
    action: str,
    entity_type: str,
    entity_id: str,
    details: dict[str, object],
) -> None:
    connection.execute(
        """
        INSERT INTO audit_events(
            audit_id, occurred_at, correlation_id, action,
            entity_type, entity_id, result, details_json
        ) VALUES (?, ?, ?, ?, ?, ?, 'success', ?)
        """,
        (
            f"aud_{uuid4().hex}",
            now_iso(),
            f"corr_{uuid4().hex}",
            action,
            entity_type,
            entity_id,
            json.dumps(details, ensure_ascii=False, sort_keys=True),
        ),
    )
