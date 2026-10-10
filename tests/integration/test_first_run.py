"""第一次啟動（ADR-0018），從 `main()` 走一遍：啟動器的預檢、問、選完之後的下一次。

對話框與主視窗都換成替身 —— 這裡測的是 `main._run` 的順序與副作用（帳本建在哪、指標檔寫了沒、
啟動器的標記檔在哪），對話框本身在 `tests/ui/test_first_run_dialog.py`。
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from typing import Any

import pytest

from tagcor_ledger.app import data_location
from tagcor_ledger.app.bootstrap import StartupContext
from tagcor_ledger.app.data_location import PROGRAM_DATA_FOLDER, LocationChoice, prepare_location
from tagcor_ledger.app.path_settings import default_settings_path
from tagcor_ledger.app.paths import paths_for
from tagcor_ledger.domain.models import SystemPathSettings
from tagcor_ledger.infrastructure.database import initialize_database
from tagcor_ledger.main import main


@dataclass(frozen=True)
class Places:
    root: Path
    program: Path
    user: Path

    @property
    def userdata(self) -> Path:
        return self.program / PROGRAM_DATA_FOLDER


@pytest.fixture
def places(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Places:
    program = tmp_path / "program"
    program.mkdir()
    user = tmp_path / "user"
    monkeypatch.setattr(data_location, "program_root", lambda: program)
    monkeypatch.setattr(
        "tagcor_ledger.app.path_settings.user_data_dir", lambda *_a, **_k: str(user)
    )
    monkeypatch.setattr(
        "tagcor_ledger.app.path_settings.user_config_dir",
        lambda *_a, **_k: str(tmp_path / "config"),
    )
    return Places(root=tmp_path, program=program, user=user)


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[StartupContext]:
    """主視窗的替身：記下它拿到的路徑，不進事件迴圈。"""
    contexts: list[StartupContext] = []

    def fake_run_gui(context: StartupContext) -> int:
        contexts.append(context)
        return 0

    monkeypatch.setattr("tagcor_ledger.ui.app.run_gui", fake_run_gui)
    return contexts


def _ask_with(monkeypatch: pytest.MonkeyPatch, answer: Any) -> list[Path]:
    """對話框的替身：照 `answer(ready_marker)` 回答，記下啟動器的標記檔位置。"""
    markers: list[Path] = []

    def fake_choose(*, ready_marker: Path) -> Any:
        markers.append(ready_marker)
        return answer(ready_marker)

    monkeypatch.setattr("tagcor_ledger.ui.first_run_dialog.choose_data_location", fake_choose)
    return markers


def _preflight(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    """啟動器的預檢：`--json`。"""
    assert main(["--json"]) == 0
    payload: dict[str, Any] = json.loads(capsys.readouterr().out)
    return payload


def _ledgers(places: Places) -> list[Path]:
    return sorted(places.root.rglob("ledger.sqlite3"))


def test_the_preflight_reports_first_run_and_creates_no_ledger(
    places: Places, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = _preflight(capsys)

    assert payload["data_location"] == "choose_on_first_run"
    assert _ledgers(places) == []
    # 預檢會在使用者資料夾留下日誌。再問一次仍然是第一次 —— 看的是帳本檔，不是資料夾。
    assert _preflight(capsys)["data_location"] == "choose_on_first_run"


def test_choosing_the_program_folder_puts_the_ledger_in_userdata_and_is_remembered(
    places: Places,
    started: list[StartupContext],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    launcher_marker = Path(_preflight(capsys)["ready_marker"])
    markers = _ask_with(monkeypatch, lambda _marker: prepare_location(LocationChoice.PROGRAM_FOLDER))

    assert main(["--gui"]) == 0

    # 對話框拿到的是啟動器在等的那一個標記檔 —— 選之前算出來的位置。
    assert markers == [launcher_marker]
    assert _ledgers(places) == [places.userdata / "data" / "ledger.sqlite3"]
    assert not default_settings_path().exists(), "程式資料夾不寫指標檔"
    assert started[-1].paths.ledger_dir == places.userdata / "data"

    # 下一次：預檢直接報程式資料夾，主程式也不再問。
    assert _preflight(capsys)["data_location"] == "program_folder"
    _ask_with(monkeypatch, lambda _marker: pytest.fail("帳本已經在 userdata，不該再問"))
    assert main(["--gui"]) == 0
    assert started[-1].paths.ledger_dir == places.userdata / "data"


def test_closing_the_question_creates_nothing_and_exits_quietly(
    places: Places, started: list[StartupContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    _ask_with(monkeypatch, lambda _marker: None)

    assert main(["--gui"]) == 0

    assert _ledgers(places) == []
    assert not default_settings_path().exists()
    assert started == [], "按了「結束」不該開主視窗"


def test_another_folder_reconnects_an_existing_ledger_untouched(
    places: Places,
    started: list[StartupContext],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """重灌 Windows 之後：指標檔不見了，資料根還在（`ledger\\` 結構）。接回去，資料原封不動。"""
    mine = places.root / "mine"
    existing = paths_for(
        SystemPathSettings(ledger_dir=mine / "ledger", backup_dir=mine / "backups", data_root=mine),
        config_dir=places.root / "unused-config",
    )
    initialize_database(existing)
    with sqlite3.connect(existing.database_path) as connection:
        connection.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES ('probe', 'kept', '2026-10-10')"
        )
    connection.close()
    _ask_with(
        monkeypatch,
        lambda _marker: prepare_location(LocationChoice.OTHER, other_folder=mine),
    )

    assert main(["--gui"]) == 0

    pointer = json.loads(default_settings_path().read_text(encoding="utf-8"))
    assert Path(pointer["ledger_dir"]) == (mine / "ledger").resolve()
    assert not (mine / "data").exists(), "接回既有的帳本，不另建一本"
    with sqlite3.connect(existing.database_path) as connection:
        row = connection.execute("SELECT value FROM settings WHERE key = 'probe'").fetchone()
    connection.close()
    assert row == ("kept",)
    assert _preflight(capsys)["data_location"] == "pointer"


def test_an_override_never_asks(
    places: Places,
    started: list[StartupContext],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """`--data-dir` 是開發與測試用的覆寫：不讀指標檔，也永遠不問。"""
    _ask_with(monkeypatch, lambda _marker: pytest.fail("--data-dir 不該問"))

    assert main(["--data-dir", str(tmp_path / "dev"), "--gui"]) == 0
    assert started[-1].location == "override"
