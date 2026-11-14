"""TagCor Ledger 的啟動完成標記位置與共用檔案操作。"""

from __future__ import annotations

from pathlib import Path

from local_qt_app.ready_marker import (
    MARKER_FILE_NAME,
    clear as _clear,
    mark_ready as _mark_ready,
    marker_path as _marker_path,
)

from tagcor_ledger.app.paths import AppPaths

__all__ = ["MARKER_FILE_NAME", "clear", "mark_ready", "marker_path"]


def marker_path(paths: AppPaths) -> Path:
    """標記放在本次啟動使用的暫存資料夾，供 `--json` 傳給啟動器。"""
    return _marker_path(paths.tmp_dir)


def clear(path: Path) -> None:
    """清除舊標記；失敗時維持 best-effort，不阻止程式啟動。"""
    _clear(path)


def mark_ready(path: Path) -> bool:
    """在視窗顯示後寫入標記；失敗只回報給日誌，不阻止程式啟動。"""
    return _mark_ready(path)
