"""稅務頁與資產總覽使用的稅務 controller 委派。"""

from __future__ import annotations

from dataclasses import dataclass

from tagcor_ledger.application.result import Result
from tagcor_ledger.application.tax.data import TaxDataStatus
from tagcor_ledger.domain.tax.estimate import Estimate
from tagcor_ledger.domain.tax.freshness import BLOCKING_ISSUES, FreshnessProblem
from tagcor_ledger.domain.tax.kinds import Flow, IncomeKind, ReminderMark, TaxKind
from tagcor_ledger.domain.tax.records import TaxMappingRow, TaxYearInputs, TaxYearOverride
from tagcor_ledger.domain.tax.reminders import (
    ReminderSwitch,
    ReminderView,
    overview_reminders,
    unset_kinds,
)
from tagcor_ledger.ui.controller.wiring import ControllerBase


@dataclass(frozen=True, slots=True)
class TaxOverview:
    reminders: tuple[ReminderView, ...]
    folded: int
    problem: FreshnessProblem | None
    unset_count: int
    income_tax_estimate: Estimate | None


class TaxSection(ControllerBase):
    """稅務 controller 薄層；不呼叫其他 controller section。"""

    def tax_reminder_views(self) -> tuple[ReminderView, ...]:
        return self.tax.reminder_views(today=self.today_provider())

    def tax_reminder_switches(self) -> dict[TaxKind, ReminderSwitch]:
        return self.tax.reminder_switches()

    def save_tax_reminder_switch(
        self, kind: TaxKind, switch: ReminderSwitch
    ) -> Result:
        return self.tax.save_reminder_switch(kind, switch)

    def mark_tax_reminder(
        self, kind: TaxKind, cycle_year: int, mark: ReminderMark | None
    ) -> Result:
        return self.tax.set_reminder_mark(kind, cycle_year, mark)

    def tax_data_status(self) -> TaxDataStatus:
        return self.tax.data_status(today=self.today_provider())

    def tax_default_income_year(self) -> int:
        return self.tax.default_income_year(today=self.today_provider())

    def tax_estimate(self, income_year: int) -> Estimate:
        return self.tax.estimate(income_year)

    def tax_year_inputs(self, income_year: int) -> TaxYearInputs | None:
        return self.tax.tax_year_inputs(income_year)

    def tax_prefilled_inputs(self, income_year: int) -> TaxYearInputs | None:
        return self.tax.prefilled_inputs(income_year)

    def save_tax_year_inputs(self, inputs: TaxYearInputs) -> Result:
        return self.tax.save_tax_year_inputs(inputs)

    def tax_year_overrides(self, income_year: int) -> dict[IncomeKind, TaxYearOverride]:
        return self.tax.tax_year_overrides(income_year)

    def save_tax_year_override(self, override: TaxYearOverride) -> Result:
        return self.tax.save_tax_year_override(override)

    def tax_mapping_rows(self, income_year: int) -> list[TaxMappingRow]:
        return self.tax.mapping_rows(income_year)

    def set_tax_mapping(
        self,
        *,
        category_id: str,
        flow: Flow,
        tax_kind: str | None,
    ) -> Result:
        return self.tax.set_mapping(
            category_id=category_id,
            flow=flow,
            tax_kind=tax_kind,
        )

    def tax_overview(self) -> TaxOverview:
        status = self.tax_data_status()
        problem = status.problems[0] if status.problems else None
        if problem is not None and problem.issue in BLOCKING_ISSUES:
            return TaxOverview((), 0, problem, 0, None)

        views = self.tax_reminder_views()
        reminders, folded = overview_reminders(views, limit=3)
        switches = self.tax_reminder_switches()
        unset_count = len(unset_kinds(switches))
        income_reminder = next(
            (view for view in reminders if view.kind is TaxKind.INCOME_TAX),
            None,
        )
        estimate = (
            self.tax_estimate(income_reminder.cycle.year - 1)
            if income_reminder is not None and income_reminder.cycle is not None
            else None
        )
        return TaxOverview(
            reminders=reminders,
            folded=folded,
            problem=problem,
            unset_count=unset_count,
            income_tax_estimate=estimate,
        )
