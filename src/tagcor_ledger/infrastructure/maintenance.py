"""Consistent SQLite backup, restore, reset, and human-readable CSV export."""

from __future__ import annotations

import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.domain.models import TransactionFilter
from tagcor_ledger.infrastructure.clock import now_iso
from tagcor_ledger.infrastructure.database import connect_database, initialize_database
from tagcor_ledger.infrastructure.migrations import LATEST_SCHEMA_VERSION
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


class MaintenanceService:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        initialize_database(paths)

    def create_backup(self, *, reason: str = "manual") -> Path:
        backup_id = f"backup_{datetime.now():%Y%m%d_%H%M%S_%f}"
        backup_dir = self.paths.backup_dir / backup_id
        backup_dir.mkdir(parents=True, exist_ok=False)
        database_copy = backup_dir / "ledger.sqlite3"
        with connect_database(self.paths.database_path) as source:
            destination = sqlite3.connect(database_copy)
            try:
                source.backup(destination)
            finally:
                destination.close()
        integrity = _integrity_check(database_copy)
        if integrity != "ok":
            # 訊息就是錯誤碼，不接 `:{integrity}` —— 帶後綴的話
            # `application/failures.py` 查不到這個 key，使用者就會看到英文原文。
            # 需要那串 pragma 輸出時對同一個資料夾跑 `validate_backup()` 就重現得出來。
            raise RuntimeError("BACKUP_INTEGRITY_FAILED")
        manifest = {
            "manifest_version": 1,
            "database_schema_version": LATEST_SCHEMA_VERSION,
            "backup_id": backup_id,
            "created_at": now_iso(),
            "reason": reason,
            "database_file": database_copy.name,
            "sha256": _sha256(database_copy),
            "integrity_check": integrity,
        }
        (backup_dir / "backup_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return backup_dir

    def restore_backup(self, backup_dir: Path, *, create_backup_first: bool = False) -> None:
        validation = self.validate_backup(backup_dir)
        if not validation["valid"]:
            raise ValueError(str(validation["error_code"]))
        database_copy = backup_dir / "ledger.sqlite3"
        if create_backup_first:
            self.create_backup(reason="before_restore")
        with sqlite3.connect(database_copy) as source:
            with sqlite3.connect(self.paths.database_path) as destination:
                source.backup(destination)
        initialize_database(self.paths)

    def reset_ledger(self, *, create_backup_first: bool = False) -> None:
        if create_backup_first and self.paths.database_path.exists():
            self.create_backup(reason="before_reset")
        for path in (
            self.paths.database_path,
            self.paths.database_path.with_name(f"{self.paths.database_path.name}-wal"),
            self.paths.database_path.with_name(f"{self.paths.database_path.name}-shm"),
        ):
            try:
                path.unlink()
            except FileNotFoundError:
                continue
        initialize_database(self.paths)

    def list_backups(self) -> list[dict[str, Any]]:
        backups: list[dict[str, Any]] = []
        if not self.paths.backup_dir.exists():
            return backups
        for backup_dir in sorted(self.paths.backup_dir.iterdir(), reverse=True):
            if not backup_dir.is_dir() or not (backup_dir / "backup_manifest.json").is_file():
                continue
            validation = self.validate_backup(backup_dir)
            backups.append({"path": str(backup_dir), **validation})
        return backups

    def validate_backup(self, backup_dir: Path) -> dict[str, Any]:
        manifest_path = backup_dir / "backup_manifest.json"
        database_copy = backup_dir / "ledger.sqlite3"
        if not manifest_path.is_file() or not database_copy.is_file():
            return {"valid": False, "error_code": "BACKUP_FILES_MISSING"}
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"valid": False, "error_code": "BACKUP_MANIFEST_INVALID"}
        if manifest.get("sha256") != _sha256(database_copy):
            return {"valid": False, "error_code": "BACKUP_CHECKSUM_MISMATCH"}
        integrity = _integrity_check(database_copy)
        if integrity != "ok":
            return {"valid": False, "error_code": "BACKUP_INTEGRITY_FAILED"}
        try:
            with sqlite3.connect(database_copy) as connection:
                row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
            schema_version = int(row[0] or 0) if row is not None else 0
        except sqlite3.Error:
            return {"valid": False, "error_code": "BACKUP_SCHEMA_MISSING"}
        if schema_version > LATEST_SCHEMA_VERSION:
            return {
                "valid": False,
                "error_code": "BACKUP_SCHEMA_TOO_NEW",
                "schema_version": schema_version,
            }
        return {
            "valid": True,
            "error_code": None,
            "schema_version": schema_version,
            "created_at": str(manifest.get("created_at", "")),
            "backup_id": str(manifest.get("backup_id", backup_dir.name)),
        }

    def export_transactions_csv(self, target: Path | None = None) -> Path:
        if target is None:
            target = self.paths.export_dir / f"transactions_{datetime.now():%Y%m%d_%H%M%S}.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        store = LedgerStore(self.paths)
        cursor: tuple[str, str] | None = None
        rows: list[dict[str, Any]] = []
        while True:
            page, cursor = store.list_transactions(
                limit=200,
                cursor=cursor,
                transaction_filter=TransactionFilter(status="all"),
            )
            rows.extend(
                {
                    "交易時間": item.occurred_at,
                    "流向": _entry_type_name(item.entry_type),
                    "帳戶": item.account_name,
                    "轉入帳戶": item.destination_account_name or "",
                    "類別": item.category_name or "",
                    "項目": item.subcategory_name or "",
                    "金額": item.money.to_decimal_string(),
                    "幣別": item.money.currency,
                    "備註": item.description,
                    "狀態": "有效" if item.status == "active" else "作廢",
                    "交易 ID": item.transaction_id,
                }
                for item in page
            )
            if cursor is None:
                break
        fieldnames = [
            "交易時間",
            "流向",
            "帳戶",
            "轉入帳戶",
            "類別",
            "項目",
            "金額",
            "幣別",
            "備註",
            "狀態",
            "交易 ID",
        ]
        with target.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _integrity_check(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        row = connection.execute("PRAGMA integrity_check").fetchone()
    return str(row[0]) if row is not None else "unknown"


def _entry_type_name(value: str) -> str:
    return {
        "income": "收入",
        "expense": "支出",
        "transfer": "轉帳",
        "adjustment": "調整",
    }.get(value, value)
