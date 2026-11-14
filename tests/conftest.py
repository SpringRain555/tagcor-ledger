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
from copy import deepcopy
from datetime import timedelta
import importlib.util
import json
from pathlib import Path

import pytest

from tagcor_ledger.application.reference import REFERENCE_DB_ENV
from tagcor_ledger.domain.tax.dataset_validate import validate_tax_dataset
from tagcor_ledger.infrastructure.clock import today_taipei

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


@pytest.fixture(scope="session", autouse=True)
def fake_tax_dataset(fake_user_dirs: Path) -> Iterator[Path]:
    """固定 App 測試使用的稅務資料，避免公開 dataset 年更改動測試結果。

    行為測試不得經 App 預設路徑讀 repo 的真實資料集；否則公告更新會讓 UI 與提醒測試
    隨年度變色。需要檢查具體資料或日期的測試，應明確傳入自己的 fixture 路徑。
    """
    repo_root = Path(__file__).resolve().parents[1]
    sample_path = repo_root / "tests" / "fixtures" / "tax" / "sample.json"
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    fake = deepcopy(sample)
    today = today_taipei()
    fake["reviewed_at"] = today.isoformat()
    fake["next_review_on"] = (today + timedelta(days=366)).isoformat()
    fake["notes"] = ["測試用的假資料，數字只為了測試，不是任何年度的公告值"]
    fake["sources"] = [deepcopy(next(source for source in sample["sources"] if source["id"] == "income-example"))]
    fake["calendar"] = {"typical": {}, "years": {}}
    fake["income_tax"] = {
        str(year): deepcopy(sample["income_tax"]["2025"])
        for year in (today.year - 1, today.year, today.year + 1)
    }
    fake["basic_living_expense"] = {
        str(year): deepcopy(sample["basic_living_expense"]["2025"])
        for year in (today.year - 1, today.year, today.year + 1)
    }

    def use_one_source(value: object) -> object:
        if isinstance(value, dict):
            return {
                key: ["income-example"] if key == "source_ids" else use_one_source(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [use_one_source(item) for item in value]
        return value

    fake = use_one_source(fake)
    problems = validate_tax_dataset(fake)
    assert not problems, problems
    path = fake_user_dirs / "fake-tax-dataset.json"
    path.write_text(json.dumps(fake, ensure_ascii=False, indent=2), encoding="utf-8")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("TAGCOR_TAX_DATA", str(path))
        yield path


@pytest.fixture(scope="session", autouse=True)
def fake_reference_db(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """法規庫一律**從版控裡的 corpus 現建一份**，不讀工作樹裡那個產生物。

    `reference/reference.sqlite3` 不進版控：開發者的工作樹裡有（一鍵啟動會建），CI 的乾淨
    checkout 上沒有。經 App 預設路徑讀到它的測試因此本機綠、CI 紅 —— 2026-11-14 稅務頁
    法規分頁的搜尋測試就是這樣（`docs/lessons.md` 同日）。2026-10-05 同一件事只在
    `test_reference_library.py` 裡修了，新的 UI 測試經 `window` fixture 又走回預設路徑，
    所以這次做在這一層，不靠每條測試記得。

    要測「法規庫不在」的測試照舊自己 `monkeypatch.setenv` 指到不存在的路徑，會蓋過這裡。
    守門在 `tests/unit/test_reference_db_guard.py`。
    """
    repo_root = Path(__file__).resolve().parents[1]
    builder_path = repo_root / "tools" / "law_sync" / "build_reference_db.py"
    spec = importlib.util.spec_from_file_location("build_reference_db", builder_path)
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    target = tmp_path_factory.mktemp("reference") / "reference.sqlite3"
    builder.build(repo_root / "reference", target=target)
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(REFERENCE_DB_ENV, str(target))
        yield target
