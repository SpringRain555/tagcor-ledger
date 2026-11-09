"""稅務申報輸入、扣繳憑單覆寫與提醒標記。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.domain.tax.kinds import (
    DeductionChoice,
    FilingStatus,
    IncomeKind,
    ReminderMark,
    TaxKind,
)
from tagcor_ledger.domain.tax.records import TaxYearInputs, TaxYearOverride
from tagcor_ledger.infrastructure.database import connect_database
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


@pytest.fixture
def store(tmp_path: Path) -> LedgerStore:
    return LedgerStore(resolve_app_paths(tmp_path / "data"))


def _inputs(income_year: int, **changes: int | None) -> TaxYearInputs:
    values: dict[str, int | None] = {
        "dependents": 1,
        "dependents_70_plus": 0,
        "official_tax_minor": 1234,
        "official_balance_minor": -50,
    }
    values.update(changes)
    return TaxYearInputs(
        income_year=income_year,
        filing=FilingStatus.SINGLE,
        deduction=DeductionChoice.STANDARD,
        other_special_deductions=False,
        dependents_have_income=False,
        filer_70_plus=False,
        dependents=int(values["dependents"]),
        dependents_70_plus=int(values["dependents_70_plus"]),
        official_tax_minor=values["official_tax_minor"],
        official_balance_minor=values["official_balance_minor"],
    )


def test_tax_year_inputs_round_trip_and_latest_prior_year(store: LedgerStore) -> None:
    prior = _inputs(2024)
    latest = _inputs(2025, dependents=2)
    store.save_tax_year_inputs(prior)
    store.save_tax_year_inputs(latest)

    assert store.get_tax_year_inputs(2025) == latest
    assert store.get_tax_year_inputs(2026) is None
    assert store.latest_tax_year_inputs_before(2026) == latest
    assert store.latest_tax_year_inputs_before(2025) == prior
    assert store.latest_tax_year_inputs_before(2024) is None


@pytest.mark.parametrize(
    "inputs",
    (
        _inputs(2026, dependents=-1),
        _inputs(2026, dependents_70_plus=-1),
        _inputs(2026, dependents=1, dependents_70_plus=2),
        _inputs(2026, official_tax_minor=-1),
    ),
    ids=("negative-dependents", "negative-elderly", "too-many-elderly", "negative-official-tax"),
)
def test_invalid_tax_year_inputs_fail_before_write(
    store: LedgerStore, inputs: TaxYearInputs
) -> None:
    with pytest.raises(ValueError, match="TAX_INPUTS_INVALID"):
        store.save_tax_year_inputs(inputs)
    assert store.get_tax_year_inputs(inputs.income_year) is None


def test_tax_year_input_audit_lists_changed_fields_without_values(
    store: LedgerStore,
) -> None:
    store.save_tax_year_inputs(_inputs(2025))
    store.save_tax_year_inputs(_inputs(2025, dependents=2, official_tax_minor=8888))
    with connect_database(store.paths.database_path) as connection:
        audits = connection.execute(
            """
            SELECT action, entity_type, entity_id, details_json
            FROM audit_events WHERE action = 'tax_year_inputs.save'
            ORDER BY rowid
            """
        ).fetchall()
    assert len(audits) == 2
    assert str(audits[0]["entity_type"]) == "tax_year"
    assert str(audits[0]["entity_id"]) == "2025"
    first_fields = json.loads(str(audits[0]["details_json"]))["fields"]
    assert first_fields == sorted(
        (
            "deduction",
            "dependents",
            "dependents_70_plus",
            "dependents_have_income",
            "filing",
            "filer_70_plus",
            "official_balance_minor",
            "official_tax_minor",
            "other_special_deductions",
        )
    )
    changed = json.loads(str(audits[1]["details_json"]))["fields"]
    assert changed == ["dependents", "official_tax_minor"]
    assert "8888" not in str(audits[1]["details_json"])


def test_tax_year_overrides_save_update_clear_and_validate(store: LedgerStore) -> None:
    first = TaxYearOverride(2025, IncomeKind.SALARY, 50_000, 6_000)
    store.save_tax_year_override(first)
    assert store.list_tax_year_overrides(2025) == {IncomeKind.SALARY: first}

    updated = TaxYearOverride(2025, IncomeKind.SALARY, 55_000, 6_500)
    store.save_tax_year_override(updated)
    assert store.list_tax_year_overrides(2025)[IncomeKind.SALARY] == updated
    store.save_tax_year_override(TaxYearOverride(2025, IncomeKind.SALARY, None, None))
    assert store.list_tax_year_overrides(2025) == {}

    with pytest.raises(ValueError, match="TAX_OVERRIDE_KIND_INVALID"):
        store.save_tax_year_override(TaxYearOverride(2025, IncomeKind.OTHER_INCOME, 1, None))
    with pytest.raises(ValueError, match="TAX_OVERRIDE_AMOUNT_INVALID"):
        store.save_tax_year_override(TaxYearOverride(2025, IncomeKind.PRIZE, -1, None))
    with pytest.raises(ValueError, match="TAX_OVERRIDE_AMOUNT_INVALID"):
        store.save_tax_year_override(TaxYearOverride(2025, IncomeKind.PRIZE, None, -1))
    assert store.list_tax_year_overrides(2025) == {}


def test_tax_override_audit_contains_only_changed_field_names(store: LedgerStore) -> None:
    store.save_tax_year_override(TaxYearOverride(2025, IncomeKind.PRIZE, 20_000, 1_000))
    store.save_tax_year_override(TaxYearOverride(2025, IncomeKind.PRIZE, 25_000, 1_000))
    store.save_tax_year_override(TaxYearOverride(2025, IncomeKind.PRIZE, None, None))
    with connect_database(store.paths.database_path) as connection:
        audits = connection.execute(
            """
            SELECT action, entity_type, entity_id, details_json
            FROM audit_events WHERE action IN ('tax_override.save', 'tax_override.clear')
            ORDER BY rowid
            """
        ).fetchall()
    assert [str(row["action"]) for row in audits] == [
        "tax_override.save",
        "tax_override.save",
        "tax_override.clear",
    ]
    assert str(audits[0]["entity_type"]) == "tax_year"
    assert str(audits[0]["entity_id"]) == "2025:prize"
    assert json.loads(str(audits[0]["details_json"])) == {
        "fields": ["gross_minor", "withheld_minor"]
    }
    assert json.loads(str(audits[1]["details_json"])) == {"fields": ["gross_minor"]}
    assert "25000" not in str(audits[1]["details_json"])


def test_reminder_marks_are_year_scoped_and_can_be_cleared(store: LedgerStore) -> None:
    store.set_reminder_mark(
        kind=TaxKind.HOUSE_TAX,
        cycle_year=2026,
        mark=ReminderMark.HANDLED,
    )
    store.set_reminder_mark(
        kind=TaxKind.HOUSE_TAX,
        cycle_year=2027,
        mark=ReminderMark.NOT_APPLICABLE,
    )
    marks = store.list_reminder_marks(cycle_years=(2026,))
    assert list(marks) == [(TaxKind.HOUSE_TAX, 2026)]
    assert marks[(TaxKind.HOUSE_TAX, 2026)].mark is ReminderMark.HANDLED
    assert marks[(TaxKind.HOUSE_TAX, 2026)].marked_at

    store.set_reminder_mark(kind=TaxKind.HOUSE_TAX, cycle_year=2026, mark=None)
    remaining = store.list_reminder_marks(cycle_years=(2026, 2027))
    assert (TaxKind.HOUSE_TAX, 2026) not in remaining
    assert remaining[(TaxKind.HOUSE_TAX, 2027)].mark is ReminderMark.NOT_APPLICABLE
    assert store.list_reminder_marks(cycle_years=()) == {}
