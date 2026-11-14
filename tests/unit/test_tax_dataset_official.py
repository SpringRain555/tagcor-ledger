"""用財政部公布過的真數字，驗 `reference/tax/dataset.json` 與試算的算法（不是假資料）。

**這支測試明確指名** repo 裡真的 dataset —— 不經 App 的預設路徑（那條路在測試裡被 conftest 換成假資料，
見 `tests/conftest.py` 的 `fake_tax_dataset`）。只驗**已經公告、不會再變**的年度（114、115 年度），
之後每年補新年度不會讓它變紅；dataset 還是骨架時整支跳過。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tagcor_ledger.domain.tax.dataset import IncomeTaxParameters, TaxDataset
from tagcor_ledger.domain.tax.dataset_parse import parse_tax_dataset
from tagcor_ledger.domain.tax.estimate import progressive_tax

DATASET = Path(__file__).resolve().parents[2] / "reference" / "tax" / "dataset.json"


@pytest.fixture(scope="module")
def dataset() -> TaxDataset:
    parsed = parse_tax_dataset(json.loads(DATASET.read_text(encoding="utf-8")))
    if not parsed.populated:
        pytest.skip("reference/tax/dataset.json 還是骨架")
    return parsed


def _parameters(dataset: TaxDataset, year: int) -> IncomeTaxParameters:
    parameters = dataset.parameters_for(year)
    assert parameters is not None, f"dataset 沒有 {year} 年度的參數"
    return parameters


def test_the_tax_portal_example_for_114(dataset: TaxDataset) -> None:
    """財政部稅務入口網的計算例：綜合所得淨額 4,827,000 元，適用 30%、累進差額 413,700 元，
    應納稅額 1,034,400 元（113 至 114 年度的級距）。"""
    parameters = _parameters(dataset, 2025)

    assert progressive_tax(4_827_000, parameters.brackets, parameters.tax_rounding) == 1_034_400


@pytest.mark.parametrize(
    ("year", "cutoffs"),
    [
        (2025, (590_000, 1_330_000, 2_660_000, 4_980_000)),
        (2026, (610_000, 1_380_000, 2_770_000, 5_190_000)),
    ],
)
def test_published_brackets_do_not_jump_at_any_cutoff(
    dataset: TaxDataset, year: int, cutoffs: tuple[int, ...]
) -> None:
    """臺北國稅局公布的級距與累進差額：每個上限前後一元，稅額最多差 1 元（進位）、不會跳一大截。"""
    parameters = _parameters(dataset, year)
    for cutoff in cutoffs:
        below = progressive_tax(cutoff, parameters.brackets, parameters.tax_rounding)
        above = progressive_tax(cutoff + 1, parameters.brackets, parameters.tax_rounding)
        assert 0 <= above - below <= 1, (year, cutoff, below, above)


def test_the_115_announcement_says_a_renting_single_earner_at_644000_pays_nothing(
    dataset: TaxDataset,
) -> None:
    """財政部 115 年度公告：「租屋自住之單身上班族年薪 64.4 萬元……可免繳所得稅」。

    64.4 萬 ＝ 免稅額 ＋ 標準扣除額 ＋ 薪資所得特別扣除額 ＋ 房屋租金支出特別扣除額上限 18 萬
    （18 萬引自臺北國稅局的減免扣除頁；試算不支援房租扣除，這裡只拿它驗 dataset 的三個數字）。
    """
    parameters = _parameters(dataset, 2026)
    rent_deduction_cap = 180_000

    assert (
        parameters.exemption.value
        + parameters.standard_deduction_single.value
        + parameters.salary_special_deduction_cap.value
        + rent_deduction_cap
    ) == 644_000
