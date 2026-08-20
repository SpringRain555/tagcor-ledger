"""記住視窗的大小與位置。

**這是 UI 狀態，不是帳務資料。** 所以它寫在 `config_dir`（跟 `system_paths.json`
同一層），不進 `ledger.sqlite3` —— 帳務資料庫的每一次 schema 變動都要寫 migration，
為了「上次視窗多大」付那個代價不划算，而且它也不該出現在備份與還原的語意裡。

讀不到、格式壞掉、數字不合理，一律當成沒有設定過，回退到預設大小。
**這個檔案壞掉不該讓程式開不起來。**
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

FILE_NAME = "window.json"

DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 760

MINIMUM_WIDTH = 1024
MINIMUM_HEIGHT = 680
"""再小就不給拖。有下限，版面才有一個可以被驗證的最壞情況。"""

# 螢幕拔掉或解析度變小時，存下來的座標可能落在畫面外。給一個寬鬆的上限擋掉離譜的值。
_MAX_REASONABLE = 20_000


@dataclass(frozen=True)
class WindowGeometry:
    x: int
    y: int
    width: int
    height: int


def state_path(config_dir: Path) -> Path:
    return config_dir / FILE_NAME


def load_geometry(config_dir: Path) -> WindowGeometry | None:
    """讀回上次的視窗大小與位置；沒有或不合理就回 `None`。"""
    try:
        raw = json.loads(state_path(config_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        geometry = WindowGeometry(
            x=int(raw["x"]),
            y=int(raw["y"]),
            width=int(raw["width"]),
            height=int(raw["height"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if not MINIMUM_WIDTH <= geometry.width <= _MAX_REASONABLE:
        return None
    if not MINIMUM_HEIGHT <= geometry.height <= _MAX_REASONABLE:
        return None
    if abs(geometry.x) > _MAX_REASONABLE or abs(geometry.y) > _MAX_REASONABLE:
        return None
    return geometry


def save_geometry(config_dir: Path, geometry: WindowGeometry) -> None:
    """寫入視窗大小與位置。寫不進去就算了 —— 這不值得打斷關閉流程。"""
    try:
        config_dir.mkdir(parents=True, exist_ok=True)
        state_path(config_dir).write_text(
            json.dumps(
                {
                    "x": geometry.x,
                    "y": geometry.y,
                    "width": geometry.width,
                    "height": geometry.height,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        return
