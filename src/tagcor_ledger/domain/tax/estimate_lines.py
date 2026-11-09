"""建立綜所稅估算明細的私有輔助。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping

from tagcor_ledger.domain.tax.dataset import IncomeTaxParameters, SourcedAmount
from tagcor_ledger.domain.tax.kinds import IncomeKind
from tagcor_ledger.domain.tax.records import TaxYearOverride

if TYPE_CHECKING:
    from tagcor_ledger.domain.tax.estimate import (
        EstimateLine,
        EstimateStep,
        LedgerIncome,
        LineSource,
        _IncomeCalculation,
    )


def _income_amounts(
    overrides: Mapping[IncomeKind, TaxYearOverride], ledger: LedgerIncome
) -> tuple[dict[IncomeKind, int], dict[IncomeKind, int], dict[IncomeKind, bool]]:
    gross: dict[IncomeKind, int] = {}
    counts: dict[IncomeKind, int] = {}
    manual: dict[IncomeKind, bool] = {}
    for kind in (
        IncomeKind.SALARY,
        IncomeKind.INTEREST_TAXABLE,
        IncomeKind.PRIZE,
        IncomeKind.WRITING_LECTURE,
    ):
        total = ledger.total(kind)
        override = overrides.get(kind)
        gross_amount = override.gross_minor if override is not None else None
        manual[kind] = gross_amount is not None
        counts[kind] = total.count
        if gross_amount is not None:
            gross[kind] = gross_amount
        elif kind is IncomeKind.INTEREST_TAXABLE:
            gross[kind] = total.net_minor + total.withheld_tax_minor + total.nhi_premium_minor
        else:
            gross[kind] = total.net_minor
    for kind in (
        IncomeKind.FOREIGN_INCOME,
        IncomeKind.INTEREST_EXEMPT,
        IncomeKind.EXEMPT_INCOME,
        IncomeKind.OTHER_INCOME,
        IncomeKind.EXCLUDED,
    ):
        total = ledger.total(kind)
        gross[kind] = total.net_minor
        counts[kind] = total.count
        manual[kind] = False
    return gross, counts, manual


def _amount_sources(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(source_id for group in groups for source_id in group))


def _line(
    step: EstimateStep,
    amount: int,
    source: LineSource | None = None,
    *,
    count: int | None = None,
    source_ids: tuple[str, ...] = (),
    included: bool = True,
) -> EstimateLine:
    from tagcor_ledger.domain.tax.estimate import EstimateLine, LineSource

    return EstimateLine(
        step,
        amount,
        LineSource.COMPUTED if source is None else source,
        count,
        source_ids,
        included,
    )


def _build_estimate_lines(
    *,
    parameters: IncomeTaxParameters,
    basic_living: SourcedAmount,
    amounts: Mapping[IncomeKind, int],
    counts: Mapping[IncomeKind, int],
    manual: Mapping[IncomeKind, bool],
    calculation: _IncomeCalculation,
    tax: int,
    withheld: int,
    balance: int,
) -> tuple[EstimateLine, ...]:
    """依計算結果建立明細行，並保留帳本、手動與公告出處。"""
    from tagcor_ledger.domain.tax.estimate import EstimateStep, LineSource

    lines: list[EstimateLine] = []
    salary_gross = amounts[IncomeKind.SALARY]
    salary_count = counts[IncomeKind.SALARY]
    if salary_count > 0 or manual[IncomeKind.SALARY]:
        salary_source = LineSource.MANUAL if manual[IncomeKind.SALARY] else LineSource.LEDGER
        lines.append(
            _line(
                EstimateStep.SALARY_GROSS,
                salary_gross,
                salary_source,
                count=salary_count if salary_source is LineSource.LEDGER else None,
            )
        )
        lines.append(
            _line(
                EstimateStep.SALARY_DEDUCTION,
                salary_gross - calculation.salary_income,
                source_ids=parameters.salary_special_deduction_cap.source_ids,
            )
        )
        lines.append(_line(EstimateStep.SALARY_INCOME, calculation.salary_income))

    for kind, step in (
        (IncomeKind.INTEREST_TAXABLE, EstimateStep.INTEREST),
        (IncomeKind.PRIZE, EstimateStep.PRIZE),
        (IncomeKind.OTHER_INCOME, EstimateStep.OTHER),
        (IncomeKind.WRITING_LECTURE, EstimateStep.WRITING_LECTURE),
        (IncomeKind.FOREIGN_INCOME, EstimateStep.FOREIGN),
        (IncomeKind.INTEREST_EXEMPT, EstimateStep.INTEREST_EXEMPT),
        (IncomeKind.EXEMPT_INCOME, EstimateStep.EXEMPT_INCOME),
        (IncomeKind.EXCLUDED, EstimateStep.EXCLUDED),
    ):
        count = counts[kind]
        if count == 0 and not manual.get(kind, False):
            continue
        source = LineSource.MANUAL if manual.get(kind, False) else LineSource.LEDGER
        included = step not in {
            EstimateStep.WRITING_LECTURE,
            EstimateStep.FOREIGN,
            EstimateStep.INTEREST_EXEMPT,
            EstimateStep.EXEMPT_INCOME,
            EstimateStep.EXCLUDED,
        }
        lines.append(
            _line(
                step,
                amounts[kind],
                source,
                count=count if source is LineSource.LEDGER else None,
                included=included,
            )
        )

    lines.extend(
        (
            _line(EstimateStep.GROSS_INCOME, calculation.gross_income),
            _line(
                EstimateStep.EXEMPTION,
                calculation.exemption,
                LineSource.DATASET,
                source_ids=_amount_sources(
                    parameters.exemption.source_ids,
                    parameters.exemption_70_plus.source_ids
                    if calculation.elderly_count
                    else (),
                ),
            ),
            _line(
                EstimateStep.STANDARD_DEDUCTION,
                calculation.standard,
                LineSource.DATASET,
                source_ids=parameters.standard_deduction_single.source_ids,
            ),
            _line(
                EstimateStep.SAVINGS_DEDUCTION,
                calculation.savings,
                source_ids=parameters.savings_investment_cap.source_ids,
            ),
            _line(
                EstimateStep.BASIC_LIVING,
                calculation.basic_living,
                source_ids=basic_living.source_ids,
            ),
            _line(EstimateStep.NET_INCOME, calculation.net_income),
            _line(
                EstimateStep.TAX,
                tax,
                source_ids=_amount_sources(
                    parameters.brackets_source_ids,
                    parameters.tax_rounding_source_ids,
                ),
            ),
            _line(EstimateStep.WITHHELD, withheld),
            _line(EstimateStep.BALANCE, balance),
        )
    )
    return tuple(lines)
