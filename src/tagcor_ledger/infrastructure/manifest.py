"""Data manifest generation and persistence."""

from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
from typing import Any

from tagcor_ledger.infrastructure.json_config import JsonConfigRepository


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def infer_schema_version(path: Path) -> int:
    if path.suffix.lower() == ".json":
        import json

        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        version = data.get("schema_version", 1)
        return int(version)
    return 1


def generate_manifest(data_root: Path, files: list[Path]) -> dict[str, Any]:
    root = data_root.resolve()
    entries: list[dict[str, Any]] = []
    for file_path in sorted(files, key=lambda path: path.as_posix()):
        resolved = file_path.resolve()
        entries.append(
            {
                "path": resolved.relative_to(root).as_posix(),
                "schema_version": infer_schema_version(resolved),
                "sha256": sha256_file(resolved),
                "updated_at": datetime.fromtimestamp(
                    resolved.stat().st_mtime
                ).astimezone().isoformat(timespec="seconds"),
            }
        )
    return {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "files": entries,
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    JsonConfigRepository(path).write(manifest)
