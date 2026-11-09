"""依給付日期試算存款利息扣繳與補充保費。"""

from dataclasses import dataclass
from datetime import date

from tagcor_ledger.domain.tax.arithmetic import apply_rate, rate_exceeds
from tagcor_ledger.domain.tax.dataset import TaxDataset


@dataclass(frozen=True, slots=True)
class InterestDeductions:
    gross_minor: int
    withheld_tax_minor: int
    nhi_premium_minor: int
    withholding_rule_found: bool
    premium_rule_found: bool

    @property
    def net_minor(self) -> int:
        """扣除所得稅與補充保費後的預期入帳金額。"""
        return self.gross_minor - self.withheld_tax_minor - self.nhi_premium_minor


def interest_deductions(
    gross_minor: int, *, on: date, dataset: TaxDataset
) -> InterestDeductions:
    """以利息給付日適用的規則計算兩項扣款。"""
    if isinstance(gross_minor, bool) or not isinstance(gross_minor, int) or gross_minor < 0:
        raise ValueError("gross_minor 必須是非負整數")

    withholding_rule = dataset.withholding_rule_on(on)
    withheld_tax = 0
    if withholding_rule is not None and rate_exceeds(
        gross_minor,
        withholding_rule.rate_ppm,
        withholding_rule.exempt_if_tax_at_most,
    ):
        withheld_tax = apply_rate(
            gross_minor, withholding_rule.rate_ppm, withholding_rule.rounding
        )

    premium_rule = dataset.premium_rule_on(on)
    premium = 0
    if premium_rule is not None and gross_minor >= premium_rule.threshold_at_least:
        premium = apply_rate(
            min(gross_minor, premium_rule.base_cap),
            premium_rule.rate_ppm,
            premium_rule.rounding,
        )

    return InterestDeductions(
        gross_minor=gross_minor,
        withheld_tax_minor=withheld_tax,
        nhi_premium_minor=premium,
        withholding_rule_found=withholding_rule is not None,
        premium_rule_found=premium_rule is not None,
    )
