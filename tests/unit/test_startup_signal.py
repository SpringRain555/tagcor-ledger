"""主控台要在主視窗出來之後才退場 —— 不是 5 秒之後，也不是永遠不退。

`tools/Launch.ps1` 從 2026-08-18 到 2026-09-11 的判準是「等 5 秒，行程還在就當視窗開了」。
那擋得住一啟動就死的情形，擋不住視窗第 8 秒才出來、或第 6 秒才炸掉。
現在程式在 `window.show()` 之後寫一個標記檔，啟動器等它出現。這裡守的是約定的兩端。
"""

from __future__ import annotations

import json
from pathlib import Path
import re

from tagcor_ledger.app import startup_signal
from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.main import main

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LAUNCH_SCRIPT = PROJECT_ROOT / "tools" / "Launch.ps1"


def test_the_marker_lives_under_tmp_dir(tmp_path: Path) -> None:
    """生命週期是「這一次啟動」，所以跟其他暫存物放一起，而且跟著資料根走。"""
    paths = resolve_app_paths(tmp_path / "ledger-data")

    marker = startup_signal.marker_path(paths)

    assert marker.parent == paths.tmp_dir
    assert marker.name == startup_signal.MARKER_FILE_NAME


def test_marking_ready_creates_the_file(tmp_path: Path) -> None:
    marker = tmp_path / "nested" / "ui-ready.txt"

    assert startup_signal.mark_ready(marker) is True
    assert marker.is_file()


def test_the_marker_says_which_process_wrote_it(tmp_path: Path) -> None:
    """PID 與時間**不是給誰去讀的** —— 是為了在標記沒被清掉的時候看得出來是哪一次留下的。"""
    marker = tmp_path / "ui-ready.txt"
    startup_signal.mark_ready(marker)

    text = marker.read_text(encoding="utf-8")

    assert re.search(r"^pid=\d+$", text, re.MULTILINE)
    assert re.search(r"^at=\d{4}-\d{2}-\d{2}T", text, re.MULTILINE)


def test_clearing_removes_a_stale_marker(tmp_path: Path) -> None:
    """上一次留下來的標記不能讓這一次以為自己已經成功了。"""
    marker = tmp_path / "ui-ready.txt"
    startup_signal.mark_ready(marker)

    startup_signal.clear(marker)

    assert not marker.exists()


def test_clearing_a_marker_that_is_not_there_is_fine(tmp_path: Path) -> None:
    """第一次啟動就是這個情形。"""
    startup_signal.clear(tmp_path / "never-existed.txt")


def test_a_marker_that_cannot_be_written_reports_false(tmp_path: Path) -> None:
    """寫不進去要說寫不進去。回 `True` 而讓啟動器永遠等下去，比主控台早關掉糟糕得多。"""
    blocker = tmp_path / "blocked"
    blocker.write_text("我是一個檔案，不是目錄", encoding="utf-8")

    assert startup_signal.mark_ready(blocker / "ui-ready.txt") is False


# ── 兩端的約定 ────────────────────────────────────────────────────────


def test_the_json_payload_tells_the_launcher_where_the_marker_is(capsys, tmp_path: Path) -> None:
    """啟動器從 `--json` 拿路徑，不在 PowerShell 那一側自己拼。

    自己拼就是第二份路徑實作：`--data-dir` 或指標檔換了資料根之後，它會安靜地
    指錯地方，於是標記永遠等不到 —— 而症狀是「等了 90 秒還沒看到視窗」，不是編碼或路徑錯。
    """
    data_dir = tmp_path / "ledger-data"
    assert main(["--data-dir", str(data_dir), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)

    marker = Path(payload["ready_marker"])
    assert marker.is_absolute()
    assert marker.parent == Path(payload["tmp_dir"])


def test_the_launcher_waits_for_the_marker_not_for_a_number_of_seconds() -> None:
    """啟動器那一端。**結構**測試而不是執行測試 —— 真的跑起來會開一個視窗。

    守三件事，少任何一件「主控台自己關掉」就會退化成「在視窗出現之前就關掉」：
    路徑從 payload 拿、等的是標記檔、行程提早結束要偵測到。
    """
    script = LAUNCH_SCRIPT.read_text(encoding="utf-8-sig")

    assert "$info.ready_marker" in script, "沒有從 --json 拿標記檔的位置"
    assert "Test-Path -LiteralPath $marker" in script, "沒有等標記出現"
    assert "$process.HasExited" in script, "沒有偵測行程提早結束"
    # 這一條是回歸：固定秒數的猜測不能回來。
    assert "WaitForExit(" not in script, "又回到「等幾秒、還活著就當開了」"
