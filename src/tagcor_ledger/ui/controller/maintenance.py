"""備份、還原、重製、匯出、診斷與法規庫 —— 一年看兩次的那一組。

**還原與重製之後一定要 `_wire_services()`。** 那兩個動作換掉了資料庫檔案本身，
不重接的話所有 service 還握著舊連線的路徑。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tagcor_ledger.application.failures import failure
from tagcor_ledger.application.reference import ReferenceEntry
from tagcor_ledger.application.result import Result
from tagcor_ledger.ui.controller.wiring import ControllerBase


class MaintenanceSection(ControllerBase):
    # --- 備份 ---------------------------------------------------------------

    def create_backup(self) -> Path:
        return self.maintenance.create_backup()

    def list_backups(self) -> list[dict[str, Any]]:
        return self.maintenance.list_backups()

    def validate_backup(self, path: Path) -> dict[str, Any]:
        return self.maintenance.validate_backup(path)

    def restore_backup(self, path: Path, *, create_backup_first: bool = False) -> None:
        self.maintenance.restore_backup(path, create_backup_first=create_backup_first)
        self._wire_services()

    def delete_backup(self, path: Path) -> Result:
        """刪除一份備份。**回 `Result` 而不是丟例外**，因為每一種失敗都有話要說。

        同一頁上的建立／還原是丟例外由頁面 `except` 接（那是既有的形狀），
        但刪除的三種失敗（資料夾不見了、不在備份資料夾底下、檔案被鎖住）
        各自要給不同的建議，走 `failure()` 才拿得到那些句子。
        """
        try:
            self.maintenance.delete_backup(path)
        except (ValueError, OSError) as exc:
            return failure(
                exc,
                fallback_code="BACKUP_DELETE_FAILED",
                fallback_message=(
                    "備份刪不掉。可能是檔案正被其他程式使用（防毒、雲端同步、"
                    "另一個開著的視窗），或是資料夾沒有寫入權限。"
                ),
            )
        return Result.ok("備份已刪除。")

    # --- 重製與匯出 ---------------------------------------------------------

    def reset_ledger(self, *, create_backup_first: bool = False) -> None:
        self.maintenance.reset_ledger(create_backup_first=create_backup_first)
        self._wire_services()

    def export_csv(self) -> Path:
        return self.maintenance.export_transactions_csv()

    # --- 診斷 ---------------------------------------------------------------

    def export_diagnostics(self) -> Result:
        return self.diagnostics.export()

    def ledger_counts(self) -> dict[str, int]:
        """各表筆數。給重製確認框用 —— 不可逆的操作要講得出「會失去什麼」。"""
        return self.diagnostics.counts()

    # --- 法規庫（唯讀） ------------------------------------------------------

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
