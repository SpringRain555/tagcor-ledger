"""資料放在哪裡：沒有指標檔時去哪裡找帳本、什麼時候要問使用者（ADR-0018）。

## 四步，每次啟動都走一次

1. **指標檔 `system_paths.json` 在** → 照它。它是「系統設定 → 資料路徑」或第一次啟動選了
   「其他位置…」寫的。
2. **`<程式資料夾>\\userdata` 裡有帳本** → 用它。**這一種不寫指標檔**：指標檔記的是絕對路徑，
   整個程式資料夾搬走或帶到別台電腦，它就指錯地方；不寫的話每次都從程式自己的位置往下找，
   搬到哪裡都找得到。
3. **使用者資料夾（`%LOCALAPPDATA%\\TagCor\\TagCorLedger`）裡有帳本** → 用它。這是 ADR-0018
   之前唯一的預設位置，舊使用者走的就是這一步 —— 跟以前一模一樣，不會被問。
4. **都沒有** → 第一次啟動。GUI 跳出對話框問（`ui/first_run_dialog.py`）；CLI 照舊回報使用者
   資料夾的路徑，不建立任何帳本。

有指標檔就停在第 1 步，跟以前完全一樣；沒有的話也只是多看幾個檔案在不在。

**「問過了沒」不另外記。** 按下「確定」當場就建出帳本，下一次第 2 或第 3 步就找到它 ——
選的結果本身就是證據。另外記一個旗標，就是第二份會跟檔案對不上的事實（旗標說問過了，
帳本卻被刪了）。

**看帳本檔，不看資料夾。** 啟動器的預檢在使用者選之前就會在使用者資料夾建 `logs\\`；
看資料夾在不在，會把第一次啟動誤判成「已經選過」。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from tagcor_ledger.app import path_settings
from tagcor_ledger.app.path_settings import PathSettingsError, validate_path_settings
from tagcor_ledger.domain.models import SystemPathSettings

PROGRAM_DATA_FOLDER = "userdata"
"""「放在程式資料夾裡」時的資料根：`<程式資料夾>\\userdata`。`.gitignore` 整個忽略它 ——
匯出的交易 CSV 不是 `*.sqlite3`，只靠副檔名的規則擋不到。"""

LEDGER_DIR_NAMES = ("data", "ledger")
"""資料根底下放帳本的資料夾，只認這兩個名字。

