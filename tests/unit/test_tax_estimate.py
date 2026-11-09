"""綜所稅試算的整數黃金案例、拒算邊界與輸入檢查。"""

from dataclasses import replace

import pytest

from tagcor_ledger.domain.tax.arithmetic import Rounding
from tagcor_ledger.domain.tax.dataset import (
    Bracket,
    IncomeTaxParameters,
    SourcedAmount,
)
from tagcor_ledger.domain.tax.estimate import (
    ESTIMATE_CAUTION_NAMES,
    ESTIMATE_STEP_NAMES,
    FIXABLE_REASONS,
    EstimateCaution,
    EstimateStep,
    LedgerIncome,
    LineSource,
    UnsupportedReason,
    estimate_income_tax,
    progressive_tax,
)
from tagcor_ledger.domain.tax.kinds import (
    DeductionChoice,
    FilingStatus,
    IncomeKind,
)
from tagcor_ledger.domain.tax.records import KindTotal, TaxYearInputs, TaxYearOverride


SOURCE_IDS = ("test-params",)


def _amount(value: int) -> SourcedAmount:
    return SourcedAmount(value, SOURCE_IDS)


def _parameters(**changes: object) -> IncomeTaxParameters:
    # 數字是任意的測試值，不是任何年度的公告值（例：
    # 基本生活費 210,000 不是 114 年度的 213,000）。
    parameters = IncomeTaxParameters(
        income_year=2025,
        exemption=_amount(97_000),
        exemption_70_plus=_amount(145_500),
        standard_deduction_single=_amount(131_000),
        salary_special_deduction_cap=_amount(218_000),
        savings_investment_cap=_amount(270_000),
        writing_lecture_exemption_cap=_amount(180_000),
        foreign_income_amt_threshold=_amount(1_000_000),
        amt_basic_exemption=_amount(7_500_000),
        brackets=(
            Bracket(590_000, 50_000, 0),
            Bracket(1_330_000, 120_000, 41_300),
            Bracket(2_660_000, 200_000, 147_700),
            Bracket(4_980_000, 300_000, 413_700),
            Bracket(None, 400_000, 911_700),
        ),
        brackets_source_ids=SOURCE_IDS,
        tax_rounding=Rounding.HALF_UP,
        tax_rounding_source_ids=SOURCE_IDS,
    )
    return replace(parameters, **changes)


def _inputs(**changes: object) -> TaxYearInputs:
    inputs = TaxYearInputs(
        income_year=2025,
        filing=FilingStatus.SINGLE,
        deduction=DeductionChoice.STANDARD,
        other_special_deductions=False,
        dependents_have_income=False,
        filer_70_plus=False,
        dependents=0,
        dependents_70_plus=0,
        official_tax_minor=None,
        official_balance_minor=None,
    )
    return replace(inputs, **changes)


def _total(
    count: int,
    net: int,
    withheld: int = 0,
    premium: int = 0,
) -> KindTotal:
    return KindTotal(count, net, withheld, premium)


def _ledger(
    by_kind: dict[IncomeKind, KindTotal] | None = None,
    unmapped: KindTotal | None = None,
) -> LedgerIncome:
    return LedgerIncome(by_kind or {}, unmapped or _total(0, 0))


def _override(
    kind: IncomeKind,
    gross: int | None,
    withheld: int | None = None,
) -> TaxYearOverride:
    return TaxYearOverride(2025, kind, gross, withheld)


def _line_map(estimate):
    return {line.step: line for line in estimate.lines}


def _estimate(
    *,
    parameters: IncomeTaxParameters | None = None,
    basic_living: SourcedAmount | None = _amount(210_000),
    inputs: TaxYearInputs | None = None,
    overrides: dict[IncomeKind, TaxYearOverride] | None = None,
    ledger: LedgerIncome | None = None,
    dataset_available: bool = True,
):
    return estimate_income_tax(
        income_year=2025,
        dataset_available=dataset_available,
        parameters=_parameters() if parameters is None else parameters,
        basic_living=basic_living,
        inputs=_inputs() if inputs is None else inputs,
        overrides=overrides or {},
        ledger=ledger or _ledger(),
    )


