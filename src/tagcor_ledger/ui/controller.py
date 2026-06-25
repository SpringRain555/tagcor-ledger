"""Presentation controller for the Phase 1–2 PySide6 interface."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.application.automation import AutomationService
from tagcor_ledger.application.catalogs import AccountService, CategoryService
from tagcor_ledger.application.result import Result
from tagcor_ledger.application.settings import SettingsService
from tagcor_ledger.application.transaction_service import (
    AddTransaction,
    AddTransactionRequest,
    AddTransfer,
    AddTransferRequest,
    ListTransactions,
    ReplaceTransfer,
    ReplaceTransferRequest,
    TransactionQuery,
    UpdateTransaction,
    UpdateTransactionRequest,
    VoidTransaction,
)
from tagcor_ledger.domain.models import (
    ApplicationSettings,
    RecurringSchedule,
    TransactionFilter,
    TransactionTemplate,
)
from tagcor_ledger.infrastructure.maintenance import MaintenanceService
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


class LedgerController:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self._wire_services()
        self._run_startup_tasks()

    def _wire_services(self) -> None:
        self.store = LedgerStore(self.paths)
        self.accounts = AccountService(self.paths, self.store)
        self.categories = CategoryService(self.paths, self.store)
        self.settings = SettingsService(self.paths)
        self.automation = AutomationService(self.paths)
        self.maintenance = MaintenanceService(self.paths)
        self.add_transaction = AddTransaction(self.paths, self.store)
        self.add_transfer = AddTransfer(self.paths, self.store)
        self.list_transaction_records = ListTransactions(self.paths, self.store)
        self.update_transaction_record = UpdateTransaction(self.paths, self.store)
        self.replace_transfer_record = ReplaceTransfer(self.paths, self.store)
        self.void_transaction_record = VoidTransaction(self.paths, self.store)

    def _run_startup_tasks(self) -> None:
        if self.settings.startup_backup_due():
            self.maintenance.create_backup(reason="startup")
            self.settings.mark_startup_backup()
        self.startup_generation = self.automation.generate_due()

    def account_options(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        result = self.accounts.list(include_archived=include_archived)
        return list(result.details.get("accounts", []))

    def category_options(
        self,
        parent_id: str | None = None,
        *,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        result = self.categories.list(
            parent_id=parent_id,
            include_archived=include_archived,
        )
        return list(result.details.get("categories", []))

    def submit(
        self,
        *,
        occurred_at: str,
        entry_type: str,
        amount: str,
        account_id: str,
        destination_account_id: str | None,
        category_id: str | None,
        payee_name: str,
        description: str,
    ) -> Result:
        if entry_type == "transfer":
            if destination_account_id is None:
                return Result.fail("TRANSFER_DESTINATION_REQUIRED", "請選擇轉入帳戶。")
            return self.add_transfer.execute(
                AddTransferRequest(
                    occurred_at=occurred_at,
                    amount=amount,
                    source_account_id=account_id,
                    destination_account_id=destination_account_id,
                    payee_name=payee_name,
                    description=description,
                )
            )
        if category_id is None:
            return Result.fail("CATEGORY_REQUIRED", "請選擇分類細項。")
        return self.add_transaction.execute(
            AddTransactionRequest(
                occurred_at=occurred_at,
                entry_type=entry_type,
                amount=amount,
                account_id=account_id,
                category_id=category_id,
                payee_name=payee_name,
                description=description,
            )
        )

    def list_transactions(
        self,
        *,
        search: str = "",
        date_from: str | None = None,
        date_to: str | None = None,
        account_id: str | None = None,
        category_id: str | None = None,
        status: str = "active",
        cursor: dict[str, str] | None = None,
        direction: str = "next",
        limit: int | None = None,
    ) -> Result:
        page_size = limit or self.settings.get().transactions_page_size
        return self.list_transaction_records.execute(
            TransactionQuery(
                limit=page_size,
                cursor_occurred_at=cursor.get("occurred_at") if cursor else None,
                cursor_transaction_id=cursor.get("transaction_id") if cursor else None,
                cursor_direction=direction,
                transaction_filter=TransactionFilter(
                    search=search,
                    date_from=date_from,
                    date_to=date_to,
                    account_id=account_id,
                    category_id=category_id,
                    status=status,
                ),
            )
        )

    def update_transaction(self, **values: Any) -> Result:
        return self.update_transaction_record.execute(UpdateTransactionRequest(**values))

    def replace_transfer(self, **values: Any) -> Result:
        return self.replace_transfer_record.execute(ReplaceTransferRequest(**values))

    def void_transaction(self, transaction_id: str) -> Result:
        return self.void_transaction_record.execute(transaction_id)

    def create_account(self, name: str, opening_balance: str) -> Result:
        return self.accounts.create(name=name, opening_balance=opening_balance)

    def archive_account(self, account_id: str) -> Result:
        return self.accounts.archive(account_id)

    def restore_account(self, account_id: str) -> Result:
        return self.accounts.restore(account_id)

    def rename_account(self, account_id: str, name: str) -> Result:
        return self.accounts.rename(account_id, name)

    def create_category(self, name: str, parent_id: str | None = None) -> Result:
        return self.categories.create(name=name, parent_id=parent_id)

    def archive_category(self, category_id: str) -> Result:
        return self.categories.archive(category_id)

    def restore_category(self, category_id: str) -> Result:
        return self.categories.restore(category_id)

    def rename_category(self, category_id: str, name: str) -> Result:
        return self.categories.rename(category_id, name)

    def get_settings(self) -> ApplicationSettings:
        return self.settings.get()

    def save_settings(self, settings: ApplicationSettings) -> Result:
        return self.settings.update(settings)

    def payee_suggestions(self, prefix: str = "") -> list[str]:
        return self.store.payee_suggestions(prefix=prefix, limit=20)

    def create_backup(self) -> Path:
        return self.maintenance.create_backup()

    def list_backups(self) -> list[dict[str, Any]]:
        return self.maintenance.list_backups()

    def validate_backup(self, path: Path) -> dict[str, Any]:
        return self.maintenance.validate_backup(path)

    def restore_backup(self, path: Path) -> None:
        self.maintenance.restore_backup(path)
        self._wire_services()

    def export_csv(self) -> Path:
        return self.maintenance.export_transactions_csv()

    def list_templates(self) -> list[dict[str, Any]]:
        result = self.automation.list_templates()
        return list(result.details.get("templates", []))

    def save_template(self, template: TransactionTemplate) -> Result:
        return self.automation.save_template(template)

    def new_template(self, **values: Any) -> TransactionTemplate:
        return self.automation.new_template(**values)

    def archive_template(self, template_id: str) -> Result:
        return self.automation.archive_template(template_id)

    def list_schedules(self) -> list[dict[str, Any]]:
        result = self.automation.list_schedules()
        return list(result.details.get("schedules", []))

    def save_schedule(self, schedule: RecurringSchedule) -> Result:
        return self.automation.save_schedule(schedule)

    def new_schedule(self, **values: Any) -> RecurringSchedule:
        return self.automation.new_schedule(**values)

    def archive_schedule(self, schedule_id: str) -> Result:
        return self.automation.archive_schedule(schedule_id)

    def generate_due(self) -> Result:
        return self.automation.generate_due()

    def list_pending(self) -> list[dict[str, Any]]:
        result = self.automation.list_pending()
        return list(result.details.get("occurrences", []))

    def update_occurrence(self, occurrence_id: str, **values: Any) -> Result:
        return self.automation.update_occurrence(occurrence_id, **values)

    def confirm_occurrence(self, occurrence_id: str) -> Result:
        return self.automation.confirm(occurrence_id)

    def skip_occurrence(self, occurrence_id: str) -> Result:
        return self.automation.skip(occurrence_id)

    def batch_confirm_valid(self) -> Result:
        return self.automation.batch_confirm_valid()
