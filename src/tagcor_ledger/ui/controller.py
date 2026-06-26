"""Presentation controller for the PySide6 interface."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from tagcor_ledger.app.path_settings import PathSettingsError, PathSettingsService
from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.application.automation import AutomationService
from tagcor_ledger.application.balance import (
    BalanceSnapshotService,
    UpdateBalanceSnapshotRequest,
)
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
    CreateBalanceSnapshotRequest,
    RecurringSchedule,
    SystemPathSettings,
    TransactionFilter,
    TransactionTemplate,
)
from tagcor_ledger.infrastructure.database import connect_database
from tagcor_ledger.infrastructure.maintenance import MaintenanceService
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


class LedgerController:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.path_settings = PathSettingsService()
        self._wire_services()
        self._run_startup_tasks()

    def _wire_services(self) -> None:
        self.store = LedgerStore(self.paths)
        self.accounts = AccountService(self.paths, self.store)
        self.categories = CategoryService(self.paths, self.store)
        self.settings = SettingsService(self.paths)
        self.automation = AutomationService(self.paths)
        self.balance = BalanceSnapshotService(self.paths, self.store)
        self.maintenance = MaintenanceService(self.paths)
        self.add_transaction = AddTransaction(self.paths, self.store)
        self.add_transfer = AddTransfer(self.paths, self.store)
        self.list_transaction_records = ListTransactions(self.paths, self.store)
        self.update_transaction_record = UpdateTransaction(self.paths, self.store)
        self.replace_transfer_record = ReplaceTransfer(self.paths, self.store)
        self.void_transaction_record = VoidTransaction(self.paths, self.store)

    def _run_startup_tasks(self) -> None:
        self.startup_generation = self.automation.generate_due()
        self.refresh_balance_snapshot_reminder_due()

    def refresh_balance_snapshot_reminder_due(self) -> bool:
        settings = self.settings.get()
        self.balance_snapshot_reminder_due = (
            settings.balance_snapshot_reminder
            and self.balance.reminder_due(settings.default_account_id)
        )
        return self.balance_snapshot_reminder_due

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
                    description=description,
                )
            )
        if category_id is None:
            return Result.fail("CATEGORY_REQUIRED", "請選擇類別／項目。")
        return self.add_transaction.execute(
            AddTransactionRequest(
                occurred_at=occurred_at,
                entry_type=entry_type,
                amount=amount,
                account_id=account_id,
                category_id=category_id,
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

    def delete_account(self, account_id: str) -> Result:
        return self.accounts.delete(account_id)

    def create_category(self, name: str, parent_id: str | None = None) -> Result:
        return self.categories.create(name=name, parent_id=parent_id)

    def archive_category(self, category_id: str) -> Result:
        return self.categories.archive(category_id)

    def restore_category(self, category_id: str) -> Result:
        return self.categories.restore(category_id)

    def rename_category(self, category_id: str, name: str) -> Result:
        return self.categories.rename(category_id, name)

    def delete_category(self, category_id: str) -> Result:
        return self.categories.delete(category_id)

    def get_settings(self) -> ApplicationSettings:
        return self.settings.get()

    def save_settings(self, settings: ApplicationSettings) -> Result:
        return self.settings.update(settings)

    def get_path_settings(self) -> SystemPathSettings:
        return SystemPathSettings(
            ledger_dir=self.paths.ledger_dir,
            backup_dir=self.paths.backup_dir,
        )

    def save_path_settings(
        self,
        *,
        ledger_dir: Path,
        backup_dir: Path,
        move_current: bool = False,
    ) -> Result:
        try:
            settings = self.path_settings.save(
                SystemPathSettings(ledger_dir=ledger_dir, backup_dir=backup_dir)
            )
            next_paths = self._paths_for_settings(settings)
            if move_current:
                self._move_current_database(next_paths.database_path)
            self.paths = next_paths
            self._wire_services()
            return Result.ok("資料路徑設定已更新。")
        except (PathSettingsError, OSError, sqlite3.Error, ValueError) as exc:
            return Result.fail(
                "PATH_SETTINGS_SAVE_FAILED",
                "資料路徑設定無法儲存，請確認兩個路徑分開且可寫入。",
                details={"reason": str(exc)},
            )

    def _paths_for_settings(self, settings: SystemPathSettings) -> AppPaths:
        root = settings.ledger_dir.parent
        return AppPaths(
            data_dir=root,
            config_dir=self.paths.config_dir,
            ledger_dir=settings.ledger_dir,
            backup_dir=settings.backup_dir,
            export_dir=root / "exports",
            log_dir=root / "logs",
            tmp_dir=root / "tmp",
        )

    def _move_current_database(self, target_database: Path) -> None:
        source_database = self.paths.database_path
        if source_database.resolve() == target_database.resolve():
            return
        if target_database.exists():
            raise ValueError("TARGET_LEDGER_ALREADY_EXISTS")
        target_database.parent.mkdir(parents=True, exist_ok=True)
        if source_database.exists():
            with connect_database(source_database) as source:
                destination = sqlite3.connect(target_database)
                try:
                    source.backup(destination)
                finally:
                    destination.close()
            for path in (
                source_database,
                source_database.with_name(f"{source_database.name}-wal"),
                source_database.with_name(f"{source_database.name}-shm"),
            ):
                try:
                    path.unlink()
                except FileNotFoundError:
                    continue

    def create_backup(self) -> Path:
        return self.maintenance.create_backup()

    def list_backups(self) -> list[dict[str, Any]]:
        return self.maintenance.list_backups()

    def validate_backup(self, path: Path) -> dict[str, Any]:
        return self.maintenance.validate_backup(path)

    def restore_backup(self, path: Path, *, create_backup_first: bool = False) -> None:
        self.maintenance.restore_backup(path, create_backup_first=create_backup_first)
        self._wire_services()

    def reset_ledger(self, *, create_backup_first: bool = False) -> None:
        self.maintenance.reset_ledger(create_backup_first=create_backup_first)
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
        return list(result.details.get("gaps", [])) if result.success else []

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
        return list(result.details.get("transactions", [])) if result.success else []

    def export_balance_snapshots_csv(self) -> Result:
        return self.balance.export_csv()
