"""守門：一鍵啟動的進入點真的會開視窗。

`[project.gui-scripts]` 產生的 `tagcor-ledger.exe` 是用 pythonw 建的，**沒有主控台**。
所以它一旦指向錯的函式，症狀是「雙擊之後什麼都沒發生」—— 沒有錯誤、沒有視窗、沒有
紀錄。這種失敗不會有人回報，只會被當成「這個捷徑壞了」而放棄使用。
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Sequence

from tagcor_ledger import main as main_module


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _record_calls() -> tuple[list[list[str]], object]:
    calls: list[list[str]] = []

    def fake_main(argv: Sequence[str] | None = None) -> int:
        calls.append(list(argv or []))
        return 0

    return calls, fake_main


def test_gui_entry_point_forces_gui(monkeypatch) -> None:
    calls, fake_main = _record_calls()
    monkeypatch.setattr(main_module, "main", fake_main)
    assert main_module.main_gui([]) == 0
    assert calls == [["--gui"]]


def test_gui_entry_point_keeps_other_arguments(monkeypatch) -> None:
    calls, fake_main = _record_calls()
    monkeypatch.setattr(main_module, "main", fake_main)
    main_module.main_gui(["--data-dir", "X:\\tmp"])
    assert calls == [["--data-dir", "X:\\tmp", "--gui"]]


def test_gui_entry_point_does_not_duplicate_the_flag(monkeypatch) -> None:
    calls, fake_main = _record_calls()
    monkeypatch.setattr(main_module, "main", fake_main)
    main_module.main_gui(["--gui"])
    assert calls == [["--gui"]]


def test_packaging_points_the_gui_script_at_main_gui() -> None:
    """指到 `main:main` 會產生一個雙擊後毫無反應的 exe。"""
    config = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["project"]["gui-scripts"] == {
        "tagcor-ledger": "tagcor_ledger.main:main_gui"
    }


def test_version_is_the_same_number_everywhere() -> None:
    """版本寫在兩個地方，只改一個是無聲的。

    `pyproject.toml` 決定安裝出來的 metadata，`__init__.py` 決定 `--json`、日誌起始行與
    診斷資訊匯出檔印出來的數字。只改前者的話，程式**照樣跑、照樣全綠**，只是每一份
    交出去的診斷檔上面都寫著舊版號 —— 而那正是要拿來判斷「你跑的是哪一版」的東西。

    2026-08-18 Stage 7 真的發生過：`pyproject.toml` 已經是 0.11.0，`--json` 還印 0.10.0。
    """
    from tagcor_ledger import __version__

    config = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["project"]["version"] == __version__

    changelog = (PROJECT_ROOT / "docs" / "changelog.md").read_text(encoding="utf-8")
    assert f"\n## {__version__} " in changelog, (
        f"changelog.md 沒有 {__version__} 這一節 —— 版本升了就要寫它改了什麼"
    )


def test_one_click_launcher_files_exist_and_are_encoded_correctly() -> None:
    launcher = PROJECT_ROOT / "啟動 TagCor Ledger.cmd"
    script = PROJECT_ROOT / "Launch.ps1"
    assert launcher.exists() and script.exists()

    # PowerShell 5.1 讀沒有 BOM 的 .ps1 會退回 Big5，整份中文亂碼且無法解析。
    assert script.read_bytes()[:3] == b"\xef\xbb\xbf", "Launch.ps1 必須是 UTF-8 with BOM"

    # cmd.exe 的字碼頁行為不可靠，所以包裝檔一律純 ASCII，中文全留在 .ps1。
    launcher.read_bytes().decode("ascii")

    assert "Launch.ps1" in launcher.read_text(encoding="ascii")
