"""資料路徑：讀目前設定、驗證新設定、必要時把資料庫搬過去。

**這一段是整個 controller 裡最危險的地方** —— 搞砸的後果是「下次啟動看起來像資料
全部消失」。順序不可調換的理由寫在 `save_path_settings()` 裡。
"""

from __future__ import annotations

from pathlib import Path
import sqlite3

from tagcor_ledger.app.path_settings import (
    PathSettingsError,
    data_root_of,
    validate_path_settings,
)
from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.application.failures import failure
from tagcor_ledger.application.result import Result
from tagcor_ledger.domain.models import SystemPathSettings
from tagcor_ledger.infrastructure.database import connect_database
from tagcor_ledger.ui.controller.wiring import ControllerBase


class DataPathSection(ControllerBase):
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
