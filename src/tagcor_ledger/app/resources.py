"""取得打包資源。editable 安裝與打包安裝兩種情況都要能找到。"""

from __future__ import annotations

from importlib import resources


RESOURCE_PACKAGE = "tagcor_ledger.resources"


def resource_exists(name: str) -> bool:
    return (resources.files(RESOURCE_PACKAGE) / name).is_file()


def read_text_resource(name: str, encoding: str = "utf-8") -> str:
    return (resources.files(RESOURCE_PACKAGE) / name).read_text(encoding=encoding)
