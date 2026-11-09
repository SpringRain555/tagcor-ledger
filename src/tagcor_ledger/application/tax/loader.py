"""載入公開的稅務資料集；資料問題不影響記帳功能。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from tagcor_ledger.domain.tax.dataset import TaxDataset
from tagcor_ledger.domain.tax.dataset_parse import TaxDatasetInvalid, parse_tax_dataset
from tagcor_ledger.domain.tax.freshness import DatasetLoad, DatasetLoadState

TAX_DATA_ENV = "TAGCOR_TAX_DATA"


def dataset_stat_signature(path: Path) -> tuple[Path, int | None, int | None]:
    """回傳載入快取使用的檔案版本；無法 stat 時交由 loader 回報檔案狀態。"""
    try:
        stat = path.stat()
    except OSError:
        return path, None, None
    return path, stat.st_mtime_ns, stat.st_size


def default_tax_dataset_path() -> Path:
    """使用明確指定的資料路徑，否則讀取 repo 內的公開資料集。"""
    override = os.environ.get(TAX_DATA_ENV)
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parents[4] / "reference" / "tax" / "dataset.json"


def load_tax_dataset(path: Path) -> DatasetLoad:
    """讀取並驗證稅務資料集，將所有檔案與格式錯誤轉成狀態。"""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return DatasetLoad(DatasetLoadState.MISSING)
    except UnicodeDecodeError:
        return DatasetLoad(
            DatasetLoadState.INVALID,
            problems=("稅務資料不是有效的 UTF-8 編碼。",),
        )
    except OSError:
        return DatasetLoad(
            DatasetLoadState.INVALID,
            problems=("稅務資料讀不開。",),
        )

    if text.startswith("\ufeff"):
        return DatasetLoad(
            DatasetLoadState.INVALID,
            problems=("稅務資料含有 UTF-8 BOM。",),
        )
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        return DatasetLoad(
            DatasetLoadState.INVALID,
            problems=(f"稅務資料的 JSON 格式不正確（第 {exc.lineno} 行第 {exc.colno} 欄）。",),
        )

    try:
        dataset: TaxDataset = parse_tax_dataset(raw)
    except TaxDatasetInvalid as exc:
        return DatasetLoad(DatasetLoadState.INVALID, problems=exc.problems)
    return DatasetLoad(DatasetLoadState.OK, dataset=dataset)
