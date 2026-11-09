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
class TaxMappingRow:
    """所得歸類分頁的一列：一個類別或項目、它的對應、該年的收入。"""

    category_id: str
    parent_id: str | None
    category_name: str
    item_name: str | None
    archived: bool
    income_kind: IncomeKind | None
    expense_kind: TaxKind | None
    parent_income_kind: IncomeKind | None
    parent_expense_kind: TaxKind | None
    effective_income_kind: IncomeKind | None
    effective_expense_kind: TaxKind | None
    own_year_count: int
    own_year_minor: int
    year_count: int
    year_minor: int

    @property
    def unmapped(self) -> bool:
        return self.own_year_count > 0 and self.effective_income_kind is None


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
    # 名字沿用，意思是「受扶養人中免稅額增加百分之五十的人數」：受扶養直系尊親屬年滿 70 歲，
    # 115 年度起也包括未成年的受扶養子女（所得稅法第 17 條 115-09-11 修正；REQ-0011 第 8 步）。
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
