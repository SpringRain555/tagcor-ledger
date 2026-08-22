"""use case 共用的 `Result`。

`message` 是**畫面上唯一會出現的那句話**；`details["detail"]` 只給診斷用，永遠不顯示。
`details["reason"]` 是廢除的 key，見 `failures.py`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


def new_correlation_id() -> str:
    return f"corr_{uuid4().hex}"


@dataclass(frozen=True)
class Result:
    success: bool
    message: str
    error_code: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = field(default_factory=new_correlation_id)

    @classmethod
    def ok(
        cls,
        message: str = "OK",
        *,
        details: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> "Result":
        return cls(
            success=True,
            message=message,
            details=dict(details or {}),
            correlation_id=correlation_id or new_correlation_id(),
        )

    @classmethod
    def fail(
        cls,
        error_code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> "Result":
        return cls(
            success=False,
            error_code=error_code,
            message=message,
            details=dict(details or {}),
            correlation_id=correlation_id or new_correlation_id(),
        )
