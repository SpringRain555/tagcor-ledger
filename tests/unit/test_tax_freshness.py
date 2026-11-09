"""稅務資料載入、新鮮度問題與公告期間涵蓋。"""

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from tagcor_ledger.domain.tax.dataset_parse import parse_tax_dataset
from tagcor_ledger.domain.tax.freshness import (
    BLOCKING_ISSUES,
    DatasetLoad,
    DatasetLoadState,
    FreshnessIssue,
    FreshnessProblem,
    assess_freshness,
    missing_exact_windows,
    required_basic_living_years,
    required_parameter_years,
)
from tagcor_ledger.domain.tax.kinds import TaxKind


FIXTURE = Path(__file__).parents[1] / "fixtures" / "tax" / "sample.json"


@pytest.fixture
def dataset():
    return parse_tax_dataset(json.loads(FIXTURE.read_text(encoding="utf-8")))


def _assess(dataset, today: date, law_reviewed: date | None = None):
    return assess_freshness(
        today=today,
        load=DatasetLoad(DatasetLoadState.OK, dataset),
        law_oldest_reviewed_at=law_reviewed,
    )


def test_blocking_load_states_return_one_problem_and_stop(dataset) -> None:
    missing = assess_freshness(
        today=date(2026, 11, 9),
        load=DatasetLoad(DatasetLoadState.MISSING),
        law_oldest_reviewed_at=date(2020, 1, 1),
    )
    invalid = assess_freshness(
        today=date(2026, 11, 9),
        load=DatasetLoad(DatasetLoadState.INVALID, problems=("格式錯誤", "來源不符")),
        law_oldest_reviewed_at=date(2020, 1, 1),
    )
    unpopulated = _assess(replace(dataset, reviewed_at=None), date(2026, 11, 9))

    assert tuple(problem.issue for problem in missing) == (FreshnessIssue.DATASET_MISSING,)
    assert tuple(problem.issue for problem in invalid) == (FreshnessIssue.DATASET_INVALID,)
    assert invalid[0].details == ("格式錯誤", "來源不符")
    assert tuple(problem.issue for problem in unpopulated) == (FreshnessIssue.NOT_POPULATED,)
    assert BLOCKING_ISSUES == (
        FreshnessIssue.DATASET_MISSING,
        FreshnessIssue.DATASET_INVALID,
        FreshnessIssue.NOT_POPULATED,
    )


@pytest.mark.parametrize(
    ("state", "dataset_present", "problems"),
    [
        (DatasetLoadState.OK, False, ()),
        (DatasetLoadState.MISSING, True, ()),
        (DatasetLoadState.INVALID, False, ()),
        (DatasetLoadState.MISSING, False, ("unexpected",)),
    ],
)
def test_dataset_load_rejects_each_inconsistent_shape(
    dataset, state: DatasetLoadState, dataset_present: bool, problems: tuple[str, ...]
) -> None:
    with pytest.raises(ValueError):
        DatasetLoad(state, dataset if dataset_present else None, problems)


def test_parameter_years_change_on_december_15() -> None:
    assert required_parameter_years(date(2026, 12, 14)) == (2025, 2026)
    assert required_parameter_years(date(2026, 12, 15)) == (2025, 2026, 2027)


def test_basic_living_years_change_on_december_15() -> None:
    assert required_basic_living_years(date(2026, 11, 9)) == (2025,)
    assert required_basic_living_years(date(2026, 12, 14)) == (2025,)
    assert required_basic_living_years(date(2026, 12, 15)) == (2025, 2026)


def test_parameter_gaps_match_required_years_and_are_sorted(dataset) -> None:
    assert _assess(dataset, date(2026, 11, 9)) == ()
    due = _assess(dataset, date(2026, 12, 15))
    assert due == (
        FreshnessProblem(FreshnessIssue.PARAMETERS_MISSING, years=(2027,)),
    )
    january = _assess(dataset, date(2027, 1, 5))
    assert FreshnessProblem(FreshnessIssue.PARAMETERS_MISSING, years=(2027,)) in january


