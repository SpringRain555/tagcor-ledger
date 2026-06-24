"""Repository protocols and initialization helpers for Phase 1."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

from tagcor_ledger.app.paths import AppPaths, ensure_directories
from tagcor_ledger.domain.validation import (
    validate_settings_document,
    validate_tags_document,
    validate_templates_document,
)
from tagcor_ledger.infrastructure.database import initialize_database
from tagcor_ledger.infrastructure.csv_ledger import CsvLedgerRepository
from tagcor_ledger.infrastructure.json_config import JsonConfigRepository
from tagcor_ledger.infrastructure.manifest import generate_manifest, write_manifest


class JsonRepository(Protocol):
    path: Path

    def read(self) -> dict[str, object]:
        ...

    def write(self, document: dict[str, object]) -> None:
        ...


def phase1_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def default_settings(paths: AppPaths, now: str | None = None) -> dict[str, object]:
    timestamp = now or phase1_timestamp()
    return {
        "schema_version": 1,
        "app_data_version": "1",
        "data_dir": str(paths.data_dir),
        "config_dir": str(paths.config_dir),
        "ledger_dir": str(paths.ledger_dir),
        "backup_dir": str(paths.backup_dir),
        "export_dir": str(paths.export_dir),
        "log_dir": str(paths.log_dir),
        "timezone": "Asia/Taipei",
        "default_currency": "TWD",
        "startup_backup": "daily",
        "export_csv_encoding": "utf-8-sig",
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def default_tags(now: str | None = None) -> dict[str, object]:
    timestamp = now or phase1_timestamp()
    return {
        "schema_version": 1,
        "levels": [
            {"level": 1, "code": "l1", "name": "流向", "required": True},
            {"level": 2, "code": "l2", "name": "帳戶", "required": True},
            {"level": 3, "code": "l3", "name": "分類", "required": True},
            {"level": 4, "code": "l4", "name": "細項", "required": True},
        ],
        "tags": [
            {
                "tag_id": "tag_expense",
                "parent_id": None,
                "level": 1,
                "name": "支出",
                "status": "active",
                "sort_order": 10,
                "aliases": [],
                "created_at": timestamp,
                "updated_at": timestamp,
                "archived_at": None,
            },
            {
                "tag_id": "tag_cash",
                "parent_id": "tag_expense",
                "level": 2,
                "name": "現金",
                "status": "active",
                "sort_order": 10,
                "aliases": [],
                "created_at": timestamp,
                "updated_at": timestamp,
                "archived_at": None,
            },
            {
                "tag_id": "tag_food",
                "parent_id": "tag_cash",
                "level": 3,
                "name": "伙食",
                "status": "active",
                "sort_order": 10,
                "aliases": [],
                "created_at": timestamp,
                "updated_at": timestamp,
                "archived_at": None,
            },
            {
                "tag_id": "tag_711",
                "parent_id": "tag_food",
                "level": 4,
                "name": "7-11",
                "status": "active",
                "sort_order": 10,
                "aliases": ["小七"],
                "created_at": timestamp,
                "updated_at": timestamp,
                "archived_at": None,
            },
        ],
    }


def default_templates(now: str | None = None) -> dict[str, object]:
    timestamp = now or phase1_timestamp()
    return {
        "schema_version": 1,
        "templates": [
            {
                "template_id": "tpl_breakfast",
                "name": "早餐",
                "status": "active",
                "l1_id": "tag_expense",
                "l2_id": "tag_cash",
                "l3_id": "tag_food",
                "l4_id": "tag_711",
                "default_amount": "0",
                "default_description": "",
                "focus_target": "amount",
                "sort_order": 10,
                "created_at": timestamp,
                "updated_at": timestamp,
                "archived_at": None,
            }
        ],
    }


def initialize_legacy_data_store(paths: AppPaths, *, overwrite: bool = False) -> dict[str, Path]:
    ensure_directories(paths)
    now = phase1_timestamp()
    settings_path = paths.config_dir / "settings.json"
    tags_path = paths.config_dir / "tags.json"
    templates_path = paths.config_dir / "templates.json"
    ledger_path = paths.ledger_dir / f"ledger_{datetime.now().year}.csv"
    manifest_path = paths.config_dir / "data_manifest.json"

    tags_document = default_tags(now)
    settings_repo = JsonConfigRepository(settings_path, validate_settings_document)
    tags_repo = JsonConfigRepository(tags_path, validate_tags_document)
    templates_repo = JsonConfigRepository(
        templates_path,
        lambda document: validate_templates_document(document, tags_document),
    )

    if overwrite or not settings_path.exists():
        settings_repo.write(default_settings(paths, now))
    if overwrite or not tags_path.exists():
        tags_repo.write(tags_document)
    else:
        tags_document = tags_repo.read()
    if overwrite or not templates_path.exists():
        templates_repo = JsonConfigRepository(
            templates_path,
            lambda document: validate_templates_document(document, tags_document),
        )
        templates_repo.write(default_templates(now))
    if overwrite or not ledger_path.exists():
        CsvLedgerRepository(ledger_path).write_rows([])

    manifest = generate_manifest(paths.data_dir, [settings_path, tags_path, templates_path, ledger_path])
    write_manifest(manifest_path, manifest)
    return {
        "settings": settings_path,
        "tags": tags_path,
        "templates": templates_path,
        "ledger": ledger_path,
        "manifest": manifest_path,
    }


def initialize_data_store(paths: AppPaths, *, overwrite: bool = False) -> dict[str, Path]:
    """Initialize the canonical SQLite store without destructive overwrite."""

    del overwrite
    return {"database": initialize_database(paths)}
