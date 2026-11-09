"""驗證與解析綜所稅試算輸入的私有輔助。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping

from tagcor_ledger.domain.tax.kinds import OVERRIDABLE_INCOME_KINDS, IncomeKind
from tagcor_ledger.domain.tax.records import TaxYearInputs, TaxYearOverride

if TYPE_CHECKING:
    from tagcor_ledger.domain.tax.estimate import LedgerIncome


def _nonnegative(value: int | None, name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} 必須是非負整數")


def _integer(value: int | None, name: str) -> None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise ValueError(f"{name} 必須是整數")


def _validate_inputs(
    overrides: Mapping[IncomeKind, TaxYearOverride],
    ledger: LedgerIncome,
    inputs: TaxYearInputs | None,
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
        _integer(inputs.official_balance_minor, "official_balance_minor")
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
