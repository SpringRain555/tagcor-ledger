"""`tests/ui/` 共用的 fixture。

## 為什麼是 fixture 而不是繼續各寫各的

這三行

    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()

在 2026-08-22 之前重複了 **49 次**，而且**每一次都一模一樣**。重複本身還好，
麻煩的是它讓「這個測試有什麼不一樣」看不出來 —— 讀者要逐字比對三行才知道
某個測試是不是刻意不 `show()`。

抽成 fixture 之後，**還在手動建視窗的地方就是真的有理由的地方**，
而那個理由現在寫在各自的註解裡。

## 什麼時候不要用它

- 需要在 `show()` 之前 `resize()`（版面測試）。
- 刻意不 `show()`。
- 一個測試裡要開第二個視窗，或用同一個 data dir 重開。

這些情況直接自己建，不要為了共用而給 fixture 加參數 —— 加到第三個參數的時候，
fixture 自己就變成另一個要讀懂的東西了。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot: Any, tmp_path: Path) -> Iterator[MainWindow]:
    """一個開好、顯示中、資料在 `tmp_path` 底下的主視窗。

    **資料一律在 `tmp_path`**，不會碰到真實帳本 —— `resolve_app_paths()` 收到明確的
    路徑時就不會去讀 `%LOCALAPPDATA%` 的指標檔。
    """
    main_window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(main_window)
    main_window.show()
    yield main_window