def test_golden_case_salary_override_and_ledger_interest() -> None:
    result = _estimate(
        overrides={IncomeKind.SALARY: _override(IncomeKind.SALARY, 800_000, 12_000)},
        ledger=_ledger(
            {
                IncomeKind.SALARY: _total(12, 760_000),
                IncomeKind.INTEREST_TAXABLE: _total(2, 26_367, 3_000, 633),
            }
        ),
    )
    lines = _line_map(result)

    assert result.refused == ()
    assert lines[EstimateStep.SALARY_GROSS].amount_minor == 800_000
    assert lines[EstimateStep.SALARY_GROSS].source is LineSource.MANUAL
    assert lines[EstimateStep.SALARY_DEDUCTION].amount_minor == 218_000
    assert lines[EstimateStep.SALARY_INCOME].amount_minor == 582_000
    assert lines[EstimateStep.INTEREST].amount_minor == 30_000
    assert lines[EstimateStep.INTEREST].ledger_count == 2
    assert lines[EstimateStep.GROSS_INCOME].amount_minor == 612_000
    assert lines[EstimateStep.EXEMPTION].amount_minor == 97_000
    assert lines[EstimateStep.STANDARD_DEDUCTION].amount_minor == 131_000
    assert lines[EstimateStep.SAVINGS_DEDUCTION].amount_minor == 30_000
    assert lines[EstimateStep.BASIC_LIVING].amount_minor == 0
    assert lines[EstimateStep.NET_INCOME].amount_minor == 354_000
    assert result.tax_minor == 17_700
    assert result.withheld_minor == 15_000
    assert result.balance_minor == 2_700
    assert result.filing_exempt is False
    assert result.cautions == ()
    assert lines[EstimateStep.SALARY_DEDUCTION].source_ids == SOURCE_IDS
    assert lines[EstimateStep.TAX].source_ids == SOURCE_IDS


def test_golden_case_dependents_and_seventy_plus_exemption() -> None:
    result = _estimate(
        inputs=_inputs(dependents=2, dependents_70_plus=1),
        ledger=_ledger({IncomeKind.SALARY: _total(12, 400_000)}),
    )
    lines = _line_map(result)

    assert lines[EstimateStep.EXEMPTION].amount_minor == 339_500
    assert lines[EstimateStep.EXEMPTION].source_ids == SOURCE_IDS
    assert lines[EstimateStep.BASIC_LIVING].amount_minor == 159_500
    assert lines[EstimateStep.SALARY_INCOME].amount_minor == 182_000
    assert lines[EstimateStep.GROSS_INCOME].amount_minor == 182_000
    assert lines[EstimateStep.NET_INCOME].amount_minor == 0
    assert result.tax_minor == 0
    assert result.withheld_minor == 0
    assert result.balance_minor == 0
    assert result.filing_exempt is True
    assert result.cautions == (EstimateCaution.SALARY_FROM_LEDGER,)


@pytest.mark.parametrize(
    ("gross", "expected_net"),
    [(1_036_000, 590_000), (1_036_001, 590_001)],
)
def test_golden_case_salary_crosses_a_bracket_without_a_tax_jump(
    gross: int, expected_net: int
) -> None:
    result = _estimate(
        overrides={IncomeKind.SALARY: _override(IncomeKind.SALARY, gross)}
    )
    lines = _line_map(result)

    assert lines[EstimateStep.NET_INCOME].amount_minor == expected_net
    assert result.tax_minor == 29_500


def test_progressive_tax_is_continuous_at_the_bracket_cutoff() -> None:
    brackets = _parameters().brackets

    assert progressive_tax(590_000, brackets, Rounding.HALF_UP) == 29_500
    assert progressive_tax(590_001, brackets, Rounding.HALF_UP) == 29_500


