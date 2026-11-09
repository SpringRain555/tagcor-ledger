"""公開稅務資料的不可變模型與查詢方法。"""

from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Mapping

from tagcor_ledger.domain.tax.arithmetic import Rounding
from tagcor_ledger.domain.tax.kinds import TaxKind


@dataclass(frozen=True, slots=True)
class TaxSource:
    id: str
    title: str
    publisher: str
    url: str
    published_on: date | None
    sha256: str
    fetched_at: str


@dataclass(frozen=True, slots=True)
class SourcedAmount:
    value: int
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TypicalWindow:
    kind: TaxKind
    start_month: int
    start_day: int
    end_month: int
    end_day: int
    basis: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Window:
    kind: TaxKind
    year: int
    start: date
    end: date
    estimated: bool
    note: str | None
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Bracket:
    up_to: int | None
    rate_ppm: int
    progressive_difference: int


@dataclass(frozen=True, slots=True)
class IncomeTaxParameters:
    income_year: int
    exemption: SourcedAmount
    exemption_70_plus: SourcedAmount
    standard_deduction_single: SourcedAmount
    salary_special_deduction_cap: SourcedAmount
    savings_investment_cap: SourcedAmount
    basic_living_expense: SourcedAmount
    writing_lecture_exemption_cap: SourcedAmount
    foreign_income_amt_threshold: SourcedAmount
    amt_basic_exemption: SourcedAmount
    brackets: tuple[Bracket, ...]
    brackets_source_ids: tuple[str, ...]
    tax_rounding: Rounding
    tax_rounding_source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InterestWithholdingRule:
    effective_from: date
    rate_ppm: int
    exempt_if_tax_at_most: int
    rounding: Rounding
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NhiPremiumRule:
    effective_from: date
    rate_ppm: int
    threshold_at_least: int
    base_cap: int
    rounding: Rounding
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TaxDataset:
    schema_version: int
    reviewed_at: date | None
    next_review_on: date | None
    notes: tuple[str, ...]
    sources: tuple[TaxSource, ...]
    typical: Mapping[TaxKind, TypicalWindow]
    years: Mapping[int, Mapping[TaxKind, Window]]
    income_tax: Mapping[int, IncomeTaxParameters]
    interest_withholding: tuple[InterestWithholdingRule, ...]
    nhi_supplementary_premium: tuple[NhiPremiumRule, ...]

    def __post_init__(self) -> None:
        """包裝所有索引映射，避免 frozen dataclass 內藏可變字典。"""
        object.__setattr__(self, "typical", MappingProxyType(dict(self.typical)))
        year_windows = {
            year: MappingProxyType(dict(windows)) for year, windows in self.years.items()
        }
        object.__setattr__(self, "years", MappingProxyType(year_windows))
        object.__setattr__(self, "income_tax", MappingProxyType(dict(self.income_tax)))

    @property
    def populated(self) -> bool:
        """資料曾經複查並標記為正式填入。"""
        return self.reviewed_at is not None

    def window_for(self, kind: TaxKind, year: int) -> Window | None:
        """優先回傳該年公告期間，否則將典型期間套用到該年。"""
        published = self.years.get(year, {}).get(kind)
        if published is not None:
            return published
        typical = self.typical.get(kind)
        if typical is None:
            return None
        try:
            start = date(year, typical.start_month, typical.start_day)
            end = date(year, typical.end_month, typical.end_day)
        except ValueError:
            return None
        return Window(
            kind=kind,
            year=year,
            start=start,
            end=end,
            estimated=True,
            note=typical.basis,
            source_ids=typical.source_ids,
        )

    def parameters_for(self, income_year: int) -> IncomeTaxParameters | None:
        """取得指定所得年度的綜所稅參數。"""
        return self.income_tax.get(income_year)

    def withholding_rule_on(self, day: date) -> InterestWithholdingRule | None:
        """取得指定日期已生效的最後一條利息扣繳規則。"""
        applicable = [rule for rule in self.interest_withholding if rule.effective_from <= day]
        return applicable[-1] if applicable else None

    def premium_rule_on(self, day: date) -> NhiPremiumRule | None:
        """取得指定日期已生效的最後一條補充保費規則。"""
        applicable = [rule for rule in self.nhi_supplementary_premium if rule.effective_from <= day]
        return applicable[-1] if applicable else None

    def source(self, source_id: str) -> TaxSource | None:
        """依來源識別字取得公開來源。"""
        return next((source for source in self.sources if source.id == source_id), None)
