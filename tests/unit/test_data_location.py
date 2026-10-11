"""資料放在哪裡（ADR-0018）：沒有指標檔時的四步、第一次啟動的三個選項、`userdata` 不進 git。

位置全部換到 `tmp_path` 底下：程式資料夾、使用者資料夾、指標檔所在的設定目錄各一個。
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from tagcor_ledger.app import data_location
from tagcor_ledger.app.data_location import (
    PROGRAM_DATA_FOLDER,
    LocationChoice,
    LocationSource,
    detect_data_location,
    inspect_other_folder,
    prepare_location,
)
from tagcor_ledger.app.path_settings import PathSettingsError, default_settings_path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Places:
    program: Path
    user: Path
    config: Path

    @property
    def userdata(self) -> Path:
        return self.program / PROGRAM_DATA_FOLDER


@pytest.fixture
def places(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Places:
    program = tmp_path / "program"
    program.mkdir()
    user = tmp_path / "user"
    config = tmp_path / "config"
    monkeypatch.setattr(data_location, "program_root", lambda: program)
    monkeypatch.setattr(
        "tagcor_ledger.app.path_settings.user_data_dir", lambda *_a, **_k: str(user)
    )
    monkeypatch.setattr(
        "tagcor_ledger.app.path_settings.user_config_dir", lambda *_a, **_k: str(config)
    )
    return Places(program=program, user=user, config=config)


def _ledger(root: Path, folder: str = "data") -> Path:
    """在 `root\\<folder>` 放一個帳本檔。偵測只看檔案在不在，內容不重要。"""
    path = root / folder / "ledger.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def _write_pointer(root: Path) -> None:
    pointer = default_settings_path()
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(
        json.dumps(
            {
                "settings_version": 1,
                "data_root": str(root),
                "ledger_dir": str(root / "ledger"),
                "backup_dir": str(root / "backups"),
            }
        ),
        encoding="utf-8",
    )


# ---- 四步 -------------------------------------------------------------------


def test_nothing_anywhere_means_ask_and_nothing_is_created(places: Places) -> None:
    location = detect_data_location()

    assert location.source is LocationSource.CHOOSE_ON_FIRST_RUN
    # 路徑先指著使用者資料夾，給日誌與啟動器的標記檔落腳。
    assert location.settings.data_root == places.user.resolve()
    # 「只看、不建」：偵測本身不能讓下一次被誤判成「選過了」。
    assert not places.user.exists()
    assert not places.userdata.exists()


def test_a_ledger_in_userdata_is_used_without_asking(places: Places) -> None:
    _ledger(places.userdata)

    location = detect_data_location()

    assert location.source is LocationSource.PROGRAM_FOLDER
    assert location.settings.ledger_dir == places.userdata / "data"
    assert location.settings.backup_dir == places.userdata / "backups"


def test_a_ledger_in_the_user_folder_is_used_without_asking(places: Places) -> None:
    """舊使用者：ADR-0018 之前沒有指標檔的人，帳本就在這裡。跟以前一樣，不會被問。"""
    _ledger(places.user)

    location = detect_data_location()

    assert location.source is LocationSource.USER_FOLDER
    assert location.settings.ledger_dir == places.user.resolve() / "data"


def test_userdata_wins_when_both_have_a_ledger(places: Places) -> None:
    _ledger(places.userdata)
    _ledger(places.user)

    assert detect_data_location().source is LocationSource.PROGRAM_FOLDER


def test_the_pointer_wins_over_everything(places: Places, tmp_path: Path) -> None:
    _ledger(places.userdata)
    _ledger(places.user)
    mine = tmp_path / "mine"
    _ledger(mine, "ledger")
    _write_pointer(mine)

    location = detect_data_location()

    assert location.source is LocationSource.POINTER
    assert location.settings.ledger_dir == (mine / "ledger").resolve()


def test_the_ledger_folder_layout_is_recognised_too(places: Places) -> None:
    """自己指定過路徑的人多半是 `ledger\\` 結構（storage-layout.md「一般使用」）。"""
    _ledger(places.user, "ledger")

    location = detect_data_location()

    assert location.source is LocationSource.USER_FOLDER
    assert location.settings.ledger_dir == places.user.resolve() / "ledger"


def test_a_backup_copy_is_not_mistaken_for_a_ledger(places: Places) -> None:
    """每一份備份裡都有一個 `ledger.sqlite3`。往下亂找的話，備份會被當成帳本接上。"""
    _ledger(places.user / "backups", "backup_20261010_120000_abc123")

    assert detect_data_location().source is LocationSource.CHOOSE_ON_FIRST_RUN


def test_a_logs_folder_alone_does_not_count_as_chosen(places: Places) -> None:
    """啟動器的預檢在使用者選之前就會建 `logs\\`。看資料夾的話，這裡會被誤判成「選過了」。"""
    (places.user / "logs").mkdir(parents=True)
    (places.user / "tmp").mkdir(parents=True)

    assert detect_data_location().source is LocationSource.CHOOSE_ON_FIRST_RUN


def test_without_a_program_folder_the_userdata_step_is_skipped(
    places: Places, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(data_location, "program_root", lambda: None)
    _ledger(places.user)

    assert data_location.program_data_root() is None
    assert detect_data_location().source is LocationSource.USER_FOLDER


# ---- 三個選項 ----------------------------------------------------------------


def test_choosing_the_program_folder_builds_userdata_and_writes_no_pointer(places: Places) -> None:
    location = prepare_location(LocationChoice.PROGRAM_FOLDER)

    assert location.source is LocationSource.PROGRAM_FOLDER
    assert (places.userdata / "data").is_dir()
    assert (places.userdata / "backups").is_dir()
    # 不寫指標檔：整個程式資料夾搬走，下一次從新的位置往下找照樣找得到。
    assert not default_settings_path().exists()


def test_choosing_the_user_folder_writes_no_pointer_either(places: Places) -> None:
    location = prepare_location(LocationChoice.USER_FOLDER)

    assert location.source is LocationSource.USER_FOLDER
    assert location.settings.ledger_dir == places.user.resolve() / "data"
    assert not default_settings_path().exists()


def test_once_the_ledger_exists_the_next_start_does_not_ask(places: Places) -> None:
    """選的結果本身就是證據：帳本一建出來，下一次第 2 步就找到它。"""
    location = prepare_location(LocationChoice.PROGRAM_FOLDER)
    _ledger(location.settings.ledger_dir.parent, location.settings.ledger_dir.name)

    assert detect_data_location().source is LocationSource.PROGRAM_FOLDER


def test_another_empty_folder_gets_a_new_layout_and_a_pointer(
    places: Places, tmp_path: Path
) -> None:
    mine = tmp_path / "mine"
    mine.mkdir()

    location = prepare_location(LocationChoice.OTHER, other_folder=mine)

    assert location.source is LocationSource.POINTER
    assert location.settings.ledger_dir == mine.resolve() / "data"
    pointer = json.loads(default_settings_path().read_text(encoding="utf-8"))
    assert Path(pointer["data_root"]) == mine.resolve()
    assert detect_data_location().source is LocationSource.POINTER


def test_another_folder_with_a_ledger_is_reconnected_as_it_is(
    places: Places, tmp_path: Path
) -> None:
    """重灌 Windows、指標檔不見、資料還在 D 槽：選「其他位置…」把它接回來，不另建一本。"""
    mine = tmp_path / "mine"
    _ledger(mine, "ledger")

    location = prepare_location(LocationChoice.OTHER, other_folder=mine)

    assert location.settings.ledger_dir == mine.resolve() / "ledger"
    assert not (mine / "data").exists()


@pytest.mark.parametrize(
    ("make_folder", "code"),
    [
        (lambda places, tmp: places.program / "inside", "DATA_ROOT_INSIDE_PROGRAM_FOLDER"),
        (lambda places, tmp: places.userdata, "DATA_ROOT_INSIDE_PROGRAM_FOLDER"),
        (lambda places, tmp: Path(tmp.anchor), "DATA_ROOT_IS_DRIVE_ROOT"),
        (lambda places, tmp: _ledger(tmp / "mine").parent, "DATA_ROOT_INSIDE_DATA_ROOT"),
        (lambda places, tmp: _ledger(tmp / "mine", "ledger").parent, "DATA_ROOT_INSIDE_DATA_ROOT"),
        # 2026-10-11 之前擋不到的兩種：資料根裡別的子資料夾、更深的地方（CONVENTIONS §11）。
        (
            lambda places, tmp: _ledger(tmp / "mine", "ledger").parents[1] / "backups",
            "DATA_ROOT_INSIDE_DATA_ROOT",
        ),
        (
            lambda places, tmp: _ledger(tmp / "mine").parent / "deeper" / "still",
            "DATA_ROOT_INSIDE_DATA_ROOT",
        ),
    ],
    ids=[
        "inside-program",
        "userdata-itself",
        "drive-root",
        "legacy-data-dir",
        "ledger-dir",
        "backups-in-data-root",
        "deeper-in-data-root",
    ],
)
def test_another_folder_that_cannot_be_a_data_root_is_refused(
    places: Places, tmp_path: Path, make_folder, code: str
) -> None:
    folder = make_folder(places, tmp_path)

    inspected = inspect_other_folder(folder)
    assert inspected.settings is None
    assert inspected.error_code == code
    with pytest.raises(PathSettingsError, match=code):
        prepare_location(LocationChoice.OTHER, other_folder=folder)
    assert not default_settings_path().exists(), "被擋下來的選擇不能寫指標檔"


def test_inspecting_another_folder_tells_existing_from_new(places: Places, tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    _ledger(existing, "ledger")
    empty = tmp_path / "empty"
    empty.mkdir()

    assert inspect_other_folder(existing).has_ledger is True
    assert inspect_other_folder(empty).has_ledger is False
    assert inspect_other_folder(empty).settings is not None
    # 只看、不建。
    assert list(empty.iterdir()) == []


def test_a_folder_that_cannot_be_created_is_reported_and_nothing_is_written(
    places: Places,
) -> None:
    places.userdata.write_text("擋路的檔案", encoding="utf-8")

    with pytest.raises(PathSettingsError, match="SYSTEM_PATH_NOT_WRITABLE"):
        prepare_location(LocationChoice.PROGRAM_FOLDER)
    assert not default_settings_path().exists()


# ---- userdata 不進 git -------------------------------------------------------

IGNORED_UNDER_USERDATA = (
    "userdata/data/ledger.sqlite3",
    # 下面兩個不是 *.sqlite3：只靠副檔名規則的話，它們會被 commit。
    "userdata/exports/transactions_20261010_120000.csv",
    "userdata/backups/backup_20261010_120000_abc123/backup_manifest.json",
    "userdata/logs/app.log",
)


@pytest.mark.skipif(shutil.which("git") is None, reason="需要 git")
@pytest.mark.parametrize("path", IGNORED_UNDER_USERDATA)
def test_everything_under_userdata_is_ignored_by_git(path: str) -> None:
    result = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "check-ignore", "--quiet", "--no-index", path],
        check=False,
    )
    assert result.returncode == 0, f"{path} 沒有被 .gitignore 忽略，會跟著 commit 出去"
