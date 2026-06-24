"""Audit log writer using JSON Lines."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from tagcor_ledger.domain.validation import validate_datetime, validate_id


def new_audit_id() -> str:
    return f"aud_{uuid4().hex}"


def validate_audit_event(event: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "audit_id",
        "occurred_at",
        "correlation_id",
        "actor",
        "action",
        "entity_type",
        "entity_id",
        "result",
        "details",
    }
    missing = required.difference(event)
    if missing:
        raise ValueError(f"Audit event missing keys: {', '.join(sorted(missing))}")
    if event["schema_version"] != 1:
        raise ValueError("Audit schema_version must be 1.")
    validate_id(str(event["audit_id"]), "aud", "audit.audit_id")
    validate_id(str(event["correlation_id"]), "corr", "audit.correlation_id")
    validate_datetime(str(event["occurred_at"]), "audit.occurred_at")
    if event["result"] not in {"success", "failure"}:
        raise ValueError("Audit result must be success or failure.")
    if not isinstance(event["details"], Mapping):
        raise ValueError("Audit details must be an object.")


class AuditLogWriter:
    def __init__(self, path: Path) -> None:
        self.path = path

    def write_event(self, event: Mapping[str, Any]) -> None:
        validate_audit_event(event)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"{line}\n")


def make_audit_event(
    *,
    correlation_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    result: str = "success",
    details: Mapping[str, Any] | None = None,
    actor: str = "local_user",
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    timestamp = (occurred_at or datetime.now().astimezone()).isoformat(timespec="seconds")
    return {
        "schema_version": 1,
        "audit_id": new_audit_id(),
        "occurred_at": timestamp,
        "correlation_id": correlation_id,
        "actor": actor,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "result": result,
        "details": dict(details or {}),
    }
