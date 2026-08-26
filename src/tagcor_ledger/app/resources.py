"""取得打包資源。editable 安裝與打包安裝兩種情況都要能找到。"""

from __future__ import annotations

from importlib import resources
from pathlib import Path


RESOURCE_PACKAGE = "tagcor_ledger.resources"


def resource_exists(name: str) -> bool:
    return (resources.files(RESOURCE_PACKAGE) / name).is_file()


def read_text_resource(name: str, encoding: str = "utf-8") -> str:
    return (resources.files(RESOURCE_PACKAGE) / name).read_text(encoding=encoding)


def resource_filesystem_path(name: str) -> Path | None:
    """資源在檔案系統上的實際路徑，取不到就回 `None`。

    **只給 QSS 的 `url()` 用。** 其他地方一律走 `read_text_resource()` ——
    那個不在乎資源到底是不是一個真的檔案，這個在乎。

    Qt 的 stylesheet 只認檔案系統路徑與 Qt resource 路徑，餵它 bytes 沒有用
    （`data:` URI 實測不畫）。而 `importlib.resources` 不保證資源是真的檔案：
    從 zip 匯入時 `files()` 回的是一個虛擬路徑，要 `as_file()` 解壓到暫存目錄，
    而那個暫存檔在 context manager 結束時就被刪掉了 —— 對「整個 process 都要有效」
    的樣式表來說沒有意義。

    所以這裡**不做解壓**：拿得到真檔案就回它，拿不到就回 `None` 讓呼叫端退回
    沒有圖的樣式。本專案是從原始碼跑的（conda env ＋ `python -m tagcor_ledger`），
    正常情況一定拿得到。
    """
    candidate = resources.files(RESOURCE_PACKAGE) / name
    try:
        path = Path(str(candidate))
    except (TypeError, ValueError):
        return None
    return path if path.is_file() else None
