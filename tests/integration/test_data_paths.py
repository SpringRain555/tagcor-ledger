"""資料根目錄約束、路徑搬移的原子性，以及 Windows 大小寫語意。

這些測試守的是三件會造成「資料看起來消失」的事：
1. 帳務檔案跑到宣告的資料根目錄外面。
2. 搬移失敗後指標檔已經指向新位置，但資料還在舊位置。
3. 只改大小寫的路徑被當成兩個不同的位置。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tagcor_ledger.app.path_settings import (
    SETTINGS_VERSION,
    PathSettingsError,
    PathSettingsService,
    validate_path_settings,
)
from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.domain.models import SystemPathSettings
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore
from tagcor_ledger.ui.controller import LedgerController


def _settings(root: Path, *, ledger: Path, backup: Path) -> SystemPathSettings:
    return SystemPathSettings(ledger_dir=ledger, backup_dir=backup, data_root=root)


def test_backup_dir_outside_data_root_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "tagcor-ledger"
    with pytest.raises(PathSettingsError) as excinfo:
        validate_path_settings(
            _settings(root, ledger=root / "ledger", backup=tmp_path / "elsewhere" / "backups")
        )
    assert str(excinfo.value) == "PATH_OUTSIDE_DATA_ROOT"


def test_ledger_dir_outside_data_root_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "tagcor-ledger"
    with pytest.raises(PathSettingsError) as excinfo:
        validate_path_settings(
            _settings(root, ledger=tmp_path / "ledger", backup=root / "backups")
        )
    assert str(excinfo.value) == "PATH_OUTSIDE_DATA_ROOT"


def test_data_root_defaults_to_ledger_parent_for_legacy_settings(tmp_path: Path) -> None:
    """沒有 data_root 欄位的舊設定檔仍要能讀，退回 ledger_dir.parent。"""
    settings_path = tmp_path / "system_paths.json"
    settings_path.write_text(
        json.dumps(
            {
                "ledger_dir": str(tmp_path / "root" / "ledger"),
                "backup_dir": str(tmp_path / "root" / "backups"),
            }
        ),
        encoding="utf-8",
    )

    loaded = PathSettingsService(settings_path).load()

    assert loaded.data_root == tmp_path / "root"


def test_save_persists_data_root_and_settings_version(tmp_path: Path) -> None:
    settings_path = tmp_path / "system_paths.json"
    root = tmp_path / "tagcor-ledger"
    service = PathSettingsService(settings_path)

    service.save(_settings(root, ledger=root / "ledger", backup=root / "backups"))

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert payload["settings_version"] == SETTINGS_VERSION
    assert Path(payload["data_root"]) == root
    assert resolve_app_paths(root).export_dir == root / "exports"


def test_failed_move_leaves_settings_and_source_database_untouched(tmp_path: Path) -> None:
    """搬移失敗時，指標檔與舊資料庫都必須原封不動。

    這是本檔案最重要的一個測試：舊版先寫指標檔再搬資料，搬失敗時指標已經指向
    新位置，下次啟動就會在新位置建一個空資料庫，使用者看起來像資料全沒了。
    """
    settings_path = tmp_path / "system_paths.json"
    original_root = tmp_path / "original"
    controller = LedgerController(resolve_app_paths(original_root))
    controller.path_settings = PathSettingsService(settings_path)
    controller.path_settings.save(
        _settings(
            original_root,
            ledger=original_root / "data",
            backup=original_root / "backups",
        )
    )
    before = settings_path.read_text(encoding="utf-8")
    assert controller.submit(
        occurred_at="2026-09-01T10:00:00+08:00",
        entry_type="expense",
        amount="120",
        account_id="acct_cash",
        destination_account_id=None,
        category_id="cat_food_711",
        description="搬移前資料",
    ).success

    # 目標已經有檔案 -> 搬移必定失敗
    next_root = tmp_path / "next"
    (next_root / "ledger").mkdir(parents=True)
    (next_root / "ledger" / "ledger.sqlite3").write_bytes(b"occupied")

    result = controller.save_path_settings(
        ledger_dir=next_root / "ledger",
        backup_dir=next_root / "backups",
        data_root=next_root,
        move_current=True,
    )

    assert not result.success
    assert result.error_code == "PATH_SETTINGS_SAVE_FAILED"
    assert settings_path.read_text(encoding="utf-8") == before
    assert controller.paths.database_path == original_root / "data" / "ledger.sqlite3"
    assert LedgerStore(controller.paths).account_balance_minor("acct_cash") == -120
    assert (next_root / "ledger" / "ledger.sqlite3").read_bytes() == b"occupied"


def test_successful_move_relocates_data_and_pointer(tmp_path: Path) -> None:
    settings_path = tmp_path / "system_paths.json"
    original_root = tmp_path / "original"
    controller = LedgerController(resolve_app_paths(original_root))
    controller.path_settings = PathSettingsService(settings_path)
    assert controller.submit(
        occurred_at="2026-09-01T10:00:00+08:00",
        entry_type="expense",
        amount="250",
        account_id="acct_cash",
        destination_account_id=None,
        category_id="cat_food_711",
        description="搬移後要留著",
    ).success

    next_root = tmp_path / "next"
    result = controller.save_path_settings(
        ledger_dir=next_root / "ledger",
        backup_dir=next_root / "backups",
        data_root=next_root,
        move_current=True,
    )

    assert result.success
    assert controller.paths.database_path == next_root / "ledger" / "ledger.sqlite3"
    assert controller.paths.export_dir == next_root / "exports"
    assert LedgerStore(controller.paths).account_balance_minor("acct_cash") == -250
    assert not (original_root / "data" / "ledger.sqlite3").exists()
    assert Path(json.loads(settings_path.read_text(encoding="utf-8"))["data_root"]) == next_root


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 的路徑大小寫語意")
def test_case_only_difference_is_the_same_path_on_windows(tmp_path: Path) -> None:
    """只差大小寫的路徑必須被當成同一個位置。

    使用者保留了日後把資料夾改成別的大小寫或底線的可能，若比對是區分大小寫的，
    `ledger_dir` 與 `backup_dir` 就可能同時指向同一個實體資料夾而通過驗證。
    """
    with pytest.raises(PathSettingsError) as excinfo:
        validate_path_settings(
            SystemPathSettings(
                ledger_dir=tmp_path / "Ledger",
                backup_dir=tmp_path / "ledger",
            )
        )
    assert str(excinfo.value) == "LEDGER_BACKUP_PATH_SAME"

    root = tmp_path / "tagcor-ledger"
    validated = validate_path_settings(
        _settings(root, ledger=tmp_path / "TagCor-Ledger" / "ledger", backup=root / "backups")
    )
    assert validated.data_root == root
