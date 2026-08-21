"""Presentation controller for the PySide6 interface."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from tagcor_ledger.app.path_settings import (
    PathSettingsError,
    PathSettingsService,
    data_root_of,
    validate_path_settings,
)
from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.application.automation import AutomationService
from tagcor_ledger.application.balance import (
    BalanceSnapshotService,
    UpdateBalanceSnapshotRequest,
)
from tagcor_ledger.application.catalogs import AccountService, CategoryService
from tagcor_ledger.application.failures import failure
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
    CategoryTreeFilter,
    CreateBalanceSnapshotRequest,
    RecurringSchedule,
    SystemPathSettings,
    TransactionFilter,
    TransactionTemplate,
)
from tagcor_ledger.infrastructure.database import connect_database
from tagcor_ledger.application.deposits import DepositService
from tagcor_ledger.application.diagnostics import DiagnosticsService
from tagcor_ledger.application.reference import ReferenceEntry, ReferenceLibrary
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
        self.automation = AutomationService(self.paths, self.store)
        self.balance = BalanceSnapshotService(self.paths, self.store)
        self.maintenance = MaintenanceService(self.paths)
        self.diagnostics = DiagnosticsService(self.paths)
        self.deposits = DepositService(self.paths, self.store)
        # 法規庫在專案底下、與帳務資料無關，所以不隨資料路徑重新接線。
        self.reference = ReferenceLibrary()
        self.add_transaction = AddTransaction(self.paths, self.store)
        self.add_transfer = AddTransfer(self.paths, self.store)
        self.list_transaction_records = ListTransactions(self.paths, self.store)
        self.update_transaction_record = UpdateTransaction(self.paths, self.store)
        self.replace_transfer_record = ReplaceTransfer(self.paths, self.store)
        self.void_transaction_record = VoidTransaction(self.paths, self.store)

    def _run_startup_tasks(self) -> None:
        self.startup_generation = self.automation.generate_due()
        self.generation_has_more = bool(self.startup_generation.details.get("has_more"))
        self.deposits.generate_due()
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

    def overview_snapshot(self) -> dict[str, Any]:
        """資產總覽要顯示的每一項，一次組好。

        **頁面不自己拼這些規則。** 「總資產只加總使用中帳戶」、「封存帳戶餘額不為 0
        要另外講」這種判斷屬於「這個帳本現在是什麼狀況」，不屬於「怎麼擺 widget」。

        封存的意思是**不出現在選單**，不是錢消失了。所以總資產不算它，但也不能默默
        不提 —— 否則使用者會拿畫面上的數字去對存摺，然後對不起來。
        """
        accounts = self.account_options(include_archived=True)
        active = [item for item in accounts if item["status"] == "active"]
        settings = self.get_settings()
        default_account = next(
            (
                item
                for item in accounts
                if str(item["account_id"]) == settings.default_account_id
            ),
            None,
        )
        return {
            "total_minor": sum(int(item["balance_minor"]) for item in active),
            "accounts": active,
            "archived_with_balance": [
                item
                for item in accounts
                if item["status"] != "active" and int(item["balance_minor"]) != 0
            ],
            "deposit": self._next_deposit_term(),
            "inbox_count": self.inbox_count(),
            # 提醒是**現算**的，不讀 `balance_snapshot_reminder_due` 那個快取值：
            # 那個值只在啟動與存設定時更新，於是「剛盤點完，提醒還在」。
            "snapshot_due_account": (
                str(default_account["name"])
                if default_account is not None
                and self.refresh_balance_snapshot_reminder_due()
                else None
            ),
            "latest_gap": (
                self.latest_balance_gap(settings.default_account_id)
                if default_account is not None
                else None
            ),
        }

    def _next_deposit_term(self) -> dict[str, Any] | None:
        """最近一期會到期的定存。沒有存續中的合約就回傳 None（整段不顯示）。"""
        contracts = {
            str(contract["contract_id"]): contract
            for contract in self.list_deposit_contracts()
        }
        terms = [
            term
            for term in self.list_deposit_terms()
            if term["status"] == "active" and str(term["contract_id"]) in contracts
        ]
        if not terms:
            return None
        nearest = min(terms, key=lambda term: str(term["maturity_date"]))
        return {
            "contract_name": str(contracts[str(nearest["contract_id"])]["name"]),
            "maturity_date": str(nearest["maturity_date"]),
            "principal_minor": int(nearest["principal_minor"]),
            "total_principal_minor": sum(int(term["principal_minor"]) for term in terms),
            "contract_count": len(terms),
        }

    def list_inbox(self) -> list[dict[str, Any]]:
        """待確認的單一清單：定期收支與定存合成一份，依到期日排序。

        **使用者不需要知道待確認來自哪個子系統。** 以前是同一頁上下兩張表，於是
        「我還有幾件事要處理」得自己把兩個數字加起來，六顆按鈕還得先想清楚哪三顆
        是對上面那張表的。

        兩邊的欄位形狀確實不同，所以每一列多帶一個 `source`：
        `inbox_values()` 靠它決定怎麼顯示，「確認入帳」靠它決定分派給誰。
        排序的第二、三順位是 `source` 與 id —— 只用到期日排的話，同一天的項目
        每次重整順序都可能不一樣。
        """
        rows = [dict(item, source="schedule") for item in self.list_pending()]
        rows += [dict(item, source="deposit") for item in self.list_deposit_pending()]
        rows.sort(
            key=lambda item: (
                str(item["due_date"]),
                str(item["source"]),
                str(item.get("occurrence_id") or item.get("event_id") or ""),
            )
        )
        return rows

    def inbox_count(self) -> int:
        """待確認的總筆數 —— **定期收支與定存一起算**。

        側邊欄的數字與資產總覽的數字都走這一個方法。兩邊各自算就會出現「側邊欄說 2、
        總覽說 3」，而使用者沒有辦法知道哪一個才對。
        """
        return len(self.list_inbox())

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

    def category_tree(
        self,
        *,
        include_archived: bool = False,
        tree_filter: CategoryTreeFilter | None = None,
    ) -> list[dict[str, Any]]:
        """兩層類別攤成一份列表，每一列都帶著上層名稱與子項目數。

        `tree_filter` 一給就以它為準：層級、所屬類別、狀態、名稱搜尋與排序**都在
        SQL 裡處理**。「類別」與「項目」兩個分頁各自送自己的 `level`，不再撈回全部
        再用 Python 濾。
        """
        result = self.categories.list_tree(
            include_archived=include_archived, tree_filter=tree_filter
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
        """目前生效的三個路徑。

        **`data_root` 一定要填。** 以前這裡只回傳兩個路徑，`data_root` 永遠是 `None`，
        於是它會被 `data_root_of()` 推成 `ledger_dir.parent` —— 而
        `PATH_OUTSIDE_DATA_ROOT` 這個錯誤講的正是那個值。使用者在畫面上看不到它，
        卻要照它去修路徑。
        """
        return SystemPathSettings(
            ledger_dir=self.paths.ledger_dir,
            backup_dir=self.paths.backup_dir,
            data_root=self.paths.data_dir,
        )

    def save_path_settings(
        self,
        *,
        ledger_dir: Path,
        backup_dir: Path,
        data_root: Path | None = None,
        move_current: bool = False,
    ) -> Result:
        """更新資料路徑。

        順序是刻意的：先把資料庫複製到新位置並確認成功，**才**寫指標檔，最後才刪掉
        舊檔。任何一步失敗都不會留下「指標指向新位置、資料還在舊位置」的狀態 ——
        那會讓下次啟動在新位置建一個空資料庫，看起來像資料消失。
        """
        copied: Path | None = None
        try:
            settings = validate_path_settings(
                SystemPathSettings(
                    ledger_dir=ledger_dir,
                    backup_dir=backup_dir,
                    data_root=data_root,
                ),
                create=True,
            )
            next_paths = self._paths_for_settings(settings)
            if move_current:
                copied = self._copy_current_database(next_paths.database_path)
            self.path_settings.write(settings)
            if copied is not None:
                self._discard_previous_database()
            self.paths = next_paths
            self._wire_services()
            return Result.ok("資料路徑設定已更新。")
        except (PathSettingsError, OSError, sqlite3.Error, ValueError) as exc:
            if copied is not None:
                # 指標檔還沒寫成功，新位置那份複本必須清掉，否則下次搬移會撞上
                # TARGET_LEDGER_ALREADY_EXISTS。舊資料原封不動。
                copied.unlink(missing_ok=True)
            # 五種失敗（同路徑、互相包含、超出資料根目錄、寫不進去、設定檔壞掉）
            # 以前擠在同一句「請確認兩個路徑分開、都在資料根目錄底下且可寫入」，
            # 真正發生的是哪一種只寫在後面括號裡的英文碼。
            return failure(
                exc,
                fallback_code="PATH_SETTINGS_SAVE_FAILED",
                fallback_message=(
                    "資料路徑設定無法儲存，舊設定與舊資料都沒有變動。請匯出診斷資訊回報。"
                ),
            )

    def _paths_for_settings(self, settings: SystemPathSettings) -> AppPaths:
        root = data_root_of(settings)
        return AppPaths(
            data_dir=root,
            config_dir=self.paths.config_dir,
            ledger_dir=settings.ledger_dir,
            backup_dir=settings.backup_dir,
            export_dir=root / "exports",
            log_dir=root / "logs",
            tmp_dir=root / "tmp",
        )

    def _copy_current_database(self, target_database: Path) -> Path | None:
        """把現有資料庫複製到新位置，回傳複本路徑；沒有東西要複製時回傳 None。

        只複製、不刪除。刪除由 `_discard_previous_database` 在指標檔寫入成功後才做。
        """
        source_database = self.paths.database_path
        if source_database.resolve() == target_database.resolve():
            return None
        if target_database.exists():
            raise ValueError("TARGET_LEDGER_ALREADY_EXISTS")
        if not source_database.exists():
            return None
        target_database.parent.mkdir(parents=True, exist_ok=True)
        with connect_database(source_database) as source:
            destination = sqlite3.connect(target_database)
            try:
                source.backup(destination)
            finally:
                destination.close()
        return target_database

    def _discard_previous_database(self) -> None:
        source_database = self.paths.database_path
        for path in (
            source_database,
            source_database.with_name(f"{source_database.name}-wal"),
            source_database.with_name(f"{source_database.name}-shm"),
        ):
            path.unlink(missing_ok=True)

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

    def reference_status(self) -> Result:
        return self.reference.status()

    def reference_topics(self) -> list[dict[str, Any]]:
        return self.reference.topics()

    def reference_entries(
        self, *, topic: object = None, keyword: str = ""
    ) -> list[ReferenceEntry]:
        return self.reference.list_entries(
            topic=str(topic) if isinstance(topic, str) else None, keyword=keyword
        )

    def export_diagnostics(self) -> Result:
        return self.diagnostics.export()

    def ledger_counts(self) -> dict[str, int]:
        """各表筆數。給重製確認框用 —— 不可逆的操作要講得出「會失去什麼」。"""
        return self.diagnostics.counts()

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

    def list_deposit_contracts(self, *, include_closed: bool = False) -> list[dict[str, Any]]:
        result = self.deposits.list_contracts(include_closed=include_closed)
        return list(result.details.get("contracts", []))

    def list_deposit_terms(self, contract_id: str | None = None) -> list[dict[str, Any]]:
        result = self.deposits.list_terms(contract_id)
        return list(result.details.get("terms", []))

    def create_deposit_contract(self, **values: Any) -> Result:
        return self.deposits.create_contract(**values)

    def update_deposit_contract(self, contract_id: str, **values: Any) -> Result:
        return self.deposits.update_contract(contract_id, **values)

    def delete_deposit_contract(self, contract_id: str) -> Result:
        return self.deposits.delete_contract(contract_id)

    def update_deposit_term(self, term_id: str, **values: Any) -> Result:
        return self.deposits.update_term(term_id, **values)

    def list_deposit_pending(self) -> list[dict[str, Any]]:
        result = self.deposits.list_pending()
        return list(result.details.get("events", []))

    def confirm_deposit_event(
        self, event_id: str, *, actual_amount_minor: int | None = None
    ) -> Result:
        return self.deposits.confirm(event_id, actual_amount_minor=actual_amount_minor)

    def skip_deposit_event(self, event_id: str) -> Result:
        return self.deposits.skip(event_id)

    def generate_due(self) -> Result:
        """定期收支與定存一起產生。**單一收件匣**：使用者不該需要知道待確認來自哪個子系統。"""
        result = self.automation.generate_due()
        deposits = self.deposits.generate_due()
        if not result.success:
            return result
        merged = dict(result.details)
        merged["deposit_generated"] = deposits.details.get("generated", 0)
        # 收件匣靠這個值決定要不要浮出「還有更多漏期」那一行。
        self.generation_has_more = bool(merged.get("has_more"))
        return Result.ok(result.message, details=merged, correlation_id=result.correlation_id)

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
