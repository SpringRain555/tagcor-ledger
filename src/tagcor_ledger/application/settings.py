"""存在 SQLite 裡的操作偏好（預設帳戶、盤點提醒⋯⋯）。

**資料路徑不在這裡** —— 那是 `app/path_settings.py` 的外部 JSON。
"""

from __future__ import annotations

import sqlite3

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.application.failures import failure
from tagcor_ledger.application.result import Result
from tagcor_ledger.domain.models import ApplicationSettings
from tagcor_ledger.infrastructure.clock import now_iso
from tagcor_ledger.infrastructure.database import connect_database, database_transaction


class SettingsService:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    def get(self) -> ApplicationSettings:
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute("SELECT key, value FROM settings").fetchall()
        values = {str(row["key"]): str(row["value"]) for row in rows}
        return ApplicationSettings(
            default_account_id=values.get("default_account_id", "acct_cash"),
            default_entry_type=values.get("default_entry_type", "expense"),
            transactions_page_size=int(values.get("transactions_page_size", "50")),
            balance_snapshot_reminder=values.get(
                "balance_snapshot_reminder", "true"
            ).lower()
            == "true",
        )

    def update(self, settings: ApplicationSettings) -> Result:
        if settings.default_entry_type not in {"income", "expense", "transfer"}:
            return Result.fail("SETTINGS_ENTRY_TYPE_INVALID", "預設流向不正確。")
        if settings.transactions_page_size not in {20, 50, 100}:
            return Result.fail(
                "SETTINGS_PAGE_SIZE_INVALID",
                "每頁筆數只能是 20、50 或 100。",
            )
        try:
            with database_transaction(self.paths.database_path) as connection:
                account = connection.execute(
                    "SELECT status FROM accounts WHERE account_id = ?",
                    (settings.default_account_id,),
                ).fetchone()
                if account is None or account["status"] != "active":
                    raise ValueError("DEFAULT_ACCOUNT_NOT_ACTIVE")
                timestamp = now_iso()
                values = {
                    "default_account_id": settings.default_account_id,
                    "default_entry_type": settings.default_entry_type,
                    "transactions_page_size": str(settings.transactions_page_size),
                    "balance_snapshot_reminder": (
                        "true" if settings.balance_snapshot_reminder else "false"
                    ),
                }
                for key, value in values.items():
                    connection.execute(
                        """
                        INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
                        ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                            updated_at = excluded.updated_at
                        """,
                        (key, value, timestamp),
                    )
            return Result.ok("設定已儲存。")
        except (ValueError, sqlite3.Error) as exc:
            # `DEFAULT_ACCOUNT_NOT_ACTIVE` 是這裡自己 raise 的（上面幾行），
            # 所以它會被 `failure()` 認出來，不會塌成 `SETTINGS_SAVE_FAILED`。
            return failure(
                exc,
                fallback_code="SETTINGS_SAVE_FAILED",
                fallback_message="設定無法儲存。請匯出診斷資訊回報。",
            )
