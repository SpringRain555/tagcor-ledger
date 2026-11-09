"""稅務提醒的週期、優先順序與總覽排序。"""

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from tagcor_ledger.domain.tax.dataset_parse import parse_tax_dataset
from tagcor_ledger.domain.tax.kinds import ReminderMark, TaxKind
from tagcor_ledger.domain.tax.records import PaymentFact
from tagcor_ledger.domain.tax.reminders import (
    LEAD_DAYS,
    OVERDUE_DAYS,
    ReminderCycle,
    ReminderState,
    ReminderSwitch,
    ReminderView,
    cycle_for,
    days_left,
    default_switch,
    overview_reminders,
    payment_range,
    reminder_state,
    unset_kinds,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "tax" / "sample.json"


@pytest.fixture
def dataset():
    import json

    return parse_tax_dataset(json.loads(FIXTURE.read_text(encoding="utf-8")))


def _cycle(dataset, kind: TaxKind, year: int) -> ReminderCycle:
    window = dataset.window_for(kind, year)
    assert window is not None
    return ReminderCycle(
        kind,
        year,
        window,
        window.start - timedelta(days=LEAD_DAYS),
        window.end + timedelta(days=OVERDUE_DAYS),
    )


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 3, 17), ReminderState.DORMANT),
        (date(2026, 3, 18), ReminderState.UPCOMING),
        (date(2026, 4, 1), ReminderState.OPEN),
        (date(2026, 4, 30), ReminderState.OPEN),
        (date(2026, 5, 1), ReminderState.OVERDUE),
        (date(2026, 5, 30), ReminderState.OVERDUE),
        (date(2026, 5, 31), ReminderState.DORMANT),
    ],
)
def test_license_tax_reminder_calendar(dataset, today: date, expected: ReminderState) -> None:
    cycle = cycle_for(TaxKind.VEHICLE_LICENSE_TAX, today=today, dataset=dataset)

    assert cycle is not None
    assert reminder_state(
        today=today,
        switch=ReminderSwitch.ON,
        cycle=cycle,
        mark=None,
        paid=False,
    ) is expected


def test_cycle_uses_published_window_and_reports_days_left(dataset) -> None:
    cycle = cycle_for(TaxKind.INCOME_TAX, today=date(2026, 5, 1), dataset=dataset)

    assert cycle is not None
    assert not cycle.window.estimated
    assert cycle.window.end == date(2026, 6, 1)
    assert days_left(cycle, today=date(2026, 5, 3)) == 29
    assert days_left(cycle, today=date(2026, 6, 1)) == 0
    assert days_left(cycle, today=date(2026, 6, 2)) == -1


def test_switches_and_missing_windows_have_priority(dataset) -> None:
    cycle = cycle_for(TaxKind.VEHICLE_LICENSE_TAX, today=date(2026, 4, 1), dataset=dataset)
    assert cycle is not None
    assert default_switch(TaxKind.INCOME_TAX) is ReminderSwitch.ON
    assert default_switch(TaxKind.HOUSE_TAX) is ReminderSwitch.UNSET
    assert reminder_state(
        today=date(2026, 4, 1), switch=ReminderSwitch.OFF, cycle=cycle, mark=None, paid=False
    ) is ReminderState.DISABLED
    assert reminder_state(
        today=date(2026, 4, 1), switch=ReminderSwitch.UNSET, cycle=cycle, mark=None, paid=False
    ) is ReminderState.UNSET
    assert reminder_state(
        today=date(2026, 4, 1), switch=ReminderSwitch.ON, cycle=None, mark=None, paid=False
    ) is ReminderState.NO_WINDOW


def test_mark_and_payment_priority_is_limited_to_the_selected_cycle(dataset) -> None:
    today = date(2026, 4, 1)
    cycle = cycle_for(TaxKind.VEHICLE_LICENSE_TAX, today=today, dataset=dataset)
    assert cycle is not None and cycle.year == 2026
    assert reminder_state(
        today=today,
        switch=ReminderSwitch.ON,
        cycle=cycle,
        mark=ReminderMark.NOT_APPLICABLE,
        paid=True,
    ) is ReminderState.NOT_APPLICABLE
    assert reminder_state(
        today=today,
        switch=ReminderSwitch.ON,
        cycle=cycle,
        mark=ReminderMark.HANDLED,
        paid=True,
    ) is ReminderState.HANDLED
    assert reminder_state(
        today=today,
        switch=ReminderSwitch.ON,
        cycle=cycle,
        mark=None,
        paid=True,
    ) is ReminderState.PAID

    next_cycle = cycle_for(
        TaxKind.VEHICLE_LICENSE_TAX, today=date(2027, 3, 18), dataset=dataset
    )
    assert next_cycle is not None and next_cycle.year == 2027
    assert reminder_state(
        today=date(2027, 3, 18),
        switch=ReminderSwitch.ON,
        cycle=next_cycle,
        mark=None,
        paid=False,
    ) is ReminderState.UPCOMING


