"""稅務申報輸入、扣繳憑單覆寫與提醒標記的持久化。"""

from __future__ import annotations

from collections.abc import Iterable
import sqlite3
from uuid import uuid4

from tagcor_ledger.domain.tax.kinds import (
    DeductionChoice,
    FilingStatus,
    IncomeKind,
    OVERRIDABLE_INCOME_KINDS,
    ReminderMark,
    TaxKind,
)
from tagcor_ledger.domain.tax.records import ReminderMarkRecord, TaxYearInputs, TaxYearOverride
from tagcor_ledger.infrastructure.clock import now_iso
from tagcor_ledger.infrastructure.database import connect_database, database_transaction
from tagcor_ledger.infrastructure.stores.base import StoreBase


class TaxFilingStore(StoreBase):
    def get_tax_year_inputs(self, income_year: int) -> TaxYearInputs | None:
        with connect_database(self.paths.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM tax_year_inputs WHERE income_year = ?", (income_year,)
            ).fetchone()
        return _row_to_inputs(row) if row is not None else None

    def latest_tax_year_inputs_before(self, income_year: int) -> TaxYearInputs | None:
        with connect_database(self.paths.database_path) as connection:
            row = connection.execute(
                """
                SELECT * FROM tax_year_inputs
                WHERE income_year < ?
                ORDER BY income_year DESC
                LIMIT 1
                """,
                (income_year,),
            ).fetchone()
        return _row_to_inputs(row) if row is not None else None

    def save_tax_year_inputs(self, inputs: TaxYearInputs) -> None:
        if (
            inputs.dependents < 0
            or inputs.dependents_70_plus < 0
            or inputs.dependents_70_plus > inputs.dependents
            or (inputs.official_tax_minor is not None and inputs.official_tax_minor < 0)
        ):
            raise ValueError("TAX_INPUTS_INVALID")
        values = {
            "filing": inputs.filing.value,
            "deduction": inputs.deduction.value,
            "other_special_deductions": int(inputs.other_special_deductions),
            "dependents_have_income": int(inputs.dependents_have_income),
            "filer_70_plus": int(inputs.filer_70_plus),
            "dependents": inputs.dependents,
            "dependents_70_plus": inputs.dependents_70_plus,
            "official_tax_minor": inputs.official_tax_minor,
            "official_balance_minor": inputs.official_balance_minor,
        }
        with database_transaction(self.paths.database_path) as connection:
            existing = connection.execute(
                "SELECT * FROM tax_year_inputs WHERE income_year = ?", (inputs.income_year,)
            ).fetchone()
            fields = sorted(
                name
                for name, value in values.items()
                if existing is None or existing[name] != value
            )
            connection.execute(
                """
                INSERT INTO tax_year_inputs(
                    income_year, filing, deduction, other_special_deductions,
                    dependents_have_income, filer_70_plus, dependents, dependents_70_plus,
                    official_tax_minor, official_balance_minor, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(income_year) DO UPDATE SET
                    filing = excluded.filing,
                    deduction = excluded.deduction,
                    other_special_deductions = excluded.other_special_deductions,
                    dependents_have_income = excluded.dependents_have_income,
                    filer_70_plus = excluded.filer_70_plus,
                    dependents = excluded.dependents,
                    dependents_70_plus = excluded.dependents_70_plus,
                    official_tax_minor = excluded.official_tax_minor,
                    official_balance_minor = excluded.official_balance_minor,
                    updated_at = excluded.updated_at
                """,
                (inputs.income_year, *values.values(), now_iso()),
            )
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action="tax_year_inputs.save",
                entity_type="tax_year",
                entity_id=str(inputs.income_year),
                details={"fields": fields},
            )

    def list_tax_year_overrides(self, income_year: int) -> dict[IncomeKind, TaxYearOverride]:
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                """
                SELECT income_year, income_kind, gross_minor, withheld_minor
                FROM tax_year_overrides
                WHERE income_year = ?
                ORDER BY income_kind
                """,
                (income_year,),
            ).fetchall()
        return {
            IncomeKind(str(row["income_kind"])): _row_to_override(row)
            for row in rows
        }

    def save_tax_year_override(self, override: TaxYearOverride) -> None:
        if override.income_kind not in OVERRIDABLE_INCOME_KINDS:
            raise ValueError("TAX_OVERRIDE_KIND_INVALID")
        if (
            (override.gross_minor is not None and override.gross_minor < 0)
            or (override.withheld_minor is not None and override.withheld_minor < 0)
        ):
            raise ValueError("TAX_OVERRIDE_AMOUNT_INVALID")

        kind = override.income_kind
        key = (override.income_year, kind.value)
        with database_transaction(self.paths.database_path) as connection:
            existing = connection.execute(
                """
                SELECT gross_minor, withheld_minor FROM tax_year_overrides
                WHERE income_year = ? AND income_kind = ?
                """,
                key,
            ).fetchone()
            if override.gross_minor is None and override.withheld_minor is None:
                connection.execute(
                    """
                    DELETE FROM tax_year_overrides
                    WHERE income_year = ? AND income_kind = ?
                    """,
                    key,
                )
                action = "tax_override.clear"
                fields = sorted(
                    name
                    for name in ("gross_minor", "withheld_minor")
                    if existing is not None and existing[name] is not None
                )
            else:
                values = {
                    "gross_minor": override.gross_minor,
                    "withheld_minor": override.withheld_minor,
                }
                fields = sorted(
                    name
                    for name, value in values.items()
                    if existing is None or existing[name] != value
                )
                connection.execute(
                    """
                    INSERT INTO tax_year_overrides(
                        income_year, income_kind, gross_minor, withheld_minor, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(income_year, income_kind) DO UPDATE SET
                        gross_minor = excluded.gross_minor,
                        withheld_minor = excluded.withheld_minor,
                        updated_at = excluded.updated_at
                    """,
                    (*key, override.gross_minor, override.withheld_minor, now_iso()),
                )
                action = "tax_override.save"
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action=action,
                entity_type="tax_year",
                entity_id=f"{override.income_year}:{kind.value}",
                details={"fields": fields},
            )

    def list_reminder_marks(
        self, *, cycle_years: Iterable[int]
    ) -> dict[tuple[TaxKind, int], ReminderMarkRecord]:
        years = tuple(dict.fromkeys(cycle_years))
        if not years:
            return {}
        placeholders = ", ".join("?" for _ in years)
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT kind, cycle_year, mark, marked_at
                FROM tax_reminder_marks
                WHERE cycle_year IN ({placeholders})
                ORDER BY cycle_year, kind
                """,
                years,
            ).fetchall()
        return {
            (record.kind, record.cycle_year): record
            for record in (_row_to_reminder_mark(row) for row in rows)
        }

    def set_reminder_mark(
        self, *, kind: TaxKind, cycle_year: int, mark: ReminderMark | None
    ) -> None:
        with database_transaction(self.paths.database_path) as connection:
            key = (kind.value, cycle_year)
            if mark is None:
                connection.execute(
                    "DELETE FROM tax_reminder_marks WHERE kind = ? AND cycle_year = ?", key
                )
                action = "tax_reminder.unmark"
            else:
                connection.execute(
                    """
                    INSERT INTO tax_reminder_marks(kind, cycle_year, mark, marked_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(kind, cycle_year) DO UPDATE SET
                        mark = excluded.mark,
                        marked_at = excluded.marked_at
                    """,
                    (*key, mark.value, now_iso()),
                )
                action = "tax_reminder.mark"
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action=action,
                entity_type="tax_reminder",
                entity_id=f"{kind.value}:{cycle_year}",
                details={"mark": mark.value if mark is not None else None},
            )


def _row_to_inputs(row: sqlite3.Row) -> TaxYearInputs:
    return TaxYearInputs(
        income_year=int(row["income_year"]),
        filing=FilingStatus(str(row["filing"])),
        deduction=DeductionChoice(str(row["deduction"])),
        other_special_deductions=bool(row["other_special_deductions"]),
        dependents_have_income=bool(row["dependents_have_income"]),
        filer_70_plus=bool(row["filer_70_plus"]),
        dependents=int(row["dependents"]),
        dependents_70_plus=int(row["dependents_70_plus"]),
        official_tax_minor=(
            int(row["official_tax_minor"]) if row["official_tax_minor"] is not None else None
        ),
        official_balance_minor=(
            int(row["official_balance_minor"])
            if row["official_balance_minor"] is not None
            else None
        ),
    )


def _row_to_override(row: sqlite3.Row) -> TaxYearOverride:
    return TaxYearOverride(
        income_year=int(row["income_year"]),
        income_kind=IncomeKind(str(row["income_kind"])),
        gross_minor=int(row["gross_minor"]) if row["gross_minor"] is not None else None,
        withheld_minor=(
            int(row["withheld_minor"]) if row["withheld_minor"] is not None else None
        ),
    )


def _row_to_reminder_mark(row: sqlite3.Row) -> ReminderMarkRecord:
    return ReminderMarkRecord(
        kind=TaxKind(str(row["kind"])),
        cycle_year=int(row["cycle_year"]),
        mark=ReminderMark(str(row["mark"])),
        marked_at=str(row["marked_at"]),
    )
