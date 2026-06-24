"""Application bootstrap and dependency wiring."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tagcor_ledger.app.paths import AppPaths, ensure_directories, resolve_app_paths
from tagcor_ledger.app.resources import resource_exists


@dataclass(frozen=True)
class StartupContext:
    """Resolved startup state shared by CLI, GUI, and tests."""

    paths: AppPaths
    styles_available: bool


def bootstrap(data_dir: str | Path | None = None, *, ensure_dirs: bool = False) -> StartupContext:
    paths = resolve_app_paths(data_dir=data_dir)
    if ensure_dirs:
        ensure_directories(paths)
    return StartupContext(paths=paths, styles_available=resource_exists("styles.qss"))