def test_golden_case_basic_living_expense_and_refund_balance() -> None:
    result = _estimate(
        inputs=_inputs(dependents=3),
        basic_living=SourcedAmount(210_000, ("basic-living-test",)),
        overrides={IncomeKind.SALARY: _override(IncomeKind.SALARY, 1_500_000, 30_000)},
    )
    lines = _line_map(result)

    assert lines[EstimateStep.EXEMPTION].amount_minor == 388_000
    assert lines[EstimateStep.BASIC_LIVING].amount_minor == 321_000
    assert lines[EstimateStep.BASIC_LIVING].source_ids == ("basic-living-test",)
    assert lines[EstimateStep.GROSS_INCOME].amount_minor == 1_282_000
    assert lines[EstimateStep.NET_INCOME].amount_minor == 442_000
    assert result.tax_minor == 22_100
    assert result.withheld_minor == 30_000
    assert result.balance_minor == -7_900
    assert lines[EstimateStep.BALANCE].amount_minor == -7_900
    assert result.filing_exempt is False


def test_golden_case_interest_override_uses_ledger_withholding_independently() -> None:
    result = _estimate(
        overrides={
            IncomeKind.INTEREST_TAXABLE: _override(
                IncomeKind.INTEREST_TAXABLE, 300_000, 30_000
            )
        },
        ledger=_ledger(
            {IncomeKind.INTEREST_TAXABLE: _total(1, 263_670, 30_000, 6_330)}
        ),
    )
    lines = _line_map(result)

    assert lines[EstimateStep.INTEREST].amount_minor == 300_000
    assert lines[EstimateStep.INTEREST].source is LineSource.MANUAL
    assert lines[EstimateStep.SAVINGS_DEDUCTION].amount_minor == 270_000
    assert lines[EstimateStep.BASIC_LIVING].amount_minor == 0
    assert lines[EstimateStep.NET_INCOME].amount_minor == 0
    assert result.tax_minor == 0
    assert result.withheld_minor == 30_000
    assert result.balance_minor == -30_000
    assert result.filing_exempt is False


@pytest.mark.parametrize(
    ("reason", "case"),
    [
        (UnsupportedReason.DATASET_UNAVAILABLE, "dataset"),
        (UnsupportedReason.PARAMETERS_MISSING, "parameters"),
        (UnsupportedReason.BASIC_LIVING_PENDING, "basic_living"),
        (UnsupportedReason.INPUTS_MISSING, "inputs"),
        (UnsupportedReason.UNMAPPED_INCOME, "unmapped"),
        (UnsupportedReason.WITH_SPOUSE, "spouse"),
        (UnsupportedReason.DEPENDENT_OF_OTHER, "dependent_of_other"),
        (UnsupportedReason.DEPENDENT_INCOME, "dependent_income"),
        (UnsupportedReason.ITEMIZED_DEDUCTION, "itemized"),
        (UnsupportedReason.OTHER_SPECIAL_DEDUCTIONS, "special"),
        (UnsupportedReason.UNSUPPORTED_INCOME, "unsupported"),
        (UnsupportedReason.WRITING_LECTURE_OVER_CAP, "writing"),
        (UnsupportedReason.FOREIGN_INCOME_AMT, "foreign"),
        (UnsupportedReason.AMT_POSSIBLE, "amt"),
    ],
)
def test_each_unsupported_reason_refuses_without_any_amounts(
    reason: UnsupportedReason, case: str
) -> None:
    parameters: IncomeTaxParameters | None = _parameters()
    inputs: TaxYearInputs | None = _inputs()
    ledger = _ledger()
    overrides: dict[IncomeKind, TaxYearOverride] = {}
    available = True
    basic_living: SourcedAmount | None = _amount(210_000)
    if case == "dataset":
        parameters = None
        available = False
    elif case == "parameters":
        parameters = None
    elif case == "basic_living":
        basic_living = None
    elif case == "inputs":
        inputs = None
    elif case == "unmapped":
        ledger = _ledger(unmapped=_total(1, 500))
    elif case == "spouse":
        inputs = _inputs(filing=FilingStatus.WITH_SPOUSE)
    elif case == "dependent_of_other":
        inputs = _inputs(filing=FilingStatus.DEPENDENT_OF_OTHER)
    elif case == "dependent_income":
        inputs = _inputs(dependents_have_income=True)
    elif case == "itemized":
        inputs = _inputs(deduction=DeductionChoice.ITEMIZED)
    elif case == "special":
        inputs = _inputs(other_special_deductions=True)
    elif case == "unsupported":
        ledger = _ledger({IncomeKind.UNSUPPORTED: _total(1, 10_000)})
    elif case == "writing":
        ledger = _ledger({IncomeKind.WRITING_LECTURE: _total(1, 180_001)})
    elif case == "foreign":
        ledger = _ledger({IncomeKind.FOREIGN_INCOME: _total(1, 1_000_000)})
    elif case == "amt":
        parameters = replace(_parameters(), amt_basic_exemption=_amount(0))
        overrides = {IncomeKind.SALARY: _override(IncomeKind.SALARY, 800_000)}

    result = estimate_income_tax(
        income_year=2025,
        dataset_available=available,
        parameters=parameters,
        basic_living=basic_living,
        inputs=inputs,
        overrides=overrides,
        ledger=ledger,
    )

    assert result.refused == (reason,)
    assert result.lines == ()
    assert result.cautions == ()
    assert result.tax_minor is None
    assert result.withheld_minor is None
    assert result.balance_minor is None
    assert result.filing_exempt is None
    assert result.official_diff_minor is None


