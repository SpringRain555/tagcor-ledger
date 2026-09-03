"""守門：`--json` 的 stdout 必須是可以直接餵給解析器的純 JSON。

一句話的由來：v0.8.0 加了日誌之後，`configure_logging` 會裝一個寫到 stderr 的 handler。
程式本身沒問題（stdout 仍然只有 JSON），但**一鍵啟動器把兩個串流合在一起再解析**，
於是啟動器壞了，症狀是「啟動資訊無法解析」。

所以這裡釘的是**契約**：不管日誌怎麼改、加多少 INFO 訊息，`--json` 的 stdout 一個字
都不能被污染。診斷訊息一律走 stderr。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tagcor_ledger.app.logging_setup import configure_logging
from tagcor_ledger.main import main


def test_json_stdout_is_pure_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--data-dir", str(tmp_path / "data"), "--init-data", "--json"])
    captured = capsys.readouterr()

    assert exit_code == 0
    # 這一行會因為 stdout 裡混進**任何**非 JSON 內容而失敗，正是我們要擋的東西。
    payload = json.loads(captured.out)
    assert payload["app"] == "TagCor Ledger"
    assert payload["version"]
    assert payload["ledger_dir"]


def test_logging_goes_to_stderr_not_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(tmp_path / "logs")
    main(["--data-dir", str(tmp_path / "data"), "--json"])
    captured = capsys.readouterr()

    json.loads(captured.out)
    assert "tagcor_ledger.startup" not in captured.out, "日誌跑到 stdout 了"


def test_plain_output_mode_still_works(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--data-dir", str(tmp_path / "data"), "--init-data"]) == 0
    assert "TagCor Ledger" in capsys.readouterr().out
