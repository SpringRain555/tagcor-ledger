"""JSON config repositories."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

from tagcor_ledger.infrastructure.file_ops import atomic_write_text


JsonValidator = Callable[[Mapping[str, Any]], None]


class JsonConfigRepository:
    def __init__(self, path: Path, validator: JsonValidator | None = None) -> None:
        self.path = path
        self.validator = validator

    def read(self) -> dict[str, Any]:
        with self.path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if self.validator is not None:
            self.validator(data)
        return data

    def write(self, document: Mapping[str, Any]) -> None:
        if self.validator is not None:
            self.validator(document)
        content = json.dumps(document, ensure_ascii=False, indent=2)
        atomic_write_text(self.path, f"{content}\n", encoding="utf-8", newline="\n")
