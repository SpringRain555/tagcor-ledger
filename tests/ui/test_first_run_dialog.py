"""第一次啟動的對話框（ADR-0018）：三個選項、什麼時候能按「確定」、按下去建了什麼。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QFileDialog

from tagcor_ledger.app import data_location
from tagcor_ledger.app.data_location import PROGRAM_DATA_FOLDER, LocationSource
from tagcor_ledger.application.failures import message_for
from tagcor_ledger.ui import first_run_dialog
from tagcor_ledger.ui.first_run_dialog import (
    OTHER_EXISTING,
    OTHER_NEW,
    PROGRAM_UNAVAILABLE,
    DataLocationDialog,
    choose_data_location,
)


@pytest.fixture
def program(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """程式資料夾與使用者資料夾都換到 `tmp_path`。回傳程式資料夾。"""
    root = tmp_path / "program"
    root.mkdir()
    monkeypatch.setattr(data_location, "program_root", lambda: root)
    monkeypatch.setattr(
        "tagcor_ledger.app.path_settings.user_data_dir", lambda *_a, **_k: str(tmp_path / "user")
    )
    monkeypatch.setattr(
        "tagcor_ledger.app.path_settings.user_config_dir",
        lambda *_a, **_k: str(tmp_path / "config"),
    )
    return root


def _dialog(qtbot: Any, program: Path | None, tmp_path: Path) -> DataLocationDialog:
    dialog = DataLocationDialog(
        program_folder=program / PROGRAM_DATA_FOLDER if program is not None else None,
        user_folder=tmp_path / "user",
    )
    qtbot.addWidget(dialog)
    return dialog


def _ok_enabled(dialog: DataLocationDialog) -> bool:
    return bool(dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled())


def test_the_program_folder_is_preselected_and_shows_where(
    qtbot: Any, program: Path, tmp_path: Path
) -> None:
    dialog = _dialog(qtbot, program, tmp_path)

    assert dialog.program_option.isChecked()
    assert dialog.program_path.text() == str(program / PROGRAM_DATA_FOLDER)
    assert dialog.user_path.text() == str(tmp_path / "user")
    assert _ok_enabled(dialog)


def test_without_a_program_folder_that_option_says_why_and_the_user_folder_is_preselected(
    qtbot: Any, tmp_path: Path
) -> None:
    dialog = _dialog(qtbot, None, tmp_path)

    assert not dialog.program_option.isEnabled()
    assert dialog.program_path.text() == PROGRAM_UNAVAILABLE
    assert dialog.user_option.isChecked()
    assert _ok_enabled(dialog)


def test_another_place_needs_a_folder_before_ok(
    qtbot: Any, program: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialog = _dialog(qtbot, program, tmp_path)
    dialog.other_option.setChecked(True)
    assert not _ok_enabled(dialog), "還沒挑資料夾就能按「確定」"

    mine = tmp_path / "mine"
    mine.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_args: str(mine))
    dialog.pick_other_folder()

    assert dialog.other_path.text() == str(mine.resolve())
    assert dialog.other_status.text() == OTHER_NEW
    assert _ok_enabled(dialog)


def test_another_place_with_a_ledger_says_it_will_be_used(
    qtbot: Any, program: Path, tmp_path: Path
) -> None:
    mine = tmp_path / "mine"
    (mine / "ledger").mkdir(parents=True)
    (mine / "ledger" / "ledger.sqlite3").write_bytes(b"")
    dialog = _dialog(qtbot, program, tmp_path)

    dialog.set_other_folder(mine)

    assert dialog.other_option.isChecked(), "挑了資料夾就該選到「其他位置」"
    assert dialog.other_status.text() == OTHER_EXISTING


def test_another_place_inside_the_program_folder_is_refused_before_ok(
    qtbot: Any, program: Path, tmp_path: Path
) -> None:
    dialog = _dialog(qtbot, program, tmp_path)

    dialog.set_other_folder(program / "somewhere")

    assert dialog.other_status.text() == message_for("DATA_ROOT_INSIDE_PROGRAM_FOLDER")
    assert not _ok_enabled(dialog)


def test_ok_builds_the_folders_and_closes(qtbot: Any, program: Path, tmp_path: Path) -> None:
    dialog = _dialog(qtbot, program, tmp_path)

    dialog.accept()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.chosen is not None
    assert dialog.chosen.source is LocationSource.PROGRAM_FOLDER
    assert (program / PROGRAM_DATA_FOLDER / "data").is_dir()


def test_a_folder_that_cannot_be_built_keeps_the_dialog_open_and_says_why(
    qtbot: Any, program: Path, tmp_path: Path
) -> None:
    (program / PROGRAM_DATA_FOLDER).write_text("擋路的檔案", encoding="utf-8")
    dialog = _dialog(qtbot, program, tmp_path)

    dialog.accept()

    assert dialog.chosen is None
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.status.text() == message_for("SYSTEM_PATH_NOT_WRITABLE")


def test_exit_builds_nothing(qtbot: Any, program: Path, tmp_path: Path) -> None:
    dialog = _dialog(qtbot, program, tmp_path)

    dialog.reject()

    assert dialog.chosen is None
    assert not (program / PROGRAM_DATA_FOLDER).exists()
    assert not (tmp_path / "user").exists()


def test_the_launcher_marker_is_written_once_the_dialog_is_shown(
    qtbot: Any, program: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """啟動器等的是「使用者看得到東西了」—— 對話框一出現就算，不必等到主視窗。"""
    marker = tmp_path / "launcher" / "ui-ready.txt"
    observed: dict[str, Any] = {}
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    quit_on_close = app.quitOnLastWindowClosed()

    def fake_exec(dialog: DataLocationDialog) -> int:
        # 進 exec() 的那一刻還沒顯示、也還沒有標記。先 show() 再 exec() 的話，已經顯示的
        # 視窗改不了 modality，對話框就不是 modal（2026-10-10 實機踩到）—— 那時標記會已經在。
        observed["marker_at_exec"] = marker.exists()
        QDialog.show(dialog)  # exec() 自己會做的那一步
        observed["marker_after_show"] = marker.exists()
        # 問的這段期間不能讓「最後一個視窗關了」把等一下的主視窗事件迴圈結束掉。
        observed["quit_on_close"] = app.quitOnLastWindowClosed()
        dialog.hide()
        qtbot.addWidget(dialog)
        return 0

    monkeypatch.setattr(first_run_dialog.DataLocationDialog, "exec", fake_exec)

    assert choose_data_location(ready_marker=marker) is None
    assert observed == {
        "marker_at_exec": False,
        "marker_after_show": True,
        "quit_on_close": False,
    }
    assert app.quitOnLastWindowClosed() == quit_on_close, "問完要還原"
