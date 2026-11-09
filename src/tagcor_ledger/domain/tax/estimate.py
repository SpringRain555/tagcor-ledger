"""純函式計算綜合所得稅估計與可追溯明細。"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from tagcor_ledger.domain.tax.arithmetic import Rounding, apply_rate
from tagcor_ledger.domain.tax.dataset import Bracket, IncomeTaxParameters
from tagcor_ledger.domain.tax.kinds import (
    OVERRIDABLE_INCOME_KINDS,
    DeductionChoice,
    FilingStatus,
    IncomeKind,
)
from tagcor_ledger.domain.tax.records import KindTotal, TaxYearInputs, TaxYearOverride


class UnsupportedReason(StrEnum):
    """綜所稅試算拒算原因；列舉順序也是輸出的順序。"""

    DATASET_UNAVAILABLE = "dataset_unavailable"
    PARAMETERS_MISSING = "parameters_missing"
    INPUTS_MISSING = "inputs_missing"
    UNMAPPED_INCOME = "unmapped_income"
    WITH_SPOUSE = "with_spouse"
    DEPENDENT_OF_OTHER = "dependent_of_other"
    DEPENDENT_INCOME = "dependent_income"
    ITEMIZED_DEDUCTION = "itemized_deduction"
    OTHER_SPECIAL_DEDUCTIONS = "other_special_deductions"
    UNSUPPORTED_INCOME = "unsupported_income"
    WRITING_LECTURE_OVER_CAP = "writing_lecture_over_cap"
    FOREIGN_INCOME_AMT = "foreign_income_amt"
    AMT_POSSIBLE = "amt_possible"


UNSUPPORTED_REASON_NAMES = {
    UnsupportedReason.DATASET_UNAVAILABLE: "稅務資料不可用。",
    UnsupportedReason.PARAMETERS_MISSING: "稅務資料缺這一年度的參數。",
    UnsupportedReason.INPUTS_MISSING: "這一年的申報狀況還沒填。",
    UnsupportedReason.UNMAPPED_INCOME: "有收入還沒歸類。",
    UnsupportedReason.WITH_SPOUSE: "與配偶合併申報不在試算範圍內。",
    UnsupportedReason.DEPENDENT_OF_OTHER: "被他人列為受扶養人不在試算範圍內。",
    UnsupportedReason.DEPENDENT_INCOME: "受扶養人有所得不在試算範圍內。",
    UnsupportedReason.ITEMIZED_DEDUCTION: "列舉扣除不在試算範圍內。",
    UnsupportedReason.OTHER_SPECIAL_DEDUCTIONS: (
        "其他特別扣除（身心障礙、教育學費、幼兒學前、長期照顧、租屋支出等）不在試算範圍內。"
    ),
    UnsupportedReason.UNSUPPORTED_INCOME: "有試算不支援的所得（股利、租賃、財產交易等）。",
    UnsupportedReason.WRITING_LECTURE_OVER_CAP: (
        "稿費、講演鐘點費超過免稅上限，超過的部分要依類型減必要費用，試算不支援。"
    ),
    UnsupportedReason.FOREIGN_INCOME_AMT: "海外所得達到最低稅負的門檻，試算不支援。",
    UnsupportedReason.AMT_POSSIBLE: "所得淨額超過最低稅負的免稅額，可能要繳基本稅額，試算不支援。",
}

FIXABLE_REASONS = tuple(UnsupportedReason)[:4]


class EstimateStep(StrEnum):
    """試算明細項目；列舉順序是所得行與計算行的順序。"""

    SALARY_GROSS = "salary_gross"
    SALARY_DEDUCTION = "salary_deduction"
    SALARY_INCOME = "salary_income"
    INTEREST = "interest"
    PRIZE = "prize"
    OTHER = "other"
    WRITING_LECTURE = "writing_lecture"
    FOREIGN = "foreign"
    INTEREST_EXEMPT = "interest_exempt"
    EXEMPT_INCOME = "exempt_income"
    EXCLUDED = "excluded"
    GROSS_INCOME = "gross_income"
    EXEMPTION = "exemption"
    STANDARD_DEDUCTION = "standard_deduction"
    SAVINGS_DEDUCTION = "savings_deduction"
    BASIC_LIVING = "basic_living"
    NET_INCOME = "net_income"
    TAX = "tax"
    WITHHELD = "withheld"
    BALANCE = "balance"


ESTIMATE_STEP_NAMES = {
    EstimateStep.SALARY_GROSS: "薪資收入",
    EstimateStep.SALARY_DEDUCTION: "減：薪資所得特別扣除額",
    EstimateStep.SALARY_INCOME: "薪資所得",
    EstimateStep.INTEREST: "利息所得",
    EstimateStep.PRIZE: "競技競賽及機會中獎獎金",
    EstimateStep.OTHER: "其他所得",
    EstimateStep.WRITING_LECTURE: "稿費、講演鐘點費（免稅，不併入）",
    EstimateStep.FOREIGN: "海外所得（不併入綜合所得）",
    EstimateStep.INTEREST_EXEMPT: "免稅利息（不併入）",
    EstimateStep.EXEMPT_INCOME: "免稅所得（不併入，依你的歸類）",
    EstimateStep.EXCLUDED: "不計入的收入",
    EstimateStep.GROSS_INCOME: "綜合所得總額",
    EstimateStep.EXEMPTION: "減：免稅額",
    EstimateStep.STANDARD_DEDUCTION: "減：標準扣除額",
    EstimateStep.SAVINGS_DEDUCTION: "減：儲蓄投資特別扣除額",
    EstimateStep.BASIC_LIVING: "減：基本生活費差額",
    EstimateStep.NET_INCOME: "所得淨額",
    EstimateStep.TAX: "應納稅額",
    EstimateStep.WITHHELD: "減：已扣繳稅額（補充保費不算）",
    EstimateStep.BALANCE: "應補（退）稅額",
}


class LineSource(StrEnum):
    """試算明細金額的來源類型。"""

    LEDGER = "ledger"
    MANUAL = "manual"
    DATASET = "dataset"
    COMPUTED = "computed"


@dataclass(frozen=True, slots=True)
class EstimateLine:
    step: EstimateStep
    amount_minor: int
    source: LineSource
    ledger_count: int | None
    source_ids: tuple[str, ...]
    included: bool

    def __post_init__(self) -> None:
        """限制明細金額正負與帳本筆數來源。"""
        if isinstance(self.amount_minor, bool) or not isinstance(self.amount_minor, int):
            raise ValueError("amount_minor 必須是整數")
        if self.step is not EstimateStep.BALANCE and self.amount_minor < 0:
            raise ValueError("只有 balance 金額可以是負數")
        if self.source is LineSource.LEDGER:
            if (
                self.ledger_count is None
                or isinstance(self.ledger_count, bool)
                or self.ledger_count < 0
            ):
                raise ValueError("帳本來源必須帶非負 ledger_count")
        elif self.ledger_count is not None:
            raise ValueError("非帳本來源的 ledger_count 必須是 None")


class EstimateCaution(StrEnum):
    """試算結果的補充提醒。"""

    SALARY_FROM_LEDGER = "salary_from_ledger"
    PRIZE_FROM_LEDGER = "prize_from_ledger"
    PRIZE_EXPENSES_NOT_DEDUCTED = "prize_expenses_not_deducted"


ESTIMATE_CAUTION_NAMES = {
    EstimateCaution.SALARY_FROM_LEDGER: (
        "薪資用的是帳本的實領金額，通常低於扣繳憑單的給付總額；有扣繳憑單時請填給付總額。"
    ),
    EstimateCaution.PRIZE_FROM_LEDGER: (
        "獎金用的是帳本的實領金額；被扣繳過的獎金，給付總額比實領多，有扣繳憑單時請填給付總額。"
    ),
    EstimateCaution.PRIZE_EXPENSES_NOT_DEDUCTED: (
        "參加競技、競賽的必要費用可以減除，試算沒有減，所以估計的稅可能偏高。"
    ),
}


@dataclass(frozen=True, slots=True)
class LedgerIncome:
    by_kind: Mapping[IncomeKind, KindTotal]
    unmapped: KindTotal

    def total(self, kind: IncomeKind) -> KindTotal:
        """取得類別金額；缺項時回傳零筆、零金額。"""
        return self.by_kind.get(kind, KindTotal(0, 0, 0, 0))


@dataclass(frozen=True, slots=True)
class Estimate:
    income_year: int
    refused: tuple[UnsupportedReason, ...]
    lines: tuple[EstimateLine, ...]
    tax_minor: int | None
    withheld_minor: int | None
    balance_minor: int | None
    filing_exempt: bool | None
    official_diff_minor: int | None
    cautions: tuple[EstimateCaution, ...]


def progressive_tax(
    net_minor: int,
    brackets: tuple[Bracket, ...],
    rounding: Rounding,
) -> int:
    """依第一個符合的稅率級距計算累進稅額。"""
    if isinstance(net_minor, bool) or not isinstance(net_minor, int) or net_minor < 0:
        raise ValueError("net_minor 必須是非負整數")
    for bracket in brackets:
        if bracket.up_to is None or net_minor <= bracket.up_to:
            return max(
                0,
                apply_rate(net_minor, bracket.rate_ppm, rounding)
                - bracket.progressive_difference,
            )
    raise ValueError("brackets 必須包含最後一個無上限級距")


def _nonnegative(value: int | None, name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} 必須是非負整數")


def _validate_inputs(
    overrides: Mapping[IncomeKind, TaxYearOverride], ledger: LedgerIncome, inputs: TaxYearInputs | None
) -> None:
    for kind, override in overrides.items():
        if kind not in OVERRIDABLE_INCOME_KINDS:
            raise ValueError("overrides 含不支援覆寫的所得類別")
        if kind is not override.income_kind:
            raise ValueError("overrides 鍵必須與 TaxYearOverride.income_kind 一致")
        _nonnegative(override.gross_minor, "gross_minor")
        _nonnegative(override.withheld_minor, "withheld_minor")
    for kind, total in ledger.by_kind.items():
        _nonnegative(total.count, f"{kind}.count")
        _nonnegative(total.net_minor, f"{kind}.net_minor")
        _nonnegative(total.withheld_tax_minor, f"{kind}.withheld_tax_minor")
        _nonnegative(total.nhi_premium_minor, f"{kind}.nhi_premium_minor")
    _nonnegative(ledger.unmapped.count, "unmapped.count")
    _nonnegative(ledger.unmapped.net_minor, "unmapped.net_minor")
    _nonnegative(ledger.unmapped.withheld_tax_minor, "unmapped.withheld_tax_minor")
    _nonnegative(ledger.unmapped.nhi_premium_minor, "unmapped.nhi_premium_minor")
    if inputs is not None:
        _nonnegative(inputs.dependents, "dependents")
        _nonnegative(inputs.dependents_70_plus, "dependents_70_plus")
        _nonnegative(inputs.official_tax_minor, "official_tax_minor")
        _nonnegative(inputs.official_balance_minor, "official_balance_minor")
        if inputs.dependents_70_plus > inputs.dependents:
            raise ValueError("dependents_70_plus 不得大於 dependents")


def _override_amount(
    overrides: Mapping[IncomeKind, TaxYearOverride], kind: IncomeKind, field: str
) -> int | None:
    override = overrides.get(kind)
    if override is None:
        return None
    if field == "gross":
        return override.gross_minor
    return override.withheld_minor


def _amount_sources(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(source_id for group in groups for source_id in group))


def _line(
    step: EstimateStep,
    amount: int,
    source: LineSource = LineSource.COMPUTED,
    *,
    count: int | None = None,
    source_ids: tuple[str, ...] = (),
    included: bool = True,
) -> EstimateLine:
    return EstimateLine(step, amount, source, count, source_ids, included)


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
        override_amount = _override_amount(overrides, kind, "gross")
        manual[kind] = override_amount is not None
        counts[kind] = total.count
        if override_amount is not None:
            gross[kind] = override_amount
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


def _refusal_reasons(
    *,
    dataset_available: bool,
    parameters: IncomeTaxParameters | None,
    inputs: TaxYearInputs | None,
    overrides: Mapping[IncomeKind, TaxYearOverride],
    ledger: LedgerIncome,
    amounts: Mapping[IncomeKind, int],
) -> tuple[UnsupportedReason, ...]:
    reasons: list[UnsupportedReason] = []
    if not dataset_available:
        reasons.append(UnsupportedReason.DATASET_UNAVAILABLE)
    elif parameters is None:
        reasons.append(UnsupportedReason.PARAMETERS_MISSING)
    if inputs is None:
        reasons.append(UnsupportedReason.INPUTS_MISSING)
    if ledger.unmapped.count > 0:
        reasons.append(UnsupportedReason.UNMAPPED_INCOME)
    if inputs is not None:
        if inputs.filing is FilingStatus.WITH_SPOUSE:
            reasons.append(UnsupportedReason.WITH_SPOUSE)
        elif inputs.filing is FilingStatus.DEPENDENT_OF_OTHER:
            reasons.append(UnsupportedReason.DEPENDENT_OF_OTHER)
        if inputs.dependents_have_income:
            reasons.append(UnsupportedReason.DEPENDENT_INCOME)
        if inputs.deduction is DeductionChoice.ITEMIZED:
            reasons.append(UnsupportedReason.ITEMIZED_DEDUCTION)
        if inputs.other_special_deductions:
            reasons.append(UnsupportedReason.OTHER_SPECIAL_DEDUCTIONS)
    if ledger.total(IncomeKind.UNSUPPORTED).count > 0:
        reasons.append(UnsupportedReason.UNSUPPORTED_INCOME)
    if parameters is not None:
        writing_override = _override_amount(overrides, IncomeKind.WRITING_LECTURE, "gross")
        writing_total = (
            writing_override
            if writing_override is not None
            else ledger.total(IncomeKind.WRITING_LECTURE).net_minor
        )
        if writing_total > parameters.writing_lecture_exemption_cap.value:
            reasons.append(UnsupportedReason.WRITING_LECTURE_OVER_CAP)
        if (
            ledger.total(IncomeKind.FOREIGN_INCOME).net_minor
            >= parameters.foreign_income_amt_threshold.value
        ):
            reasons.append(UnsupportedReason.FOREIGN_INCOME_AMT)
        input_reasons = {
            UnsupportedReason.WITH_SPOUSE,
            UnsupportedReason.DEPENDENT_OF_OTHER,
            UnsupportedReason.DEPENDENT_INCOME,
            UnsupportedReason.ITEMIZED_DEDUCTION,
            UnsupportedReason.OTHER_SPECIAL_DEDUCTIONS,
        }
        if inputs is not None and not any(reason in input_reasons for reason in reasons):
            net = _net_income(parameters, inputs, amounts)
            if net > parameters.amt_basic_exemption.value:
                reasons.append(UnsupportedReason.AMT_POSSIBLE)
    reason_order = {reason: index for index, reason in enumerate(UnsupportedReason)}
    return tuple(sorted(set(reasons), key=lambda reason: reason_order[reason]))


def _net_income(
    parameters: IncomeTaxParameters,
    inputs: TaxYearInputs,
    amounts: Mapping[IncomeKind, int],
) -> int:
    salary_income = max(
        0,
        amounts[IncomeKind.SALARY]
        - min(amounts[IncomeKind.SALARY], parameters.salary_special_deduction_cap.value),
    )
    gross_income = (
        salary_income
        + amounts[IncomeKind.INTEREST_TAXABLE]
        + amounts[IncomeKind.PRIZE]
        + amounts[IncomeKind.OTHER_INCOME]
    )
    exemptions, _, _ = _exemption_amount(parameters, inputs)
    standard = parameters.standard_deduction_single.value
    savings = min(
        amounts[IncomeKind.INTEREST_TAXABLE], parameters.savings_investment_cap.value
    )
    basic = max(
        0,
        parameters.basic_living_expense.value * (1 + inputs.dependents)
        - (exemptions + standard + savings),
    )
    return max(0, gross_income - exemptions - standard - savings - basic)


def _exemption_amount(
    parameters: IncomeTaxParameters, inputs: TaxYearInputs
) -> tuple[int, int, int]:
    dependents = inputs.dependents
    elderly_count = int(inputs.filer_70_plus) + inputs.dependents_70_plus
    regular_count = 1 + dependents - elderly_count
    exemption = (
        regular_count * parameters.exemption.value
        + elderly_count * parameters.exemption_70_plus.value
    )
    return exemption, regular_count, elderly_count


def _used_withholding(
    ledger: LedgerIncome,
    overrides: Mapping[IncomeKind, TaxYearOverride],
) -> int:
    kinds = (
        IncomeKind.SALARY,
        IncomeKind.INTEREST_TAXABLE,
        IncomeKind.PRIZE,
        IncomeKind.WRITING_LECTURE,
    )
    total = 0
    for kind in kinds:
        override_withheld = _override_amount(overrides, kind, "withheld")
        total += (
            override_withheld
            if override_withheld is not None
            else ledger.total(kind).withheld_tax_minor
        )
    return total


def _refused_estimate(income_year: int, refused: tuple[UnsupportedReason, ...]) -> Estimate:
    return Estimate(income_year, refused, (), None, None, None, None, None, ())


def estimate_income_tax(
    *,
    income_year: int,
    dataset_available: bool,
    parameters: IncomeTaxParameters | None,
    inputs: TaxYearInputs | None,
    overrides: Mapping[IncomeKind, TaxYearOverride],
    ledger: LedgerIncome,
) -> Estimate:
    """整合帳本與使用者資料試算所得稅；有拒算原因時不回任何稅額。"""
    _validate_inputs(overrides, ledger, inputs)
    amounts, counts, manual = _income_amounts(overrides, ledger)
    refused = _refusal_reasons(
        dataset_available=dataset_available,
        parameters=parameters,
        inputs=inputs,
        overrides=overrides,
        ledger=ledger,
        amounts=amounts,
    )
    if refused:
        return _refused_estimate(income_year, refused)
    if parameters is None or inputs is None:
        raise ValueError("拒算檢查漏掉必要輸入")

    salary_gross = amounts[IncomeKind.SALARY]
    salary_deduction = min(salary_gross, parameters.salary_special_deduction_cap.value)
    salary_income = salary_gross - salary_deduction
    taxable_interest = amounts[IncomeKind.INTEREST_TAXABLE]
    prize = amounts[IncomeKind.PRIZE]
    other = amounts[IncomeKind.OTHER_INCOME]
    gross_income = salary_income + taxable_interest + prize + other
    exemption, _, elderly_count = _exemption_amount(parameters, inputs)
    standard = parameters.standard_deduction_single.value
    savings = min(taxable_interest, parameters.savings_investment_cap.value)
    basic_living = max(
        0,
        parameters.basic_living_expense.value * (1 + inputs.dependents)
        - (exemption + standard + savings),
    )
    net_income = max(0, gross_income - exemption - standard - savings - basic_living)
    tax = progressive_tax(net_income, parameters.brackets, parameters.tax_rounding)
    withheld = _used_withholding(ledger, overrides)
    balance = tax - withheld

    lines: list[EstimateLine] = []
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
                salary_deduction,
                source_ids=parameters.salary_special_deduction_cap.source_ids,
            )
        )
        lines.append(_line(EstimateStep.SALARY_INCOME, salary_income))

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
            _line(EstimateStep.GROSS_INCOME, gross_income),
            _line(
                EstimateStep.EXEMPTION,
                exemption,
                LineSource.DATASET,
                source_ids=_amount_sources(
                    parameters.exemption.source_ids,
                    parameters.exemption_70_plus.source_ids if elderly_count else (),
                ),
            ),
            _line(
                EstimateStep.STANDARD_DEDUCTION,
                standard,
                LineSource.DATASET,
                source_ids=parameters.standard_deduction_single.source_ids,
            ),
            _line(
                EstimateStep.SAVINGS_DEDUCTION,
                savings,
                source_ids=parameters.savings_investment_cap.source_ids,
            ),
            _line(
                EstimateStep.BASIC_LIVING,
                basic_living,
                source_ids=parameters.basic_living_expense.source_ids,
            ),
            _line(EstimateStep.NET_INCOME, net_income),
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

    cautions: list[EstimateCaution] = []
    if salary_count > 0 and not manual[IncomeKind.SALARY]:
        cautions.append(EstimateCaution.SALARY_FROM_LEDGER)
    if counts[IncomeKind.PRIZE] > 0 and not manual[IncomeKind.PRIZE]:
        cautions.append(EstimateCaution.PRIZE_FROM_LEDGER)
    if prize > 0:
        cautions.append(EstimateCaution.PRIZE_EXPENSES_NOT_DEDUCTED)
    official_diff = (
        tax - inputs.official_tax_minor
        if inputs.official_tax_minor is not None
        else None
    )
    filing_exempt = gross_income <= exemption + standard and withheld == 0
    return Estimate(
        income_year=income_year,
        refused=(),
        lines=tuple(lines),
        tax_minor=tax,
        withheld_minor=withheld,
        balance_minor=balance,
        filing_exempt=filing_exempt,
        official_diff_minor=official_diff,
        cautions=tuple(cautions),
    )