def test_multiple_refusal_reasons_are_complete_and_in_declaration_order() -> None:
    """REQ-0011 §拒算：全部原因都列出來。資料不可用時只是不另外報參數與基本生活費。"""
    result = estimate_income_tax(
        income_year=2025,
        dataset_available=False,
        parameters=None,
        basic_living=None,
        inputs=None,
        overrides={},
        ledger=_ledger(
            {IncomeKind.UNSUPPORTED: _total(1, 100)},
            unmapped=_total(1, 100),
        ),
    )

    assert result.refused == (
        UnsupportedReason.DATASET_UNAVAILABLE,
        UnsupportedReason.INPUTS_MISSING,
        UnsupportedReason.UNMAPPED_INCOME,
        UnsupportedReason.UNSUPPORTED_INCOME,
    )
    assert UnsupportedReason.PARAMETERS_MISSING not in result.refused
    assert UnsupportedReason.BASIC_LIVING_PENDING not in result.refused
    assert result.lines == () and result.tax_minor is None


def test_missing_parameters_does_not_also_report_basic_living_pending() -> None:
    result = estimate_income_tax(
        income_year=2025,
        dataset_available=True,
        parameters=None,
        basic_living=None,
        inputs=_inputs(),
        overrides={},
        ledger=_ledger(),
    )

    assert result.refused == (UnsupportedReason.PARAMETERS_MISSING,)
    assert result.lines == () and result.tax_minor is None


def test_negative_official_balance_does_not_block_estimation() -> None:
    result = _estimate(
        inputs=_inputs(official_balance_minor=-7_900),
        overrides={IncomeKind.SALARY: _override(IncomeKind.SALARY, 800_000)},
    )

    assert result.refused == ()
    assert result.tax_minor == 17_700


def test_writing_lecture_cap_accepts_the_limit_and_override_takes_precedence() -> None:
    accepted = _estimate(
        ledger=_ledger({IncomeKind.WRITING_LECTURE: _total(1, 180_000)})
    )
    accepted_line = _line_map(accepted)[EstimateStep.WRITING_LECTURE]
    assert accepted.refused == ()
    assert accepted_line.amount_minor == 180_000
    assert accepted_line.included is False

    rejected = _estimate(
        ledger=_ledger({IncomeKind.WRITING_LECTURE: _total(1, 180_001)})
    )
    override_rejected = _estimate(
        overrides={
            IncomeKind.WRITING_LECTURE: _override(
                IncomeKind.WRITING_LECTURE, 180_001
            )
        },
        ledger=_ledger({IncomeKind.WRITING_LECTURE: _total(1, 100_000)}),
    )
    assert rejected.refused == (UnsupportedReason.WRITING_LECTURE_OVER_CAP,)
    assert override_rejected.refused == (UnsupportedReason.WRITING_LECTURE_OVER_CAP,)


