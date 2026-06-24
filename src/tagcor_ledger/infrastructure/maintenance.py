"""Consistent SQLite backup, restore, and human-readable CSV export."""

from __future__ import annotations

import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.infrastructure.database import connect_database, initialize_database, now_iso
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
            raise RuntimeError(f"BACKUP_INTEGRITY_FAILED:{integrity}")
        manifest = {
            "schema_version": 1,
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

    def restore_backup(self, backup_dir: Path) -> None:
        manifest_path = backup_dir / "backup_manifest.json"
        database_copy = backup_dir / "ledger.sqlite3"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("sha256") != _sha256(database_copy):
            raise ValueError("BACKUP_CHECKSUM_MISMATCH")
        if _integrity_check(database_copy) != "ok":
            raise ValueError("BACKUP_INTEGRITY_FAILED")
        self.create_backup(reason="before_restore")
        with sqlite3.connect(database_copy) as source:
            with sqlite3.connect(self.paths.database_path) as destination:
                source.backup(destination)

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
                include_voided=True,
            )
            rows.extend(
                {
                    "交易時間": item.occurred_at,
                    "類型": _entry_type_name(item.entry_type),
                    "帳戶": item.account_name,
                    "轉入帳戶": item.destination_account_name or "",
                    "分類": item.category_name or "",
                    "細項": item.subcategory_name or "",
                    "對象／商家": item.payee_name,
                    "金額": item.money.to_decimal_string(),
                    "幣別": item.money.currency,
                    "備註": item.description,
                    "狀態": "有效" if item.status == "active" else "已作廢",
                    "交易編號": item.transaction_id,
                }
                for item in page
            )
            if cursor is None:
                break
        fieldnames = [
            "交易時間",
            "類型",
            "帳戶",
            "轉入帳戶",
            "分類",
            "細項",
            "對象／商家",
            "金額",
            "幣別",
            "備註",
            "狀態",
            "交易編號",
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
