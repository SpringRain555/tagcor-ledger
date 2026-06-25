"""Application preferences stored in SQLite."""

from __future__ import annotations

import sqlite3

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.application.result import Result
from tagcor_ledger.domain.models import ApplicationSettings
from tagcor_ledger.infrastructure.clock import now_iso, today_taipei
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
            startup_backup=values.get("startup_backup", "daily"),
        )

    def update(self, settings: ApplicationSettings) -> Result:
        if settings.default_entry_type not in {"income", "expense", "transfer"}:
            return Result.fail("SETTINGS_ENTRY_TYPE_INVALID", "預設流向無效。")
        if settings.transactions_page_size not in {20, 50, 100}:
            return Result.fail("SETTINGS_PAGE_SIZE_INVALID", "每頁筆數只能是 20、50 或 100。")
        if settings.startup_backup not in {"never", "daily", "always"}:
            return Result.fail("SETTINGS_BACKUP_INVALID", "啟動備份設定無效。")
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
                    "startup_backup": settings.startup_backup,
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
            return Result.fail(
                "SETTINGS_SAVE_FAILED",
                "設定無法儲存。",
                details={"reason": str(exc)},
            )

    def startup_backup_due(self) -> bool:
        settings = self.get()
        if settings.startup_backup == "never":
            return False
        if settings.startup_backup == "always":
            return True
        with connect_database(self.paths.database_path) as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = 'last_startup_backup_date'"
            ).fetchone()
        return row is None or str(row["value"]) != today_taipei().isoformat()

    def mark_startup_backup(self) -> None:
        with database_transaction(self.paths.database_path) as connection:
            connection.execute(
                """
                INSERT INTO settings(key, value, updated_at) VALUES (
                    'last_startup_backup_date', ?, ?
                )
                ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (today_taipei().isoformat(), now_iso()),
            )
