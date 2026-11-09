"""存款利息依日期套用扣繳與補充保費規則。"""

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from tagcor_ledger.domain.tax.arithmetic import Rounding
from tagcor_ledger.domain.tax.dataset_parse import parse_tax_dataset
from tagcor_ledger.domain.tax.withholding import interest_deductions


@pytest.fixture
def dataset():
    path = Path(__file__).parents[1] / "fixtures" / "tax" / "sample.json"
    return parse_tax_dataset(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    ("gross", "withheld", "premium"),
    [(19_999, 0, 0), (20_000, 0, 422), (20_001, 2_000, 422)],
)
def test_interest_deductions_match_tax_rule_boundaries(
    dataset, gross: int, withheld: int, premium: int
) -> None:
    result = interest_deductions(gross, on=date(2026, 11, 9), dataset=dataset)
    assert (result.withheld_tax_minor, result.nhi_premium_minor) == (withheld, premium)
    assert result.withholding_rule_found
    assert result.premium_rule_found


def test_interest_deductions_apply_half_up_rounding(dataset) -> None:
    floor_result = interest_deductions(20_005, on=date(2026, 11, 9), dataset=dataset)
    rule = replace(dataset.interest_withholding[0], rounding=Rounding.HALF_UP)
    half_up_dataset = replace(dataset, interest_withholding=(rule,))

    result = interest_deductions(20_005, on=date(2026, 11, 9), dataset=half_up_dataset)

    assert floor_result.withheld_tax_minor == 2_000
    assert result.withheld_tax_minor == 2_001


def test_interest_deductions_apply_base_cap_and_net_amount(dataset) -> None:
    result = interest_deductions(12_000_000, on=date(2026, 11, 9), dataset=dataset)

    assert result.withheld_tax_minor == 1_200_000
    assert result.nhi_premium_minor == 211_000
    assert result.net_minor == 10_589_000


def test_interest_deductions_report_when_no_rules_are_effective(dataset) -> None:
    result = interest_deductions(20_001, on=date(2000, 1, 1), dataset=dataset)

    assert not result.withholding_rule_found
    assert not result.premium_rule_found
    assert result.withheld_tax_minor == 0
    assert result.nhi_premium_minor == 0
    assert result.net_minor == 20_001


def test_interest_deductions_reject_negative_gross_amount(dataset) -> None:
    with pytest.raises(ValueError):
        interest_deductions(-1, on=date(2026, 11, 9), dataset=dataset)
