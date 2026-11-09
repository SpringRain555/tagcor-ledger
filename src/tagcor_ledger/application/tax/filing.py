"""綜所稅申報輸入、扣繳憑單與所得試算 use case。"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from tagcor_ledger.application.failures import STORE_FAILURES, failure
from tagcor_ledger.application.result import Result
from tagcor_ledger.application.tax.base import TaxServiceBase
from tagcor_ledger.domain.tax.estimate import Estimate, estimate_income_tax
from tagcor_ledger.domain.tax.kinds import IncomeKind
from tagcor_ledger.domain.tax.records import TaxYearInputs, TaxYearOverride


class TaxFilingSection(TaxServiceBase):
    def tax_year_inputs(self, income_year: int) -> TaxYearInputs | None:
        return self.store.get_tax_year_inputs(income_year)

    def prefilled_inputs(self, income_year: int) -> TaxYearInputs | None:
        inputs = self.store.get_tax_year_inputs(income_year)
        if inputs is not None:
            return inputs
        previous = self.store.latest_tax_year_inputs_before(income_year)
        if previous is None:
            return None
        return replace(
            previous,
            income_year=income_year,
            official_tax_minor=None,
            official_balance_minor=None,
        )

    def save_tax_year_inputs(self, inputs: TaxYearInputs) -> Result:
        try:
            self.store.save_tax_year_inputs(inputs)
            return Result.ok("申報狀況已儲存。")
        except STORE_FAILURES as exc:
            return failure(
                exc,
                fallback_code="TAX_INPUTS_SAVE_FAILED",
                fallback_message="申報狀況無法儲存。請匯出診斷資訊回報。",
            )

    def tax_year_overrides(self, income_year: int) -> dict[IncomeKind, TaxYearOverride]:
        return self.store.list_tax_year_overrides(income_year)

    def save_tax_year_override(self, override: TaxYearOverride) -> Result:
        try:
            self.store.save_tax_year_override(override)
            return Result.ok("扣繳憑單已儲存。")
        except STORE_FAILURES as exc:
            return failure(
                exc,
                fallback_code="TAX_OVERRIDE_SAVE_FAILED",
                fallback_message="扣繳憑單無法儲存。請匯出診斷資訊回報。",
            )

    def estimate(self, income_year: int) -> Estimate:
        dataset = self._usable_dataset()
        return estimate_income_tax(
            income_year=income_year,
            dataset_available=dataset is not None,
            parameters=dataset.parameters_for(income_year) if dataset is not None else None,
            basic_living=dataset.basic_living_for(income_year) if dataset is not None else None,
            inputs=self.store.get_tax_year_inputs(income_year),
            overrides=self.store.list_tax_year_overrides(income_year),
            ledger=self.store.income_totals(income_year),
        )

    def default_income_year(self, *, today: date | None = None) -> int:
        current = self._today(today)
        dataset = self._usable_dataset()
        if dataset is None:
            return current.year - 1
        complete = tuple(
            year
            for year in dataset.income_tax
            if year <= current.year and dataset.basic_living_for(year) is not None
        )
        return max(complete) if complete else current.year - 1
