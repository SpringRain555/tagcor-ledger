"""REQ-0009 的驗收：五種故障各製造一次，每種都必須有訊息、有紀錄、不無聲死掉。

**「不無聲死掉」是這裡的重點。** 之前這五種全部未攔截，從捷徑啟動時的症狀是
「視窗沒出現、沒有訊息、沒有紀錄」—— 使用者無從判斷是程式壞了還是自己沒點到。

這些測試不開 Qt：`main()` 在 `--gui` 之下會先試 Qt 對話框、失敗才退回 stderr，
而測試環境要驗的是「**有沒有把話講出來**」，用哪個管道講是次要的。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tagcor_ledger.app.logging_setup import configure_logging
from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.app.single_instance import AlreadyRunningError, SingleInstanceGuard
from tagcor_ledger.app.startup import classify_startup_error
from tagcor_ledger.infrastructure.database import initialize_database
from tagcor_ledger.main import main


@pytest.fixture(autouse=True)
def _isolate_logging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """把 fallback 日誌位置導到 tmp，避免測試污染真正的日誌。"""
    monkeypatch.setattr(
        "tagcor_ledger.app.logging_setup.fallback_log_dir",
        lambda: tmp_path / "fallback-logs",
    )


def _run(argv: list[str]) -> int:
    return main(argv)


def test_corrupt_settings_file_reports_instead_of_crashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings_path = tmp_path / "system_paths.json"
    settings_path.write_text("{ 這不是 JSON", encoding="utf-8")
    # 兩個模組都要 patch：`startup.py` 是 `from ... import`，綁的是自己命名空間裡的名字。
    for module in ("tagcor_ledger.app.path_settings", "tagcor_ledger.app.startup"):
        monkeypatch.setattr(f"{module}.default_settings_path", lambda: settings_path)
    monkeypatch.delenv("TAGCOR_LEDGER_DATA_DIR", raising=False)

    exit_code = _run([])

    assert exit_code == 1
    output = capsys.readouterr().err
    assert "路徑設定檔損毀" in output
    # 最重要的一句：使用者要知道刪掉它是安全的。
    assert "不會損失" in output
    assert str(settings_path) in output


def test_missing_drive_reports_the_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError(2, "找不到磁碟", "Z:\\ledger")

    monkeypatch.setattr("tagcor_ledger.main.bootstrap", explode)

    exit_code = _run(["--json"])

    assert exit_code == 1
    output = capsys.readouterr().err
    assert "找不到資料夾" in output
    assert "外接磁碟" in output


def test_schema_too_new_tells_the_user_not_to_continue(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    paths = resolve_app_paths(data_dir)
    initialize_database(paths)

    import sqlite3

    with sqlite3.connect(paths.database_path) as connection:
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (99, '2026-01-01')"
        )
        connection.commit()

    exit_code = _run(["--data-dir", str(data_dir), "--init-data"])

    assert exit_code == 1
    output = capsys.readouterr().err
    assert "資料庫版本比程式新" in output
    assert "不要繼續" in output


def test_second_instance_is_refused_with_a_clear_message(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()

    with SingleInstanceGuard(ledger_dir):
        with pytest.raises(AlreadyRunningError):
            SingleInstanceGuard(ledger_dir, timeout=0.05).acquire()

        failure = classify_startup_error(AlreadyRunningError("ALREADY_RUNNING"))
        assert failure.error_code == "ALREADY_RUNNING"
        assert "已經" in failure.title

    # 釋放之後必須拿得回來，否則使用者關掉程式就再也開不起來。
    SingleInstanceGuard(ledger_dir).acquire()


def test_leftover_lock_file_does_not_block_the_next_start(tmp_path: Path) -> None:
    """程式被強制結束時鎖檔會留在磁碟上。**這種殘留無害**，不該要求使用者手動刪。

    正常釋放時 `filelock` 會自己把檔案刪掉，所以這裡直接手寫一個檔案來模擬「行程被
    工作管理員砍掉」：檔案還在，但 OS 已經釋放了它的檔案鎖。
    """
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    stale = ledger_dir / "ledger.lock"
    stale.write_text("", encoding="utf-8")

    guard = SingleInstanceGuard(ledger_dir)
    guard.acquire()
    guard.release()


def test_lock_is_released_so_the_app_can_be_reopened(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()

    first = SingleInstanceGuard(ledger_dir)
    first.acquire()
    first.release()

    SingleInstanceGuard(ledger_dir).acquire()


def test_two_different_ledgers_do_not_block_each_other(tmp_path: Path) -> None:
    """鎖是綁在 `ledger_dir` 上的，所以指向不同資料夾的兩個實例可以並存。"""
    first_dir = tmp_path / "one"
    second_dir = tmp_path / "two"
    first_dir.mkdir()
    second_dir.mkdir()

    SingleInstanceGuard(first_dir).acquire()
    SingleInstanceGuard(second_dir).acquire()


def test_read_only_directory_is_reported_as_permission_not_as_mystery(
    tmp_path: Path,
) -> None:
    failure = classify_startup_error(PermissionError(13, "拒絕存取", str(tmp_path / "backups")))
    assert failure.error_code == "DATA_DIRECTORY_NOT_WRITABLE"
    assert "唯讀" in failure.message


def test_every_startup_failure_gives_an_actionable_instruction() -> None:
    """驗收條件之一：不能只說「發生錯誤」。

    每一則訊息都必須含有可以照著做的動詞。寫不出動作，代表這個錯誤還沒想清楚。
    """
    import sqlite3

    from tagcor_ledger.app.path_settings import PathSettingsError

    samples: list[BaseException] = [
        AlreadyRunningError("ALREADY_RUNNING"),
        PathSettingsError("SYSTEM_PATH_SETTINGS_INVALID"),
        PathSettingsError("PATH_OUTSIDE_DATA_ROOT"),
        RuntimeError("DATABASE_SCHEMA_TOO_NEW"),
        sqlite3.DatabaseError("database is locked"),
        sqlite3.DatabaseError("database disk image is malformed"),
        sqlite3.DatabaseError("something else entirely"),
        PermissionError(13, "拒絕存取", "X:\\x"),
        OSError(28, "磁碟已滿", "X:\\x"),
        FileNotFoundError(2, "找不到", "Z:\\x"),
        ValueError("完全沒見過的東西"),
    ]
    verbs = ("請", "可以", "先", "把", "確認", "切換", "刪")
    for exc in samples:
        failure = classify_startup_error(exc)
        assert failure.error_code, exc
        assert failure.title, exc
        assert any(verb in failure.message for verb in verbs), (
            f"{failure.error_code} 的訊息沒有可執行的動作：{failure.message}"
        )


def test_failure_is_written_to_the_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """訊息看得到還不夠，紀錄也要留得下 —— 使用者常常是關掉對話框之後才想找原因。"""
    log_dir = tmp_path / "fallback-logs"
    monkeypatch.setattr(
        "tagcor_ledger.app.logging_setup.fallback_log_dir", lambda: log_dir
    )

    def explode(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError(2, "找不到磁碟", "Z:\\ledger")

    monkeypatch.setattr("tagcor_ledger.main.bootstrap", explode)
    _run(["--json"])
    capsys.readouterr()

    log_file = log_dir / "app.log"
    assert log_file.exists(), "啟動失敗必須留下紀錄"
    content = log_file.read_text(encoding="utf-8")
    assert "DATA_DIRECTORY_UNAVAILABLE" in content
    assert "FileNotFoundError" in content


def test_settings_file_written_by_an_older_version_still_loads(tmp_path: Path) -> None:
    """相容性：舊的 `system_paths.json` 沒有 `data_root`，不該變成啟動失敗。"""
    from tagcor_ledger.app.path_settings import PathSettingsService

    settings_path = tmp_path / "system_paths.json"
    root = tmp_path / "root"
    settings_path.write_text(
        json.dumps(
            {
                "ledger_dir": str(root / "ledger"),
                "backup_dir": str(root / "backups"),
            }
        ),
        encoding="utf-8",
    )
    settings = PathSettingsService(settings_path).load()
    assert settings.ledger_dir == root / "ledger"


def test_logging_survives_an_unwritable_directory(tmp_path: Path) -> None:
    """記不了日誌是遺憾，不該變成不能記帳。"""
    blocker = tmp_path / "blocked"
    blocker.write_text("我是檔案不是資料夾", encoding="utf-8")
    assert configure_logging(blocker / "logs") is None
