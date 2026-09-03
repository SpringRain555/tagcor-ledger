"""應用程式日誌。

**日誌不記金額，也不記備註。** 只記操作名稱、錯誤碼、`correlation_id` 與時間。

這不是隱私潔癖，是為了讓日誌**可以直接交出去**：出問題時要能把 `app.log` 貼給別人看
而不用先逐行檢查有沒有洩漏花了多少錢、買了什麼。一旦日誌裡有金額，它就變成第二份帳本，
而且是沒有加密、會被複製到各種地方的那一份。

`tests/integration/test_logging_privacy.py` 會實際跑一輪操作再掃日誌檔，確認金額與備註沒有進去。

## 為什麼日誌路徑要分兩段決定

日誌要寫到哪，是由 `system_paths.json` 決定的 —— 但**啟動失敗最常見的原因就是那個檔案
壞了或它指的磁碟不在**。如果日誌只肯寫到那個位置，最需要紀錄的那次失敗就正好沒有紀錄。

所以：能解析出 `AppPaths` 就寫 `logs/app.log`；解析不出來就退回 `fallback_log_dir()`，
它只看作業系統的標準位置，不看任何專案設定。
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from platformdirs import user_log_dir


LOGGER_NAME = "tagcor_ledger"
LOG_FILE_NAME = "app.log"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 5

_HANDLER_TAG = "tagcor_ledger.managed"


def fallback_log_dir() -> Path:
    """不依賴 `system_paths.json` 的日誌位置，給「設定檔本身壞掉」時用。"""
    from tagcor_ledger.app.paths import APP_AUTHOR, APP_NAME

    return Path(user_log_dir(APP_NAME, APP_AUTHOR))


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(LOGGER_NAME if name is None else f"{LOGGER_NAME}.{name}")


def configure_logging(log_dir: Path, *, level: int = logging.INFO) -> Path | None:
    """設定檔案日誌，回傳實際寫入的檔案路徑。

    寫不進去時**不丟例外** —— 記不了日誌是遺憾，不是不能記帳的理由。此時回傳 `None`，
    只保留 stderr 輸出。
    """
    logger = get_logger()
    logger.setLevel(level)
    logger.propagate = False
    _remove_managed_handlers(logger)

    stream = logging.StreamHandler()
    stream.setFormatter(_formatter())
    _mark(stream)
    logger.addHandler(stream)

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / LOG_FILE_NAME
        # encoding="utf-8" 寫出來沒有 BOM，符合專案的「給其他工具讀的檔案不加 BOM」。
        handler = RotatingFileHandler(
            log_path,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        return None

    handler.setFormatter(_formatter())
    _mark(handler)
    logger.addHandler(handler)
    return log_path


def current_log_path() -> Path | None:
    for handler in get_logger().handlers:
        if isinstance(handler, RotatingFileHandler):
            return Path(handler.baseFilename)
    return None


def log_result(action: str, result: object, *, logger: logging.Logger | None = None) -> None:
    """記錄一個 use case 的結果。

    **只取 `success`／`error_code`／`correlation_id`。** 刻意不碰 `details` 與 `message` ——
    `details` 裝的正是金額、帳戶名稱與備註，而 `message` 有時會把 `reason` 一起帶進來。
    """
    target = logger or get_logger("result")
    success = bool(getattr(result, "success", False))
    correlation_id = str(getattr(result, "correlation_id", ""))
    if success:
        target.info("%s ok corr=%s", action, correlation_id)
        return
    target.warning(
        "%s failed code=%s corr=%s",
        action,
        getattr(result, "error_code", None),
        correlation_id,
    )


def _formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )


def _mark(handler: logging.Handler) -> None:
    setattr(handler, _HANDLER_TAG, True)


def _remove_managed_handlers(logger: logging.Logger) -> None:
    """只移除自己裝的 handler —— 測試框架或宿主程式裝的不要動。"""
    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_TAG, False):
            logger.removeHandler(handler)
            handler.close()
