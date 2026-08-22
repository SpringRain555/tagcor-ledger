"""controller 的共同基底：服務接線、啟動任務，以及所有 section 共用的小工具。

**每一個 section 都繼承這裡，section 之間不互相繼承** —— 唯一的例外是
`overview.py`，它是聚合層，理由寫在那個檔案裡。這條紀律跟 `stores/` 是同一條：
`LedgerStore` 底下六個 store 也是各自繼承 `StoreBase`、彼此不呼叫對方的方法。
"""

from __future__ import annotations

from typing import Any

from tagcor_ledger.app.path_settings import PathSettingsService
from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.application.automation import AutomationService
from tagcor_ledger.application.balance import BalanceSnapshotService
from tagcor_ledger.application.catalogs import AccountService, CategoryService
from tagcor_ledger.application.deposits import DepositService
from tagcor_ledger.application.diagnostics import DiagnosticsService
from tagcor_ledger.application.reference import ReferenceLibrary
from tagcor_ledger.application.result import Result
from tagcor_ledger.application.settings import SettingsService
from tagcor_ledger.application.transaction_service import (
    AddTransaction,
    AddTransfer,
    ListTransactions,
    ReplaceTransfer,
    UpdateTransaction,
    VoidTransaction,
)
from tagcor_ledger.infrastructure.maintenance import MaintenanceService
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


class ControllerBase:
    """持有 `AppPaths` 與全部 service，並提供 section 共用的解包工具。"""

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.path_settings = PathSettingsService()
        self._wire_services()
        self._run_startup_tasks()

    def _wire_services(self) -> None:
        """（重）建全部 service。

        **換資料路徑、還原備份、重製之後都要重跑一次** —— 每個 service 都握著一份
        `AppPaths`，不重接的話它們會繼續讀舊位置的資料庫。
        """
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

    @staticmethod
    def _rows(result: Result, key: str) -> list[dict[str, Any]]:
        """把 `Result.details[key]` 那份清單拿出來給頁面。

        service 一律回 `Result`（成功／失敗／錯誤碼），但列表頁要的只是那幾列 ——
        `list(result.details.get(key, []))` 這一句以前在 controller 裡出現 12 次。
        收成一個地方之後，「查不到 key 時給空清單」這個決定也只寫在一處。
        """
        return list(result.details.get(key, []))
