"""`tests/conftest.py` 那層保護網的陽性對照：它真的有把預設位置換掉。

保護網本身是「沒事就不會被看到」的東西 —— 它壞了，所有測試照樣全綠，只是某一天
忘了傳路徑的那條測試會寫進真帳本。所以這裡直接量：**預設路徑全部落在假目錄底下**，
而且 `src/` 裡每一個從 `platformdirs` 拿位置的名字都被換掉了。
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import platformdirs

from tagcor_ledger.app.logging_setup import fallback_log_dir
from tagcor_ledger.app.path_settings import default_settings_path
from tagcor_ledger.app.paths import APP_AUTHOR, APP_NAME, resolve_app_paths

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"


def _platformdirs_imports() -> list[tuple[str, str]]:
    """`src/` 裡所有 `from platformdirs import X`，回傳 `(模組, X)`。"""
    found: list[tuple[str, str]] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        module = ".".join(path.relative_to(SOURCE_ROOT).with_suffix("").parts)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "platformdirs":
                found.extend((module, alias.asname or alias.name) for alias in node.names)
    return found


def test_the_scanner_finds_the_known_imports() -> None:
    """掃描器本身的陽性對照：已知的三個模組一定要被找到，否則下一條測試是空的。"""
    modules = {module for module, _name in _platformdirs_imports()}
    assert {
        "tagcor_ledger.app.paths",
        "tagcor_ledger.app.path_settings",
        "tagcor_ledger.app.logging_setup",
    } <= modules


def test_every_platformdirs_lookup_in_src_is_redirected(fake_user_dirs: Path) -> None:
    """新增一個 `from platformdirs import` 的模組卻忘了加進保護網，這條會紅。"""
    leaks = []
    for module, name in _platformdirs_imports():
        lookup = getattr(importlib.import_module(module), name)
        if not Path(lookup(APP_NAME, APP_AUTHOR)).is_relative_to(fake_user_dirs):
            leaks.append(f"{module}.{name}")
    assert not leaks, "這些位置沒有被 tests/conftest.py 換掉：" + "、".join(leaks)


def test_default_resolution_never_reaches_the_real_user_dirs(fake_user_dirs: Path) -> None:
    """沒傳路徑時解析出來的每一個位置，都在假目錄底下。"""
    assert default_settings_path().is_relative_to(fake_user_dirs)
    assert fallback_log_dir().is_relative_to(fake_user_dirs)
    for value in resolve_app_paths().as_dict().values():
        assert Path(value).is_relative_to(fake_user_dirs), value


def test_the_real_location_is_somewhere_else(fake_user_dirs: Path) -> None:
    """反過來確認：真正的 `platformdirs` 指的不是假目錄 —— 否則上面幾條證明不了任何事。"""
    real = Path(platformdirs.user_config_dir(APP_NAME, APP_AUTHOR))
    assert not real.is_relative_to(fake_user_dirs)
