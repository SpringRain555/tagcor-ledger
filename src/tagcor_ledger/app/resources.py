"""Resource helpers that work in editable and packaged installs."""

from __future__ import annotations

from importlib import resources


RESOURCE_PACKAGE = "tagcor_ledger.resources"


def resource_exists(name: str) -> bool:
    return (resources.files(RESOURCE_PACKAGE) / name).is_file()


def read_text_resource(name: str, encoding: str = "utf-8") -> str:
    return (resources.files(RESOURCE_PACKAGE) / name).read_text(encoding=encoding)
