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

from collections.abc import Callable, Iterator
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


@pytest.fixture
def make_deposit() -> Callable[..., str]:
    """建一份**確定會產生待確認項目**的定存，回傳 contract_id。

    四個檔案都要「有一件待確認」當前提，而它們踩的坑一模一樣，所以收在這裡。
    **是 fixture 不是普通函式** —— `tests/` 底下沒有 `__init__.py`，
    `pythonpath` 也只有 `src`，所以 `from tests.ui.conftest import …` 匯入不到。

    **`recorded_on` 一定要跟著首次起存日往前拉。** 產生待確認項目的下界是合約的建檔日
    （ADR-0012），預設今天 —— 首次起存日填在很久以前但建檔日是今天的話，那一期在建檔
    之前就到期了，一件項目都不會產生。而 UI 測試沒辦法像 `generate_due(today=...)`
    那樣控制「今天」，它走的是真實時鐘。

    這正是使用者照存單抄日期會遇到的情形，只是在測試裡它會讓斷言悄悄變成
    「0 件也算通過」。
    """

    def build(
        controller: Any,
        *,
        name: str = "郵局定存",
        opened_on: str = "2020-01-15",
        generate: bool = True,
    ) -> str:
        account_id = str(controller.account_options()[0]["account_id"])
        result = controller.create_deposit_contract(
            account_id=account_id,
            name=name,
            interest_method="lump_sum",
            maturity_action="renew_principal_only",
            interest_destination_account_id=account_id,
            term_months=12,
            opened_on=opened_on,
            principal="100000",
            annual_rate_ppm=16_000,
            recorded_on=opened_on,
        )
        assert result.success, result.message
        if generate:
            # **合約建好不會自己產生事件** —— 那是啟動任務或定存頁那顆按鈕做的。
            assert controller.generate_deposit_events().success
        return str(result.details["contract_id"])

    return build