def test_payment_range_is_clipped_to_cycle_bounds(dataset) -> None:
    cycle = cycle_for(TaxKind.VEHICLE_LICENSE_TAX, today=date(2026, 3, 17), dataset=dataset)
    assert cycle is not None
    assert payment_range(cycle, today=date(2026, 3, 17)) is None
    assert payment_range(cycle, today=date(2026, 4, 1)) == (
        date(2026, 3, 18),
        date(2026, 4, 1),
    )
    assert payment_range(cycle, today=date(2026, 6, 1)) == (
        date(2026, 3, 18),
        date(2026, 5, 30),
    )


def test_cycle_can_start_in_the_previous_calendar_year(dataset) -> None:
    kind = TaxKind.VEHICLE_LICENSE_TAX
    typical = dict(dataset.typical)
    typical[kind] = replace(
        typical[kind], start_month=1, start_day=5, end_month=1, end_day=31
    )
    adjusted = replace(dataset, typical=typical)

    before = cycle_for(kind, today=date(2026, 12, 21), dataset=adjusted)
    active = cycle_for(kind, today=date(2026, 12, 22), dataset=adjusted)

    assert before is not None and before.year == 2027
    assert reminder_state(
        today=date(2026, 12, 21),
        switch=ReminderSwitch.ON,
        cycle=before,
        mark=None,
        paid=False,
    ) is ReminderState.DORMANT
    assert active is not None and active.year == 2027
    assert reminder_state(
        today=date(2026, 12, 22),
        switch=ReminderSwitch.ON,
        cycle=active,
        mark=None,
        paid=False,
    ) is ReminderState.UPCOMING


def _view(
    kind: TaxKind,
    state: ReminderState,
    cycle: ReminderCycle | None,
) -> ReminderView:
    return ReminderView(kind, state, cycle, None, PaymentFact(0, 0, None))


def test_overview_sorts_by_state_then_deadline_and_folds_after_limit(dataset) -> None:
    overdue_late = _cycle(dataset, TaxKind.LAND_VALUE_TAX, 2026)
    overdue_early = _cycle(dataset, TaxKind.VEHICLE_LICENSE_TAX, 2026)
    open_cycle = _cycle(dataset, TaxKind.HOUSE_TAX, 2026)
    upcoming_cycle = _cycle(dataset, TaxKind.FUEL_FEE, 2026)
    views = (
        _view(TaxKind.FUEL_FEE, ReminderState.UPCOMING, upcoming_cycle),
        _view(TaxKind.HOUSE_TAX, ReminderState.OPEN, open_cycle),
        _view(TaxKind.LAND_VALUE_TAX, ReminderState.OVERDUE, overdue_late),
        _view(TaxKind.VEHICLE_LICENSE_TAX, ReminderState.OVERDUE, overdue_early),
        _view(TaxKind.INCOME_TAX, ReminderState.PAID, None),
        _view(TaxKind.INCOME_TAX, ReminderState.DORMANT, None),
    )

    ordered, folded = overview_reminders(views, limit=5)
    assert tuple(view.kind for view in ordered) == (
        TaxKind.VEHICLE_LICENSE_TAX,
        TaxKind.LAND_VALUE_TAX,
        TaxKind.HOUSE_TAX,
        TaxKind.FUEL_FEE,
    )
    assert folded == 0
    three_views, folded = overview_reminders(views[:3], limit=3)
    assert tuple(view.kind for view in three_views) == (
        TaxKind.LAND_VALUE_TAX,
        TaxKind.HOUSE_TAX,
        TaxKind.FUEL_FEE,
    )
    assert folded == 0
    three, folded = overview_reminders(views, limit=3)
    assert tuple(view.kind for view in three) == (
        TaxKind.VEHICLE_LICENSE_TAX,
        TaxKind.LAND_VALUE_TAX,
    )
    assert folded == 2


def test_unset_kinds_use_default_for_kinds_not_in_mapping() -> None:
    assert unset_kinds({}) == (
        TaxKind.HOUSE_TAX,
        TaxKind.LAND_VALUE_TAX,
        TaxKind.VEHICLE_LICENSE_TAX,
        TaxKind.FUEL_FEE,
    )
    assert unset_kinds(
        {TaxKind.HOUSE_TAX: ReminderSwitch.OFF, TaxKind.VEHICLE_LICENSE_TAX: ReminderSwitch.ON}
    ) == (TaxKind.LAND_VALUE_TAX, TaxKind.FUEL_FEE)


@pytest.mark.parametrize("limit", [0, -1, True])
def test_overview_requires_a_positive_integer_limit(dataset, limit: int) -> None:
    with pytest.raises(ValueError):
        overview_reminders((), limit=limit)
