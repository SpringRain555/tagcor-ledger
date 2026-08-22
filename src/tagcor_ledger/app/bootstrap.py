"""啟動與相依組裝：CLI、GUI 與測試共用同一條路徑解析流程。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tagcor_ledger.app.paths import AppPaths, ensure_directories, resolve_app_paths
from tagcor_ledger.app.resources import resource_exists


@dataclass(frozen=True)
class StartupContext:
    """解析完成的啟動狀態。CLI、GUI 與測試共用同一份，路徑才不會有第二種算法。"""

    paths: AppPaths
    styles_available: bool


def bootstrap(data_dir: str | Path | None = None, *, ensure_dirs: bool = False) -> StartupContext:
    paths = resolve_app_paths(data_dir=data_dir)
    if ensure_dirs:
        ensure_directories(paths)
    return StartupContext(paths=paths, styles_available=resource_exists("styles.qss"))
