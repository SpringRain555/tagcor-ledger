"""依稅務資料集計算提醒週期與狀態。"""

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import Mapping

from tagcor_ledger.domain.tax.dataset import TaxDataset, Window
from tagcor_ledger.domain.tax.kinds import ReminderMark, TaxKind
from tagcor_ledger.domain.tax.records import PaymentFact


LEAD_DAYS = 14
OVERDUE_DAYS = 30


class ReminderSwitch(StrEnum):
    """單一稅目的提醒開關。"""

    ON = "on"
    OFF = "off"
    UNSET = "unset"


def default_switch(kind: TaxKind) -> ReminderSwitch:
    """回傳尚未設定時使用的開關預設值。"""
    if kind is TaxKind.INCOME_TAX:
        return ReminderSwitch.ON
    return ReminderSwitch.UNSET


class ReminderState(StrEnum):
    """某一提醒週期在指定日期的狀態。"""

    DISABLED = "disabled"
    UNSET = "unset"
    NO_WINDOW = "no_window"
    HANDLED = "handled"
    NOT_APPLICABLE = "not_applicable"
    PAID = "paid"
    DORMANT = "dormant"
    UPCOMING = "upcoming"
    OPEN = "open"
    OVERDUE = "overdue"


@dataclass(frozen=True, slots=True)
class ReminderCycle:
    kind: TaxKind
    year: int
    window: Window
    notify_from: date
    overdue_until: date


def _cycle(kind: TaxKind, year: int, window: Window) -> ReminderCycle:
    return ReminderCycle(
        kind=kind,
        year=year,
        window=window,
        notify_from=window.start - timedelta(days=LEAD_DAYS),
        overdue_until=window.end + timedelta(days=OVERDUE_DAYS),
    )


def cycle_for(
    kind: TaxKind, *, today: date, dataset: TaxDataset
) -> ReminderCycle | None:
    """找出目前涵蓋今天的週期，否則回傳最近的未來週期。"""
    candidates = tuple(
        _cycle(kind, year, window)
        for year in range(today.year - 1, today.year + 2)
        if (window := dataset.window_for(kind, year)) is not None
    )
    current = tuple(
        cycle
        for cycle in candidates
        if cycle.notify_from <= today <= cycle.overdue_until
    )
    if current:
        return min(current, key=lambda cycle: cycle.notify_from)
    future = tuple(cycle for cycle in candidates if cycle.notify_from > today)
    if future:
        return min(future, key=lambda cycle: cycle.notify_from)
    return None


def payment_range(cycle: ReminderCycle, *, today: date) -> tuple[date, date] | None:
    """回傳用來判斷本週期已繳款的含首尾日期範圍。"""
    if today < cycle.notify_from:
        return None
    return cycle.notify_from, min(today, cycle.overdue_until)


def reminder_state(
    *,
    today: date,
    switch: ReminderSwitch,
    cycle: ReminderCycle | None,
    mark: ReminderMark | None,
    paid: bool,
) -> ReminderState:
    """依規格的固定優先順序計算提醒狀態。"""
    if switch is ReminderSwitch.OFF:
        return ReminderState.DISABLED
    if switch is ReminderSwitch.UNSET:
        return ReminderState.UNSET
    if cycle is None:
        return ReminderState.NO_WINDOW
    if mark is ReminderMark.HANDLED:
        return ReminderState.HANDLED
    if mark is ReminderMark.NOT_APPLICABLE:
        return ReminderState.NOT_APPLICABLE
    if paid:
        return ReminderState.PAID
    if today < cycle.notify_from:
        return ReminderState.DORMANT
    if today < cycle.window.start:
        return ReminderState.UPCOMING
    if today <= cycle.window.end:
        return ReminderState.OPEN
    return ReminderState.OVERDUE


def days_left(cycle: ReminderCycle, *, today: date) -> int:
    """回傳距離期間截止日的天數。"""
    return (cycle.window.end - today).days


@dataclass(frozen=True, slots=True)
class ReminderView:
    kind: TaxKind
    state: ReminderState
    cycle: ReminderCycle | None
    mark: ReminderMark | None
    last_year_paid: PaymentFact | None


_VISIBLE_STATES = frozenset(
    {ReminderState.UPCOMING, ReminderState.OPEN, ReminderState.OVERDUE}
)
_STATE_ORDER = {
    ReminderState.OVERDUE: 0,
    ReminderState.OPEN: 1,
    ReminderState.UPCOMING: 2,
}
_KIND_ORDER = {kind: index for index, kind in enumerate(TaxKind)}


def _overview_key(view: ReminderView) -> tuple[int, date, int, int]:
    state_order = _STATE_ORDER[view.state]
    if view.cycle is None:
        due_on = date.max
        year = 0
    elif view.state is ReminderState.UPCOMING:
        due_on = view.cycle.window.start
        year = view.cycle.year
    else:
        due_on = view.cycle.window.end
        year = view.cycle.year
    return state_order, due_on, _KIND_ORDER[view.kind], year


def overview_reminders(
    views: tuple[ReminderView, ...], *, limit: int = 3
) -> tuple[tuple[ReminderView, ...], int]:
    """排序總覽提醒，必要時保留最後一列做摺疊數量。"""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit 必須是大於 0 的整數")
    visible = tuple(sorted((view for view in views if view.state in _VISIBLE_STATES), key=_overview_key))
    if len(visible) <= limit:
        return visible, 0
    return visible[: limit - 1], len(visible) - (limit - 1)


def unset_kinds(
    switches: Mapping[TaxKind, ReminderSwitch],
) -> tuple[TaxKind, ...]:
    """列出尚未決定是否提醒的稅目，未提供者採用預設開關。"""
    return tuple(
        kind
        for kind in TaxKind
        if switches.get(kind, default_switch(kind)) is ReminderSwitch.UNSET
    )