`data` 是新建資料根的布局（`path_settings.layout_for()`）；`ledger` 是
`docs/architecture/storage-layout.md`「一般使用」那一種，自己指定過路徑的人多半是它。
只認名字、不往下亂找：備份資料夾裡每一份都有一個 `ledger.sqlite3`，找深一層就會把備份當成帳本。
"""

LEDGER_FILE_NAME = "ledger.sqlite3"


class LocationSource(StrEnum):
    """這一次的資料位置是怎麼決定的。`--json` 的 `data_location` 印的就是它。"""

    OVERRIDE = "override"
    """`--data-dir` 或 `TAGCOR_LEDGER_DATA_DIR`：開發與測試用，永遠不問。"""
    POINTER = "pointer"
    PROGRAM_FOLDER = "program_folder"
    USER_FOLDER = "user_folder"
    CHOOSE_ON_FIRST_RUN = "choose_on_first_run"


class LocationChoice(StrEnum):
    """第一次啟動對話框的三個選項。"""

    PROGRAM_FOLDER = "program_folder"
    USER_FOLDER = "user_folder"
    OTHER = "other"


@dataclass(frozen=True)
class DataLocation:
    """決定好的位置：從哪裡來、三個路徑是什麼。"""

    source: LocationSource
    settings: SystemPathSettings


@dataclass(frozen=True)
class OtherFolder:
    """「其他位置…」挑到的資料夾，按下確定之前先看一眼。

    `settings` 是 `None` 表示不能用，原因在 `error_code`（`application/failures.py` 有中文）。
    """

    root: Path
    settings: SystemPathSettings | None
    has_ledger: bool
    error_code: str | None


def program_root() -> Path | None:
    """程式資料夾，也就是 repo 的根目錄。不是從原始碼資料夾執行（例如裝進 site-packages）就回 `None`。

    從這個檔案的位置往上推：`<根>\\src\\tagcor_ledger\\app\\data_location.py`。推出來的位置
    還要真的有 `pyproject.toml` 才算 —— 對不上就不猜，對話框會把「程式資料夾」那個選項停用。
    """
    package_dir = Path(__file__).resolve().parents[1]
    source_dir = package_dir.parent
    root = source_dir.parent
    if source_dir.name != "src" or not (root / "pyproject.toml").is_file():
        return None
    return root


def program_data_root() -> Path | None:
    """`<程式資料夾>\\userdata`；沒有程式資料夾就是 `None`。"""
    root = program_root()
    return root / PROGRAM_DATA_FOLDER if root is not None else None


def find_ledger_dir(root: Path) -> Path | None:
    """`root` 底下放著帳本檔的那個資料夾（`data` 或 `ledger`），沒有就回 `None`。"""
    for name in LEDGER_DIR_NAMES:
        candidate = root / name
        if (candidate / LEDGER_FILE_NAME).is_file():
            return candidate
    return None


def existing_layout(root: Path) -> SystemPathSettings | None:
    """`root` 底下已經有帳本的話，它的三個路徑；沒有回 `None`。備份一律是 `backups`。"""
    ledger_dir = find_ledger_dir(root)
    if ledger_dir is None:
        return None
    return SystemPathSettings(ledger_dir=ledger_dir, backup_dir=root / "backups", data_root=root)


def detect_data_location() -> DataLocation:
    """模組說明的四步。**只看、不建**：這裡不建任何資料夾或檔案。"""
    service = path_settings.PathSettingsService()
    if service.settings_path.is_file():
        return DataLocation(LocationSource.POINTER, service.load())
    program = program_data_root()
    if program is not None:
        found = existing_layout(program)
        if found is not None:
            return DataLocation(LocationSource.PROGRAM_FOLDER, found)
    user = path_settings.default_data_root()
    found = existing_layout(user)
    if found is not None:
        return DataLocation(LocationSource.USER_FOLDER, found)
    # 還沒選：路徑先照舊指著使用者資料夾 —— 日誌與啟動器的標記檔需要一個落腳處，
    # 而那兩樣都不是帳本，不會讓下一次被誤判成「選過了」。
    return DataLocation(LocationSource.CHOOSE_ON_FIRST_RUN, path_settings.layout_for(user))


def inspect_other_folder(folder: Path) -> OtherFolder:
    """「其他位置…」挑到的資料夾能不能用、裡面有沒有帳本。只看、不建。"""
    root = folder.expanduser().resolve()
    try:
        _require_usable_other_folder(root)
    except PathSettingsError as exc:
        return OtherFolder(root=root, settings=None, has_ledger=False, error_code=str(exc))
    existing = existing_layout(root)
    if existing is not None:
        return OtherFolder(root=root, settings=existing, has_ledger=True, error_code=None)
    return OtherFolder(
        root=root, settings=path_settings.layout_for(root), has_ledger=False, error_code=None
    )


def _require_usable_other_folder(root: Path) -> None:
    """不能當資料根就丟 `PathSettingsError`。三種情形的中文在 `application/failures.py`。"""
    if root.parent == root:
        # 整顆磁碟：`data`、`backups`、`logs` 這些資料夾會直接長在磁碟根目錄。
        raise PathSettingsError("DATA_ROOT_IS_DRIVE_ROOT")
    program = program_root()
    if program is not None and root.is_relative_to(program):
        # 只有 `userdata` 被 git 忽略。挑程式資料夾裡別的地方，匯出的交易 CSV 就可能被 commit。
        raise PathSettingsError("DATA_ROOT_INSIDE_PROGRAM_FOLDER")
    if any(find_ledger_dir(parent) is not None for parent in root.parents):
        # 在一份既有的資料根裡面：放帳本檔的那一層（`ledger`／舊的 `data`）、`backups` 或更深的地方都算。
        # 照樣用下去會在真的那份裡面另建一本空的，指標檔指過去之後真的那本反而沒被接上。
        # 2026-10-11 之前只擋放帳本檔的那一層（`DATA_ROOT_IS_LEDGER_DIR`）；上游 CONVENTIONS §11 統一成這一條。
        raise PathSettingsError("DATA_ROOT_INSIDE_DATA_ROOT")


def prepare_location(choice: LocationChoice, *, other_folder: Path | None = None) -> DataLocation:
    """把選擇變成真的位置：建好資料夾、確認寫得進去；「其他位置」另外寫指標檔。

    **帳本不在這裡建**，那是 `initialize_database()` 的事，呼叫端接著就會做。
    失敗丟 `PathSettingsError`（訊息是錯誤碼）或 `OSError`，指標檔不會被寫。
    """
    if choice is LocationChoice.OTHER:
        if other_folder is None:
            raise ValueError("other_folder is required for LocationChoice.OTHER")
        root = other_folder.expanduser().resolve()
        _require_usable_other_folder(root)
        settings = existing_layout(root) or path_settings.layout_for(root)
        # 驗證、建資料夾、原子寫入指標檔 —— 跟「系統設定 → 資料路徑」同一條路。
        saved = path_settings.PathSettingsService().save(settings)
        return DataLocation(LocationSource.POINTER, saved)
    if choice is LocationChoice.PROGRAM_FOLDER:
        program = program_data_root()
        if program is None:
            raise ValueError("the program folder is not available")
        root, source = program, LocationSource.PROGRAM_FOLDER
    else:
        root, source = path_settings.default_data_root(), LocationSource.USER_FOLDER
    settings = existing_layout(root) or path_settings.layout_for(root)
    return DataLocation(source, validate_path_settings(settings, create=True))
