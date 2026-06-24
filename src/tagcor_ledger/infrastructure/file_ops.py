"""Filesystem helpers for safe writes."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8", newline: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding=encoding,
        newline=newline,
        dir=path.parent,
        delete=False,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as tmp:
        tmp.write(content)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "wb",
        dir=path.parent,
        delete=False,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as tmp:
        tmp.write(content)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)
