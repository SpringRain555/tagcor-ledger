"""Transaction use cases for the Phase 2 MVP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.application.result import Result, new_correlation_id
from tagcor_ledger.application.tags import TagCatalog
from tagcor_ledger.domain.models import TagPath
from tagcor_ledger.domain.money import MoneyError, parse_decimal_string
from tagcor_ledger.domain.validation import ValidationError, validate_ledger_row
from tagcor_ledger.infrastructure.audit import AuditLogWriter, make_audit_event
from tagcor_ledger.infrastructure.csv_ledger import CsvLedgerRepository
from tagcor_ledger.infrastructure.json_config import JsonConfigRepository
from tagcor_ledger.infrastructure.manifest import generate_manifest, write_manifest
from tagcor_ledger.infrastructure.repositories import initialize_data_store


@dataclass(frozen=True)
class LegacyAddTransactionRequest:
    occurred_at: str
    entry_type: str
    amount: str
    tag_path: TagPath
    description: str = ""
    currency: str = "TWD"
    source: str = "manual"
    template_id: str | None = None


@dataclass(frozen=True)
class RecentTransaction:
    transaction_id: str
    occurred_at: str
    entry_type: str
    amount: str
    currency: str
    tag_path_name: str
    description: str
    status: str


def legacy_new_transaction_id() -> str:
    return f"txn_{uuid4().hex}"


def legacy_current_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ledger_path_for_occurred_at(paths: AppPaths, occurred_at: str) -> Path:
    occurred = datetime.fromisoformat(occurred_at)
    return paths.ledger_dir / f"ledger_{occurred.year}.csv"


class LegacyAddTransaction:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    def execute(self, request: AddTransactionRequest) -> Result:
        correlation_id = new_correlation_id()
        try:
            self._ensure_data_store()
            tag_catalog = self._load_tag_catalog()
            snapshot = tag_catalog.snapshot_for_path(request.tag_path)
            parse_decimal_string(request.amount)

            recorded_at = current_timestamp()
            template_id = request.template_id or ""
            row = {
                "schema_version": "1",
                "transaction_id": new_transaction_id(),
                "revision": "1",
                "status": "active",
                "entry_type": request.entry_type,
                "occurred_at": request.occurred_at,
                "recorded_at": recorded_at,
                "updated_at": recorded_at,
                "currency": request.currency,
                "amount": request.amount,
                "l1_id": request.tag_path.l1_id,
                "l2_id": request.tag_path.l2_id,
                "l3_id": request.tag_path.l3_id,
                "l4_id": request.tag_path.l4_id,
                "l1_name_snapshot": snapshot.l1_name,
                "l2_name_snapshot": snapshot.l2_name,
                "l3_name_snapshot": snapshot.l3_name,
                "l4_name_snapshot": snapshot.l4_name,
                "description": request.description,
                "source": request.source,
                "template_id": template_id,
                "correlation_id": correlation_id,
            }
            validate_ledger_row(row)

            ledger_path = ledger_path_for_occurred_at(self.paths, request.occurred_at)
            CsvLedgerRepository(ledger_path).append_row(row)
            self._write_audit(row, ledger_path, correlation_id)
            self._update_manifest(ledger_path)

            return Result.ok(
                "Transaction added.",
                details={"transaction_id": row["transaction_id"], "ledger_file": str(ledger_path)},
                correlation_id=correlation_id,
            )
        except (MoneyError, ValidationError, ValueError) as exc:
            return Result.fail(
                "VALIDATION_FAILED",
                str(exc),
                correlation_id=correlation_id,
            )
        except OSError as exc:
            return Result.fail(
                "FILE_WRITE_FAILED",
                str(exc),
                correlation_id=correlation_id,
            )

    def _ensure_data_store(self) -> None:
        if not (self.paths.config_dir / "tags.json").exists():
            initialize_data_store(self.paths)

    def _load_tag_catalog(self) -> TagCatalog:
        tags_document = JsonConfigRepository(self.paths.config_dir / "tags.json").read()
        return TagCatalog(tags_document)

    def _write_audit(self, row: dict[str, str], ledger_path: Path, correlation_id: str) -> None:
        event = make_audit_event(
            correlation_id=correlation_id,
            action="transaction.create",
            entity_type="transaction",
            entity_id=row["transaction_id"],
            details={"ledger_file": ledger_path.relative_to(self.paths.data_dir).as_posix()},
        )
        AuditLogWriter(self.paths.log_dir / "audit.log").write_event(event)

    def _update_manifest(self, ledger_path: Path) -> None:
        files = [
            self.paths.config_dir / "settings.json",
            self.paths.config_dir / "tags.json",
            self.paths.config_dir / "templates.json",
            ledger_path,
        ]
        existing_files = [path for path in files if path.exists()]
        manifest = generate_manifest(self.paths.data_dir, existing_files)
        write_manifest(self.paths.config_dir / "data_manifest.json", manifest)


class LegacyListRecentTransactions:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    def execute(self, limit: int = 20) -> Result:
        try:
            rows = self._read_all_rows()
            rows.sort(key=lambda row: (row["occurred_at"], row["recorded_at"]), reverse=True)
            recent = [row_to_recent_transaction(row) for row in rows[:limit]]
            return Result.ok(
                "Recent transactions loaded.",
                details={"transactions": [transaction_to_dict(item) for item in recent]},
            )
        except (OSError, ValueError, ValidationError) as exc:
            return Result.fail("LIST_TRANSACTIONS_FAILED", str(exc))

    def _read_all_rows(self) -> list[dict[str, str]]:
        if not self.paths.ledger_dir.exists():
            return []
        rows: list[dict[str, str]] = []
        for ledger_file in sorted(self.paths.ledger_dir.glob("ledger_*.csv")):
            rows.extend(CsvLedgerRepository(ledger_file).read_rows())
        return rows


def row_to_recent_transaction(row: dict[str, str]) -> RecentTransaction:
    tag_path_name = " / ".join(
        [
            row["l1_name_snapshot"],
            row["l2_name_snapshot"],
            row["l3_name_snapshot"],
            row["l4_name_snapshot"],
        ]
    )
    return RecentTransaction(
        transaction_id=row["transaction_id"],
        occurred_at=row["occurred_at"],
        entry_type=row["entry_type"],
        amount=row["amount"],
        currency=row["currency"],
        tag_path_name=tag_path_name,
        description=row["description"],
        status=row["status"],
    )


def legacy_transaction_to_dict(transaction: RecentTransaction) -> dict[str, Any]:
    return {
        "transaction_id": transaction.transaction_id,
        "occurred_at": transaction.occurred_at,
        "entry_type": transaction.entry_type,
        "amount": transaction.amount,
        "currency": transaction.currency,
        "tag_path_name": transaction.tag_path_name,
        "description": transaction.description,
        "status": transaction.status,
    }


# The SQLite implementation supersedes the original CSV prototype while these
# re-exports keep the public import path stable for scripts and integrations.
from tagcor_ledger.application.transaction_service import (  # noqa: E402,F401
    AddTransaction,
    AddTransactionRequest,
    AddTransfer,
    AddTransferRequest,
    ListRecentTransactions,
    ListTransactions,
    TransactionQuery,
    UpdateTransaction,
    UpdateTransactionRequest,
    VoidTransaction,
    current_timestamp,
    new_transaction_id,
    transaction_to_dict,
)
