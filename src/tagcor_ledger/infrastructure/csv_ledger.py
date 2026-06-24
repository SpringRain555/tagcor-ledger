"""CSV ledger repository for Phase 1."""

from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path
from typing import Mapping, Sequence

from tagcor_ledger.domain.validation import LEDGER_FIELDS, validate_ledger_row
from tagcor_ledger.infrastructure.file_ops import atomic_write_text


class CsvLedgerRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read_rows(self) -> list[dict[str, str]]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != LEDGER_FIELDS:
                raise ValueError("Ledger CSV header does not match the canonical field order.")
            rows = [dict(row) for row in reader]
        for row in rows:
            validate_ledger_row(row)
        return rows

    def write_rows(self, rows: Sequence[Mapping[str, str]]) -> None:
        for row in rows:
            validate_ledger_row(row)
        buffer = StringIO()
        writer = csv.DictWriter(buffer, fieldnames=LEDGER_FIELDS, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
        atomic_write_text(self.path, buffer.getvalue(), encoding="utf-8", newline="")

    def append_row(self, row: Mapping[str, str]) -> None:
        validate_ledger_row(row)
        rows = self.read_rows()
        rows.append(dict(row))
        self.write_rows(rows)
