"""刪除備份，以及讓它一度不可能的那個連線洩漏。

## 為什麼這兩件事在同一個檔案

`sqlite3.Connection.__exit__` 只做 commit／rollback，**不 close**。「函式結束時
refcount 會把它收掉」這個假設在 Windows 上實測不成立 —— 檔案會一直被鎖住。

而 `validate_backup()` 要開資料庫讀 schema 版本，`list_backups()` 又對每一份都跑它，
維護頁每次 refresh 都呼叫 `list_backups()`。所以連線沒關的話，**開著程式看一眼備份
清單，那些備份就全都刪不掉了** —— 刪除功能等於整個不能用。

也就是說：不先修連線，這個功能寫出來也是壞的。兩件事是同一個使用情境的兩半。

拿掉 `contextlib.closing` 之後，這個檔案十條裡有八條會紅。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.infrastructure.maintenance import MaintenanceService
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


@pytest.fixture
def maintenance(tmp_path: Path) -> MaintenanceService:
    paths = resolve_app_paths(tmp_path / "ledger")
    LedgerStore(paths)
    return MaintenanceService(paths)


def _break_checksum(backup_dir: Path) -> None:
    (backup_dir / "ledger.sqlite3").write_bytes(b"not a database at all")


def test_a_good_backup_can_be_deleted(maintenance: MaintenanceService) -> None:
    backup_dir = maintenance.create_backup(reason="test")
    assert backup_dir.is_dir()

    maintenance.delete_backup(backup_dir)

    assert not backup_dir.exists()
    assert maintenance.list_backups() == []


def test_a_broken_backup_can_be_deleted(maintenance: MaintenanceService) -> None:
    """**壞掉的備份也要刪得掉** —— 那是這個功能的主要用途。

    如果 `delete_backup` 先驗證再刪，壞備份就永遠清不掉，而清單上會一直掛著
    一列「不可用」。
    """
    backup_dir = maintenance.create_backup(reason="test")
    _break_checksum(backup_dir)
    assert maintenance.validate_backup(backup_dir)["error_code"] == "BACKUP_CHECKSUM_MISMATCH"

    maintenance.delete_backup(backup_dir)

    assert not backup_dir.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="檔案鎖是 Windows 才有的行為")
def test_a_failed_restore_does_not_lock_the_backup_it_just_rejected(
    maintenance: MaintenanceService,
) -> None:
    """還原失敗之後，那份壞備份必須刪得掉。**這是最痛的那一種情況。**

    使用者剛被告知「這份備份壞了，請改用別的」，下一個動作就是想把它清掉。
    舊的 `with sqlite3.connect(...)` 不 close，`shutil.rmtree` 會撞 `WinError 32`，
    於是壞備份會永遠掛在清單上。

    這裡刻意把例外留在手上（`caught.value`），重現 UI 裡「錯誤訊息還開著、
    使用者接著按刪除」的那一刻 —— 那時 traceback 還抓著整條呼叫鏈的 frame。
    """
    backup_dir = maintenance.create_backup(reason="test")
    _break_checksum(backup_dir)

    with pytest.raises(ValueError) as caught:
        maintenance.restore_backup(backup_dir)
    held = caught.value  # 抓住 traceback，重現真實 UI 裡例外還在手上的那一刻

    maintenance.delete_backup(backup_dir)

    assert not backup_dir.exists()
    assert str(held) == "BACKUP_CHECKSUM_MISMATCH"


@pytest.mark.skipif(sys.platform != "win32", reason="檔案鎖是 Windows 才有的行為")
def test_listing_backups_does_not_lock_them(maintenance: MaintenanceService) -> None:
    """`list_backups()` 會對每一份跑 `validate_backup()`（要開資料庫讀版本）。

    維護頁每次 refresh 都呼叫它，所以連線沒關的話，開著程式看一看清單，
    那些備份就都刪不掉了。
    """
    first = maintenance.create_backup(reason="test")
    second = maintenance.create_backup(reason="test")
    assert len(maintenance.list_backups()) == 2

    maintenance.delete_backup(first)
    maintenance.delete_backup(second)

    assert maintenance.list_backups() == []


def test_deleting_refuses_anything_outside_the_backup_directory(
    maintenance: MaintenanceService, tmp_path: Path
) -> None:
    """**這道檢查是這個方法能存在的前提。** 它收路徑而且做遞迴刪除。"""
    outsider = tmp_path / "not_a_backup"
    outsider.mkdir()
    (outsider / "important.txt").write_text("keep me", encoding="utf-8")

    with pytest.raises(ValueError) as caught:
        maintenance.delete_backup(outsider)

    assert str(caught.value) == "BACKUP_OUTSIDE_BACKUP_DIR"
    assert (outsider / "important.txt").is_file()


def test_deleting_refuses_the_backup_directory_itself(
    maintenance: MaintenanceService,
) -> None:
    """備份資料夾**本身**不是一份備份。刪掉它等於一次清光全部。"""
    maintenance.create_backup(reason="test")
    root = maintenance.paths.backup_dir

    with pytest.raises(ValueError) as caught:
        maintenance.delete_backup(root)

    assert str(caught.value) == "BACKUP_OUTSIDE_BACKUP_DIR"
    assert root.is_dir()
    assert len(maintenance.list_backups()) == 1


def test_deleting_something_already_gone_says_so(maintenance: MaintenanceService) -> None:
    backup_dir = maintenance.create_backup(reason="test")
    maintenance.delete_backup(backup_dir)

    with pytest.raises(FileNotFoundError) as caught:
        maintenance.delete_backup(backup_dir)

    assert str(caught.value) == "BACKUP_NOT_FOUND"


def test_a_backup_missing_its_database_can_still_be_deleted(
    maintenance: MaintenanceService,
) -> None:
    """只剩清單檔的殘骸也要清得掉 —— 它在清單上是「檔案缺少」那一列。"""
    backup_dir = maintenance.create_backup(reason="test")
    (backup_dir / "ledger.sqlite3").unlink()
    assert maintenance.validate_backup(backup_dir)["error_code"] == "BACKUP_FILES_MISSING"

    maintenance.delete_backup(backup_dir)

    assert not backup_dir.exists()


def test_a_backup_with_a_broken_manifest_can_still_be_deleted(
    maintenance: MaintenanceService,
) -> None:
    backup_dir = maintenance.create_backup(reason="test")
    (backup_dir / "backup_manifest.json").write_text("{ not json", encoding="utf-8")
    assert maintenance.validate_backup(backup_dir)["error_code"] == "BACKUP_MANIFEST_INVALID"

    maintenance.delete_backup(backup_dir)

    assert not backup_dir.exists()


def test_deleting_one_backup_leaves_the_others_alone(
    maintenance: MaintenanceService,
) -> None:
    keep = maintenance.create_backup(reason="test")
    drop = maintenance.create_backup(reason="test")
    kept_manifest = json.loads((keep / "backup_manifest.json").read_text(encoding="utf-8"))

    maintenance.delete_backup(drop)

    assert keep.is_dir()
    remaining = maintenance.list_backups()
    assert len(remaining) == 1
    assert remaining[0]["valid"] is True
    assert (
        json.loads((keep / "backup_manifest.json").read_text(encoding="utf-8"))
        == kept_manifest
    )