def test_foreign_income_threshold_is_inclusive_and_never_included() -> None:
    below = _estimate(
        ledger=_ledger({IncomeKind.FOREIGN_INCOME: _total(1, 999_999)})
    )
    line = _line_map(below)[EstimateStep.FOREIGN]
    assert below.refused == ()
    assert line.amount_minor == 999_999
    assert line.included is False
    at_threshold = _estimate(
        ledger=_ledger({IncomeKind.FOREIGN_INCOME: _total(1, 1_000_000)})
    )
    assert at_threshold.refused == (UnsupportedReason.FOREIGN_INCOME_AMT,)


def test_amt_refusal_is_strict_and_not_checked_for_unsupported_filing() -> None:
    salary = {IncomeKind.SALARY: _override(IncomeKind.SALARY, 800_000)}
    at_limit = _estimate(
        parameters=replace(_parameters(), amt_basic_exemption=_amount(354_000)),
        overrides=salary,
    )
    below_limit = _estimate(
        parameters=replace(_parameters(), amt_basic_exemption=_amount(353_999)),
        overrides=salary,
    )
    spouse = _estimate(
        parameters=replace(_parameters(), amt_basic_exemption=_amount(0)),
        inputs=_inputs(filing=FilingStatus.WITH_SPOUSE),
        overrides=salary,
    )

    assert at_limit.refused == ()
    assert below_limit.refused == (UnsupportedReason.AMT_POSSIBLE,)
    assert spouse.refused == (UnsupportedReason.WITH_SPOUSE,)


def test_official_tax_difference_and_prize_cautions() -> None:
    compared = _estimate(
        inputs=_inputs(official_tax_minor=17_000),
        overrides={IncomeKind.SALARY: _override(IncomeKind.SALARY, 800_000)},
        ledger=_ledger({IncomeKind.INTEREST_TAXABLE: _total(2, 26_367, 3_000, 633)}),
    )
    without_official = _estimate(
        overrides={IncomeKind.SALARY: _override(IncomeKind.SALARY, 800_000)},
        ledger=_ledger({IncomeKind.INTEREST_TAXABLE: _total(2, 26_367, 3_000, 633)}),
    )
    prize = _estimate(ledger=_ledger({IncomeKind.PRIZE: _total(1, 50_000)}))

    assert compared.official_diff_minor == 700
    assert without_official.official_diff_minor is None
    assert prize.cautions == (
        EstimateCaution.PRIZE_FROM_LEDGER,
        EstimateCaution.PRIZE_EXPENSES_NOT_DEDUCTED,
    )


def test_fixture_names_and_fixable_reasons_follow_declared_order() -> None:
    assert FIXABLE_REASONS == (
        UnsupportedReason.DATASET_UNAVAILABLE,
        UnsupportedReason.PARAMETERS_MISSING,
        UnsupportedReason.INPUTS_MISSING,
        UnsupportedReason.UNMAPPED_INCOME,
    )
    assert tuple(ESTIMATE_STEP_NAMES) == tuple(EstimateStep)
    assert set(ESTIMATE_CAUTION_NAMES) == set(EstimateCaution)


@pytest.mark.parametrize(
    ("overrides", "ledger", "inputs"),
    [
        ({IncomeKind.OTHER_INCOME: _override(IncomeKind.OTHER_INCOME, 100)}, _ledger(), _inputs()),
        (
            {IncomeKind.SALARY: _override(IncomeKind.PRIZE, 100)},
            _ledger(),
            _inputs(),
        ),
        (
            {IncomeKind.SALARY: _override(IncomeKind.SALARY, -1)},
            _ledger(),
            _inputs(),
        ),
        ({}, _ledger(), _inputs(dependents=0, dependents_70_plus=1)),
        ({}, _ledger(), _inputs(official_balance_minor=True)),
        ({}, _ledger(), _inputs(official_balance_minor=7_900.0)),
    ],
)
def test_invalid_override_and_input_shapes_raise_value_error(
    overrides: dict[IncomeKind, TaxYearOverride], ledger: LedgerIncome, inputs: TaxYearInputs
) -> None:
    with pytest.raises(ValueError):
        _estimate(overrides=overrides, ledger=ledger, inputs=inputs)
