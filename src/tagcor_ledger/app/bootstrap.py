"""啟動與相依組裝：CLI、GUI 與測試共用同一條路徑解析流程。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tagcor_ledger.app.data_location import LocationSource
from tagcor_ledger.app.paths import AppPaths, ensure_directories, resolve_location
from tagcor_ledger.app.resources import resource_exists


@dataclass(frozen=True)
class StartupContext:
    """解析完成的啟動狀態。CLI、GUI 與測試共用同一份，路徑才不會有第二種算法。

    `location` 是 `CHOOSE_ON_FIRST_RUN` 時，`paths` 只是暫時的落腳處（使用者資料夾）——
    GUI 要先問使用者資料放哪裡（ADR-0018），問完才換成真正的位置。
    """

    paths: AppPaths
    styles_available: bool
    location: LocationSource = LocationSource.OVERRIDE


def bootstrap(data_dir: str | Path | None = None, *, ensure_dirs: bool = False) -> StartupContext:
    paths, location = resolve_location(data_dir=data_dir)
    if ensure_dirs:
        ensure_directories(paths)
    return StartupContext(
        paths=paths,
        styles_available=resource_exists("styles.qss"),
        location=location,
    )
