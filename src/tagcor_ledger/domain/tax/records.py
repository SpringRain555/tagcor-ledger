"""稅務資料儲存與試算流程共用的不可變紀錄型別。"""

from dataclasses import dataclass

from tagcor_ledger.domain.tax.kinds import (
    DeductionChoice,
    FilingStatus,
    Flow,
    IncomeKind,
    ReminderMark,
    TaxKind,
)


@dataclass(frozen=True, slots=True)
class TaxMapping:
    category_id: str
    flow: Flow
    tax_kind: str


@dataclass(frozen=True, slots=True)
class ReminderMarkRecord:
    kind: TaxKind
    cycle_year: int
    mark: ReminderMark
    marked_at: str


@dataclass(frozen=True, slots=True)
class TaxYearInputs:
    income_year: int
    filing: FilingStatus
    deduction: DeductionChoice
    other_special_deductions: bool
    dependents_have_income: bool
    filer_70_plus: bool
    dependents: int
    dependents_70_plus: int
    official_tax_minor: int | None
    official_balance_minor: int | None


@dataclass(frozen=True, slots=True)
class TaxYearOverride:
    income_year: int
    income_kind: IncomeKind
    gross_minor: int | None
    withheld_minor: int | None


@dataclass(frozen=True, slots=True)
class KindTotal:
    count: int
    net_minor: int
    withheld_tax_minor: int
    nhi_premium_minor: int


@dataclass(frozen=True, slots=True)
class PaymentFact:
    count: int
    total_minor: int
    last_on: str | None
