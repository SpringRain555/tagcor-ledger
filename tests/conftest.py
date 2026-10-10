"""整個 `tests/` 共用的保護網：**任何測試都碰不到真實的指標檔、帳本與日誌。**

## 為什麼需要這一層

`resolve_app_paths()` 沒收到路徑、環境變數也沒設時，會去讀使用者真正的指標檔
（`%LOCALAPPDATA%` 底下的 `system_paths.json`），接著打開它指向的那一份**真帳本**。
在這之前，擋住這件事的只有「每一條測試都記得傳 `tmp_path`」—— 一條靠記性的規則。
漏掉一次，測試就會在真帳本上建帳戶、寫交易，而且全綠。

這裡把各模組從 `platformdirs` 拿到的位置函式，整個 session 換成暫存目錄底下的假位置；
程式資料夾（第一次啟動可以選的 `userdata`，ADR-0018）也一起換掉。
「忘了傳路徑」最壞只會寫進暫存目錄。陽性對照在 `tests/unit/test_user_dir_guard.py`。

## 為什麼 patch 各模組的名字，不 patch `platformdirs` 本身

三個模組都是 `from platformdirs import user_..._dir`，綁的是**自己命名空間**裡的名字
（`test_startup_failures.py` 為了同一個理由 patch 兩個模組）。改 `platformdirs` 上的
函式，對已經 import 完的模組沒有作用。**新增任何一個 `from platformdirs import` 的模組，
要加進下面那張表** —— 守門測試會掃 `src/` 找出漏掉的。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

USER_DIR_FUNCTIONS: tuple[tuple[str, str, str], ...] = (
    ("tagcor_ledger.app.paths", "user_data_dir", "data"),
    ("tagcor_ledger.app.path_settings", "user_data_dir", "data"),
    ("tagcor_ledger.app.path_settings", "user_config_dir", "config"),
    ("tagcor_ledger.app.logging_setup", "user_log_dir", "logs"),
)
"""`(模組, 函式名, 假位置底下的子資料夾)`。正本只有這一份，守門測試也讀它。"""

DATA_DIR_ENV = "TAGCOR_LEDGER_DATA_DIR"
"""`app/paths.py` 認的覆寫變數。開發者的 shell 裡設了它，測試不該跟著指過去。"""

PROGRAM_ROOT_FUNCTION = "tagcor_ledger.app.data_location.program_root"
"""程式資料夾（repo 本身）。沒有指標檔時第 2 步會去 `<它>\\userdata` 找帳本，第一次啟動
選「放在程式資料夾裡」也會在那裡建 —— 不換掉的話，測試會在 repo 裡長出一個真的 `userdata`
（ADR-0018）。它不是 `platformdirs` 的函式，所以不在上面那張表裡，另外換。"""


@pytest.fixture(scope="session", autouse=True)
def fake_user_dirs(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """整個 session 的假使用者目錄。回傳它的根，給陽性對照用。"""
    root = tmp_path_factory.mktemp("fake-user-dirs")
    with pytest.MonkeyPatch.context() as patch:
        for module, name, folder in USER_DIR_FUNCTIONS:
            target = str(root / folder)
            patch.setattr(f"{module}.{name}", lambda *_args, _to=target, **_kwargs: _to)
        patch.setattr(PROGRAM_ROOT_FUNCTION, lambda: root / "program")
        patch.delenv(DATA_DIR_ENV, raising=False)
        yield root
