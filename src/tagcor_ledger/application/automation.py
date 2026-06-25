"""Use cases for templates, schedules, and pending occurrences."""

from __future__ import annotations

from dataclasses import asdict
import sqlite3
from uuid import uuid4

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.application.result import Result
from tagcor_ledger.domain.models import (
    RecurringSchedule,
    ScheduledOccurrence,
    TransactionTemplate,
)
from tagcor_ledger.infrastructure.automation_store import AutomationStore


class AutomationService:
    def __init__(self, paths: AppPaths) -> None:
        self.store = AutomationStore(paths)

    def list_templates(self, *, include_archived: bool = False) -> Result:
        return Result.ok(
            "模板已載入。",
            details={
                "templates": [
                    asdict(item)
                    for item in self.store.list_templates(include_archived=include_archived)
                ]
            },
        )

    def save_template(self, template: TransactionTemplate) -> Result:
        try:
            saved = self.store.save_template(template)
            return Result.ok("模板已儲存。", details={"template": asdict(saved)})
        except (ValueError, sqlite3.Error) as exc:
            return Result.fail(
                "TEMPLATE_SAVE_FAILED",
                "模板無法儲存。",
                details={"reason": str(exc)},
            )

    def new_template(
        self,
        *,
        name: str,
        entry_type: str,
        account_id: str,
        destination_account_id: str | None,
        category_id: str | None,
        amount_minor: int | None,
        payee_name: str,
        description: str,
    ) -> TransactionTemplate:
        return TransactionTemplate(
            template_id=f"tpl_{uuid4().hex}",
            name=name,
            status="active",
            entry_type=entry_type,
            account_id=account_id,
            destination_account_id=destination_account_id,
            category_id=category_id,
            amount_minor=amount_minor,
            currency="TWD",
            payee_name=payee_name,
            description=description,
            sort_order=100,
        )

    def archive_template(self, template_id: str) -> Result:
        try:
            self.store.archive_template(template_id)
            return Result.ok("模板已封存。")
        except (ValueError, sqlite3.Error) as exc:
            return Result.fail(
                "TEMPLATE_ARCHIVE_FAILED", "模板無法封存。", details={"reason": str(exc)}
            )

    def list_schedules(self, *, include_archived: bool = False) -> Result:
        return Result.ok(
            "排程已載入。",
            details={
                "schedules": [
                    asdict(item)
                    for item in self.store.list_schedules(include_archived=include_archived)
                ]
            },
        )

    def save_schedule(self, schedule: RecurringSchedule) -> Result:
        try:
            saved = self.store.save_schedule(schedule)
            return Result.ok("排程已儲存。", details={"schedule": asdict(saved)})
        except (ValueError, sqlite3.Error) as exc:
            return Result.fail(
                "SCHEDULE_SAVE_FAILED",
                "排程無法儲存。",
                details={"reason": str(exc)},
            )

    def new_schedule(
        self,
        *,
        name: str,
        entry_type: str,
        account_id: str,
        destination_account_id: str | None,
        category_id: str | None,
        amount_minor: int | None,
        payee_name: str,
        description: str,
        frequency: str,
        interval_count: int,
        start_date: str,
        end_date: str | None,
    ) -> RecurringSchedule:
        return RecurringSchedule(
            schedule_id=f"sched_{uuid4().hex}",
            name=name,
            status="active",
            entry_type=entry_type,
            account_id=account_id,
            destination_account_id=destination_account_id,
            category_id=category_id,
            amount_minor=amount_minor,
            currency="TWD",
            payee_name=payee_name,
            description=description,
            frequency=frequency,
            interval_count=interval_count,
            start_date=start_date,
            next_due_date=start_date,
            end_date=end_date,
        )

    def archive_schedule(self, schedule_id: str) -> Result:
        try:
            self.store.archive_schedule(schedule_id)
            return Result.ok("排程已封存。")
        except (ValueError, sqlite3.Error) as exc:
            return Result.fail(
                "SCHEDULE_ARCHIVE_FAILED", "排程無法封存。", details={"reason": str(exc)}
            )

    def generate_due(self, *, through_date: str | None = None) -> Result:
        try:
            generated, has_more = self.store.generate_due_occurrences(
                through_date=through_date,
                limit=366,
            )
            return Result.ok(
                "到期項目已更新。",
                details={"generated": generated, "has_more": has_more},
            )
        except (ValueError, sqlite3.Error) as exc:
            return Result.fail(
                "SCHEDULE_GENERATE_FAILED",
                "到期項目無法產生。",
                details={"reason": str(exc)},
            )

    def list_pending(self) -> Result:
        items: list[ScheduledOccurrence] = self.store.list_occurrences(status="pending")
        return Result.ok(
            "待確認項目已載入.",
            details={"occurrences": [asdict(item) for item in items]},
        )

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
    ) -> Result:
        try:
            self.store.update_occurrence(
                occurrence_id,
                amount_minor=amount_minor,
                account_id=account_id,
                destination_account_id=destination_account_id,
                category_id=category_id,
                payee_name=payee_name,
                description=description,
            )
            return Result.ok("待確認項目已更新。")
        except (ValueError, sqlite3.Error) as exc:
            return Result.fail(
                "OCCURRENCE_UPDATE_FAILED",
                "待確認項目無法更新。",
                details={"reason": str(exc)},
            )

    def confirm(self, occurrence_id: str) -> Result:
        try:
            transaction_id = self.store.confirm_occurrence(occurrence_id)
            return Result.ok(
                "待確認項目已入帳。",
                details={"transaction_id": transaction_id},
            )
        except (ValueError, sqlite3.Error) as exc:
            return Result.fail(
                "OCCURRENCE_CONFIRM_FAILED",
                "待確認項目無法入帳。",
                details={"reason": str(exc)},
            )

    def skip(self, occurrence_id: str) -> Result:
        try:
            self.store.skip_occurrence(occurrence_id)
            return Result.ok("待確認項目已略過。")
        except (ValueError, sqlite3.Error) as exc:
            return Result.fail(
                "OCCURRENCE_SKIP_FAILED",
                "待確認項目無法略過。",
                details={"reason": str(exc)},
            )

    def batch_confirm_valid(self) -> Result:
        confirmed = 0
        failed = 0
        for item in self.store.list_occurrences(status="pending"):
            if item.invalid_reason is not None:
                failed += 1
                continue
            try:
                self.store.confirm_occurrence(item.occurrence_id)
                confirmed += 1
            except (ValueError, sqlite3.Error):
                failed += 1
        return Result.ok(
            "批次確認完成。",
            details={"confirmed": confirmed, "failed": failed},
        )