def test_basic_living_gap_starts_on_december_15(dataset) -> None:
    remaining = {
        year: amount
        for year, amount in dataset.basic_living_expense.items()
        if year != 2026
    }
    changed = replace(dataset, basic_living_expense=remaining)

    assert _assess(changed, date(2026, 11, 9)) == ()
    december = next(
        problem
        for problem in _assess(changed, date(2026, 12, 15))
        if problem.issue is FreshnessIssue.PARAMETERS_MISSING
    )
    assert december.years == (2026, 2027)


def test_missing_prior_year_basic_living_is_reported(dataset) -> None:
    changed = replace(
        dataset,
        basic_living_expense={
            year: amount
            for year, amount in dataset.basic_living_expense.items()
            if year != 2025
        },
    )

    due = _assess(changed, date(2026, 11, 9))

    assert due == (
        FreshnessProblem(FreshnessIssue.PARAMETERS_MISSING, years=(2025,)),
    )


def test_missing_income_and_basic_living_same_year_is_listed_once(dataset) -> None:
    changed = replace(
        dataset,
        income_tax={
            year: parameters
            for year, parameters in dataset.income_tax.items()
            if year != 2025
        },
        basic_living_expense={
            year: amount
            for year, amount in dataset.basic_living_expense.items()
            if year != 2025
        },
    )

    due = _assess(changed, date(2026, 11, 9))

    assert due == (
        FreshnessProblem(FreshnessIssue.PARAMETERS_MISSING, years=(2025,)),
    )


def test_parameter_gap_precedes_review_due(dataset) -> None:
    changed = replace(dataset, next_review_on=date(2026, 12, 1))

    problems = _assess(changed, date(2026, 12, 15))

    assert tuple(problem.issue for problem in problems) == (
        FreshnessIssue.PARAMETERS_MISSING,
        FreshnessIssue.REVIEW_DUE,
    )


def test_review_due_includes_the_due_date(dataset) -> None:
    assert not any(
        problem.issue is FreshnessIssue.REVIEW_DUE
        for problem in _assess(dataset, date(2026, 12, 31))
    )
    due = _assess(dataset, date(2027, 1, 1))
    review = next(problem for problem in due if problem.issue is FreshnessIssue.REVIEW_DUE)
    assert review.due_on == date(2027, 1, 1)


@pytest.mark.parametrize(
    ("today", "oldest", "expected"),
    [
        (date(2026, 3, 31), date(2025, 5, 20), False),
        (date(2026, 4, 1), date(2025, 5, 20), True),
        (date(2026, 6, 1), date(2025, 5, 20), True),
        (date(2026, 6, 2), date(2025, 5, 20), False),
        (date(2026, 4, 1), date(2026, 1, 1), False),
        (date(2026, 4, 1), None, False),
    ],
)
def test_law_review_due_uses_the_income_tax_window(
    dataset, today: date, oldest: date | None, expected: bool
) -> None:
    problems = _assess(dataset, today, oldest)

    assert any(problem.issue is FreshnessIssue.LAW_REVIEW_DUE for problem in problems) is expected


def test_missing_exact_windows_uses_year_then_input_kind_order(dataset) -> None:
    kinds = (
        TaxKind.INCOME_TAX,
        TaxKind.HOUSE_TAX,
        TaxKind.VEHICLE_LICENSE_TAX,
        TaxKind.FUEL_FEE,
    )

    assert missing_exact_windows(dataset, today=date(2026, 11, 9), kinds=kinds) == (
        (TaxKind.VEHICLE_LICENSE_TAX, 2026),
        (TaxKind.INCOME_TAX, 2027),
        (TaxKind.HOUSE_TAX, 2027),
        (TaxKind.VEHICLE_LICENSE_TAX, 2027),
        (TaxKind.FUEL_FEE, 2027),
    )
