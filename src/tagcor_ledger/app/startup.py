"""把啟動失敗的例外翻成使用者可以照著做的繁中說明。

分支清單是 `docs/architecture/state-machines.md` §6 的六種結果。在這之前只有「正常啟動」
被實作，其餘五種會直接把 traceback 丟到 console —— 而從捷徑或一鍵啟動器開的時候
根本沒有 console，所以實際症狀是「視窗沒出現、沒有訊息、沒有紀錄」。

**每個分支都要給可執行的下一步。** 「發生未預期的錯誤」對使用者毫無幫助；
「設定檔在這個位置，刪掉它會退回預設路徑，不會損失帳務資料」才有。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from tagcor_ledger.app.path_settings import PathSettingsError, default_settings_path
from tagcor_ledger.app.single_instance import AlreadyRunningError


@dataclass(frozen=True)
class StartupFailure:
    """一種啟動失敗。`error_code` 一律用位置參數傳，錯誤碼守門測試靠這個抓得到。"""

    error_code: str
    title: str
    message: str
    detail: str = ""

    def as_text(self) -> str:
        parts = [self.title, "", self.message]
        if self.detail:
            parts += ["", "技術細節：", self.detail]
        return "\n".join(parts)


def classify_startup_error(exc: BaseException) -> StartupFailure:
    """把啟動階段的例外對應到 §6 的分支。認不出來的一律給通用分支，不要吞掉。"""
    if isinstance(exc, AlreadyRunningError):
        return _already_running()
    if isinstance(exc, PathSettingsError):
        return _path_settings(exc)
    if isinstance(exc, RuntimeError) and str(exc) == "DATABASE_SCHEMA_TOO_NEW":
        return _schema_too_new()
    if isinstance(exc, sqlite3.DatabaseError):
        return _database_error(exc)
    if isinstance(exc, OSError):
        return _filesystem_error(exc)
    return StartupFailure(
        "STARTUP_FAILED",
        "程式無法啟動",
        "發生未預期的問題。請把日誌檔一併提供，裡面有這次啟動的紀錄（不含金額與備註）。",
        f"{type(exc).__name__}: {exc}",
    )


def _already_running() -> StartupFailure:
    return StartupFailure(
        "ALREADY_RUNNING",
        "程式已經開著了",
        "同一份帳本已經有一個視窗在使用中，請切換到那個視窗。\n"
        "如果找不到視窗，可能是上一次沒有正常關閉；等幾秒後再開一次即可。",
    )


def _path_settings(exc: PathSettingsError) -> StartupFailure:
    code = str(exc)
    settings_path = default_settings_path()
    if code == "SYSTEM_PATH_SETTINGS_INVALID":
        return StartupFailure(
            "SYSTEM_PATH_SETTINGS_INVALID",
            "路徑設定檔損毀",
            f"設定檔內容不是合法的 JSON：\n{settings_path}\n\n"
            "**把這個檔案刪掉就會退回預設路徑，不會損失任何帳務資料** —— "
            "帳本本身是另一個檔案，設定檔只記錄它在哪裡。\n"
            "刪除後重新開啟程式，再到「系統設定 → 資料路徑」指回原本的資料夾。",
        )
    if code == "PATH_OUTSIDE_DATA_ROOT":
        return StartupFailure(
            "PATH_OUTSIDE_DATA_ROOT",
            "資料路徑設定越界",
            f"記帳資料路徑或備份路徑不在資料根目錄底下。\n設定檔：{settings_path}\n\n"
            "可以直接編輯該檔案讓三個路徑一致，或把它刪掉退回預設路徑後重新設定。",
            code,
        )
    return StartupFailure(
        "SYSTEM_PATH_SETTINGS_INVALID",
        "路徑設定無法使用",
        f"設定檔：{settings_path}\n刪掉它會退回預設路徑，不會損失帳務資料。",
        code,
    )


def _schema_too_new() -> StartupFailure:
    return StartupFailure(
        "DATABASE_SCHEMA_TOO_NEW",
        "資料庫版本比程式新",
        "這份帳本是用比較新的版本建立的。\n\n"
        "**請不要繼續使用這個版本開啟它** —— 用舊程式寫新結構的資料庫會弄壞資料。\n"
        "請先把程式更新到最新版本再開啟。",
    )


def _database_error(exc: sqlite3.DatabaseError) -> StartupFailure:
    text = str(exc).lower()
    if "locked" in text or "busy" in text:
        return StartupFailure(
            "DATABASE_LOCKED",
            "帳本正被其他程式使用",
            "資料庫被鎖住了。請確認沒有另一個視窗開著，也沒有備份或同步軟體正在讀寫這個檔案，"
            "然後再開一次。",
            str(exc),
        )
    if "malformed" in text or "not a database" in text or "corrupt" in text:
        return StartupFailure(
            "DATABASE_CORRUPT",
            "帳本檔案損毀",
            "資料庫無法讀取。請到「系統設定 → 備份與還原」用最近一次可用的備份還原。\n"
            "**先不要覆蓋現有檔案** —— 把它另存一份，損毀的檔案有時仍能救回部分資料。",
            str(exc),
        )
    return StartupFailure(
        "DATABASE_UNAVAILABLE",
        "帳本無法開啟",
        "資料庫無法開啟。請確認檔案存在且沒有被其他程式佔用。",
        str(exc),
    )


def _filesystem_error(exc: OSError) -> StartupFailure:
    path = getattr(exc, "filename", None)
    location = f"\n位置：{path}" if path else ""
    if isinstance(exc, PermissionError):
        return StartupFailure(
            "DATA_DIRECTORY_NOT_WRITABLE",
            "資料夾沒有寫入權限",
            f"程式無法寫入指定的資料夾。{location}\n\n"
            "請確認該資料夾不是唯讀，也沒有被防毒軟體鎖住。",
            f"{type(exc).__name__}: {exc}",
        )
    if getattr(exc, "errno", None) == 28:
        return StartupFailure(
            "DISK_FULL",
            "磁碟空間不足",
            f"磁碟已滿，無法寫入。{location}\n\n請清出空間後再開啟程式。",
            f"{type(exc).__name__}: {exc}",
        )
    return StartupFailure(
        "DATA_DIRECTORY_UNAVAILABLE",
        "找不到資料夾",
        f"指定的資料夾無法使用。{location}\n\n"
        "最常見的原因是**外接磁碟沒有連接**，或資料夾被搬走、改名了。\n"
        "接上磁碟後重新開啟即可；若資料夾真的搬走了，"
        "可以先刪掉路徑設定檔退回預設路徑，再到「系統設定 → 資料路徑」指到新位置。",
        f"{type(exc).__name__}: {exc}",
    )


def resolve_log_dir(paths_log_dir: Path | None) -> Path:
    """有 `AppPaths` 就用它的 `logs/`，沒有就退回不依賴專案設定的位置。"""
    from tagcor_ledger.app.logging_setup import fallback_log_dir

    return paths_log_dir if paths_log_dir is not None else fallback_log_dir()
