"""單一實例守門。

WAL 讓兩個實例同時寫不會壞資料，所以這**不是**資料完整性的防護。它防的是困惑：
兩個視窗各自快取餘額與待確認數量，在 A 存了一筆之後 B 顯示的數字就是舊的，而且兩邊
都會跳「今天還沒盤點」的提醒。使用者會以為程式算錯帳。

用 advisory lock（`filelock`）而不是強制鎖：
- 程式被強制結束時，鎖檔會留下但 OS 已經釋放檔案鎖，所以**下次啟動照樣拿得到**，
  不需要使用者手動刪檔。殘留的鎖檔本身無害。
- 拿不到鎖時**不強行搶**。真的想開第二個實例（例如指向另一個資料夾）的人，
  會用 `--data-dir` 指到別的地方，那裡的鎖是另一支。

鎖檔放在 `ledger_dir`，所以「同一份帳本」才互斥；不同資料夾各自獨立。
"""

from __future__ import annotations

from pathlib import Path
from types import TracebackType

from filelock import BaseFileLock, FileLock, Timeout


LOCK_FILE_NAME = "ledger.lock"


class AlreadyRunningError(RuntimeError):
    """另一個實例正在使用同一份帳本。"""


class SingleInstanceGuard:
    """context manager：拿不到鎖就丟 `AlreadyRunningError`。

    `timeout` 給一小段而不是 0：程式剛關閉時 OS 釋放檔案鎖可能慢個幾十毫秒，
    立刻重開不該被自己的殘影擋下來。
    """

    def __init__(self, ledger_dir: Path, *, timeout: float = 0.5) -> None:
        self.lock_path = ledger_dir / LOCK_FILE_NAME
        self._timeout = timeout
        self._lock: BaseFileLock | None = None

    def acquire(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(self.lock_path), timeout=self._timeout)
        try:
            lock.acquire()
        except Timeout as exc:
            raise AlreadyRunningError("ALREADY_RUNNING") from exc
        except OSError as exc:
            # 鎖檔所在的資料夾不可寫。這是資料夾的問題，不是「已經在跑」，
            # 讓它往上傳成啟動失敗，不要謊報成第二個實例。
            raise OSError(f"無法建立鎖檔 {self.lock_path}") from exc
        self._lock = lock

    def release(self) -> None:
        if self._lock is not None:
            self._lock.release()
            self._lock = None

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
