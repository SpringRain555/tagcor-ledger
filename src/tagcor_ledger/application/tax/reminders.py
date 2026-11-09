"""依公開資料集、設定與帳本事實組成提醒狀態。"""

from __future__ import annotations

from datetime import date, timedelta

from tagcor_ledger.application.failures import STORE_FAILURES, failure
from tagcor_ledger.application.result import Result
from tagcor_ledger.application.tax.base import TaxServiceBase
from tagcor_ledger.domain.tax.kinds import ReminderMark, TaxKind
from tagcor_ledger.domain.tax.records import PaymentFact
from tagcor_ledger.domain.tax.reminders import (
    LEAD_DAYS,
    OVERDUE_DAYS,
    ReminderSwitch,
    ReminderView,
    cycle_for,
    default_switch,
    payment_range,
    reminder_state,
)


class TaxReminderSection(TaxServiceBase):
    def reminder_switches(self) -> dict[TaxKind, ReminderSwitch]:
        return self.settings.get_tax_reminder_switches()

    def save_reminder_switch(self, kind: TaxKind, switch: ReminderSwitch) -> Result:
        return self.settings.save_tax_reminder_switch(kind, switch)

    def reminder_views(self, *, today: date | None = None) -> tuple[ReminderView, ...]:
        current = self._today(today)
        dataset = self._usable_dataset()
        if dataset is None:
            return ()

        switches = self.reminder_switches()
        years = (current.year - 1, current.year, current.year + 1)
        marks = self.store.list_reminder_marks(cycle_years=years)
        views: list[ReminderView] = []
        for kind in TaxKind:
            cycle = cycle_for(kind, today=current, dataset=dataset)
            mark = marks.get((kind, cycle.year)) if cycle is not None else None
            mark_value = mark.mark if mark is not None else None
            payment = (
                payment_range(cycle, today=current)
                if cycle is not None
                else None
            )
            paid = False
            if payment is not None:
                paid = self.store.payment_fact(kind, start=payment[0], end=payment[1]).count > 0
            state = reminder_state(
                today=current,
                switch=switches.get(kind, default_switch(kind)),
                cycle=cycle,
                mark=mark_value,
                paid=paid,
            )
            last_year_paid: PaymentFact | None = None
            if cycle is not None:
                last_window = dataset.window_for(kind, cycle.year - 1)
                if last_window is not None:
                    prior = self.store.payment_fact(
                        kind,
                        start=last_window.start - timedelta(days=LEAD_DAYS),
                        end=last_window.end + timedelta(days=OVERDUE_DAYS),
                    )
                    if prior.count > 0:
                        last_year_paid = prior
            views.append(
                ReminderView(
                    kind=kind,
                    state=state,
                    cycle=cycle,
                    mark=mark_value,
                    last_year_paid=last_year_paid,
                )
            )
        return tuple(views)

    def set_reminder_mark(
        self, kind: TaxKind, cycle_year: int, mark: ReminderMark | None
    ) -> Result:
        try:
            self.store.set_reminder_mark(kind=kind, cycle_year=cycle_year, mark=mark)
            message = "已標記。" if mark is not None else "已取消標記。"
            return Result.ok(message)
        except STORE_FAILURES as exc:
            return failure(
                exc,
                fallback_code="TAX_REMINDER_SAVE_FAILED",
                fallback_message="提醒設定無法儲存。請匯出診斷資訊回報。",
            )
