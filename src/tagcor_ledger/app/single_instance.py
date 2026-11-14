"""TagCor Ledger 的單一實例政策與共用鎖機制轉接層。"""

from __future__ import annotations

from pathlib import Path
from types import TracebackType

from local_qt_app.single_instance import (
    AlreadyRunningError,
    LockUnavailableError,
    SingleInstanceGuard as _SharedSingleInstanceGuard,
)


LOCK_FILE_NAME = "ledger.lock"
__all__ = ["AlreadyRunningError", "LOCK_FILE_NAME", "SingleInstanceGuard"]


class SingleInstanceGuard:
    """把共用鎖綁到帳本資料夾，並保留 TagCor 的錯誤訊息。"""

    def __init__(self, ledger_dir: Path, *, timeout: float = 0.5) -> None:
        self._guard = _SharedSingleInstanceGuard(
            ledger_dir, lock_name=LOCK_FILE_NAME, timeout=timeout
        )
        self.lock_path = self._guard.lock_path

    def acquire(self) -> None:
        try:
            self._guard.acquire()
        except LockUnavailableError as exc:
            # 保留舊版供啟動錯誤分類與日誌使用的繁中訊息。
            raise OSError(f"無法建立鎖檔 {exc.path}") from exc

    def release(self) -> None:
        self._guard.release()

    def __enter__(self) -> "SingleInstanceGuard":
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
