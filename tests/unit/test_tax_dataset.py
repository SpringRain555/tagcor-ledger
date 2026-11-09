"""稅務資料集的驗證、解析與查詢行為。"""

import copy
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from tagcor_ledger.domain.tax.arithmetic import Rounding
from tagcor_ledger.domain.tax.dataset_parse import (
    TaxDatasetInvalid,
    parse_tax_dataset,
)
from tagcor_ledger.domain.tax.dataset_validate import validate_tax_dataset
from tagcor_ledger.domain.tax.kinds import TaxKind


FIXTURE = Path(__file__).parents[1] / "fixtures" / "tax" / "sample.json"


@pytest.fixture
def sample_raw() -> dict[str, object]:
    return cast(dict[str, object], json.loads(FIXTURE.read_text(encoding="utf-8")))


def _set(raw: dict[str, object], path: tuple[str | int, ...], value: object) -> None:
    current: object = raw
    for key in path[:-1]:
        if isinstance(current, dict):
            current = current[cast(str, key)]
        else:
            current = cast(list[object], current)[cast(int, key)]
    last = path[-1]
    if isinstance(current, dict):
        current[cast(str, last)] = value
    else:
        cast(list[object], current)[cast(int, last)] = value


def _skeleton() -> dict[str, object]:
    return {
        "schema_version": 1,
        "reviewed_at": None,
        "next_review_on": None,
        "notes": [],
        "sources": [],
        "calendar": {"typical": {}, "years": {}},
        "income_tax": {},
        "basic_living_expense": {},
        "interest_withholding": [],
        "nhi_supplementary_premium": [],
    }


@pytest.mark.parametrize(
    ("path", "value", "expected"),
    [
        (("schema_version",), 2, "schema_version："),
        (("reviewed_at",), "2026-02-30", "reviewed_at："),
        (
            ("reviewed_at",),
            "2027-01-01",
            "next_review_on：已複查的資料要寫下次複查日，而且要晚於 reviewed_at。",
        ),
        (
            ("next_review_on",),
            None,
            "next_review_on：已複查的資料要寫下次複查日，而且要晚於 reviewed_at。",
        ),
        (
            ("next_review_on",),
            "2026-11-01",
            "next_review_on：已複查的資料要寫下次複查日，而且要晚於 reviewed_at。",
        ),
        (("sources", 0, "id"), "bad_id", "sources[0].id："),
        (("sources", 1, "id"), "calendar-example", "sources[1].id：來源識別字重複"),
        (("sources", 0, "url"), "http://example.invalid/calendar", "sources[0].url："),
        (("sources", 0, "sha256"), "ABC", "sources[0].sha256："),
        (("calendar", "typical", "income_tax", "source_ids"), ["missing-source"], "source_ids[0]："),
        (("calendar", "typical", "income_tax", "source_ids"), [], "source_ids："),
        (("calendar", "typical", "income_tax", "start"), "02-30", "income_tax.start："),
        (("calendar", "typical", "income_tax", "start"), "06-01", "開始日期不可晚於結束日期。"),
        (("calendar", "years", "2026", "income_tax", "end"), "2027-01-01", "income_tax.end："),
        (("income_tax", "2025", "exemption", "value"), True, "exemption.value："),
        (("income_tax", "2025", "exemption", "value"), -1, "exemption.value："),
        (("income_tax", "2025", "exemption", "value"), Decimal("1.25"), "exemption.value："),
        (("basic_living_expense", "2025", "value"), True, "basic_living_expense.2025.value："),
        (("basic_living_expense", "2025", "value"), -1, "basic_living_expense.2025.value：不得小於 0。"),
        (("basic_living_expense", "2025", "source_ids"), [], "basic_living_expense.2025.source_ids：至少要引用一個來源。"),
        (("income_tax", "2025", "exemption_70_plus", "value"), 99_999, "exemption_70_plus.value："),
        (("income_tax", "2025", "brackets", "rows"), [
            {"up_to": 590000, "rate_ppm": 50000, "progressive_difference": 0}
        ], "brackets.rows："),
        (("income_tax", "2025", "brackets", "rows", 1, "up_to"), 500000, "rows[1].up_to："),
        (("income_tax", "2025", "brackets", "rows", 4, "up_to"), 6000000, "rows[4].up_to："),
        (("income_tax", "2025", "brackets", "rows", 1, "rate_ppm"), 50000, "rows[1].rate_ppm："),
        (
            ("income_tax", "2025", "brackets", "rows", 0, "rate_ppm"),
            0,
            "rate_ppm：比率必須大於 0、小於 1000000（100%）。",
        ),
        (
            ("interest_withholding", 0, "rate_ppm"),
            1_000_000,
            "interest_withholding[0].rate_ppm：比率必須大於 0、小於 1000000（100%）。",
        ),
        (
            ("nhi_supplementary_premium", 0, "rate_ppm"),
            0,
            "nhi_supplementary_premium[0].rate_ppm：比率必須大於 0、小於 1000000（100%）。",
        ),
        (("income_tax", "2025", "brackets", "rows", 0, "progressive_difference"), 1, "rows[0].progressive_difference："),
        (("income_tax", "2025", "brackets", "rows", 2, "progressive_difference"), 147000, "rows[2].progressive_difference："),
        (("interest_withholding", 0, "rounding"), "ceil", "interest_withholding[0].rounding："),
        (("nhi_supplementary_premium", 0, "base_cap"), 20000, "nhi_supplementary_premium[0].base_cap："),
    ],
)
def test_each_dataset_rule_rejects_a_targeted_bad_value(
    sample_raw: dict[str, object],
    path: tuple[str | int, ...],
    value: object,
    expected: str,
) -> None:
    changed = copy.deepcopy(sample_raw)
    _set(changed, path, value)

    problems = validate_tax_dataset(changed)

    assert any(expected in problem for problem in problems), problems


def test_fixture_is_valid_and_parses_into_dataset(sample_raw: dict[str, object]) -> None:
    assert validate_tax_dataset(sample_raw) == []

    dataset = parse_tax_dataset(sample_raw)

    assert dataset.populated
    assert len(dataset.typical) == 5
    assert len(dataset.sources) == 3
    assert dataset.parameters_for(2025) is not None
    assert dataset.parameters_for(2025).brackets[2].progressive_difference == 147700
    assert dataset.basic_living_for(2025) is not None
    assert dataset.basic_living_for(2025).value == 500000
    assert dataset.basic_living_for(2040) is None
    assert dataset.source("income-example") is not None


def test_empty_skeleton_is_valid_and_not_populated() -> None:
    raw = _skeleton()

    assert validate_tax_dataset(raw) == []
    dataset = parse_tax_dataset(raw)
    assert not dataset.populated
    assert dataset.reviewed_at is None


def test_parser_raises_stable_error_code_and_keeps_problems(sample_raw: dict[str, object]) -> None:
    _set(sample_raw, ("schema_version",), 9)

    with pytest.raises(TaxDatasetInvalid) as caught:
        parse_tax_dataset(sample_raw)

    assert str(caught.value) == "TAX_DATASET_INVALID"
    assert caught.value.problems
    assert any("schema_version" in problem for problem in caught.value.problems)


def test_unreferenced_source_is_reported(sample_raw: dict[str, object]) -> None:
    sources = cast(list[object], sample_raw["sources"])
    sources.append(
        {
            "id": "unused-example",
            "title": "未引用的測試來源",
            "publisher": "測試資料",
            "url": "https://example.invalid/unused",
            "published_on": None,
            "sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
            "fetched_at": "2026-01-04T00:00:00Z",
        }
    )

    problems = validate_tax_dataset(sample_raw)

    assert any("sources[3].id：來源「unused-example」沒有被引用" in problem for problem in problems)


def test_unknown_tax_kind_is_rejected(sample_raw: dict[str, object]) -> None:
    typical = cast(dict[str, object], cast(dict[str, object], sample_raw["calendar"])["typical"])
    typical["mystery_tax"] = copy.deepcopy(typical["income_tax"])

    problems = validate_tax_dataset(sample_raw)

    assert any("calendar.typical.mystery_tax：未知稅目" in problem for problem in problems)


def test_calendar_year_key_must_be_four_digits(sample_raw: dict[str, object]) -> None:
    years = cast(dict[str, object], cast(dict[str, object], sample_raw["calendar"])["years"])
    years["26"] = years.pop("2026")

    problems = validate_tax_dataset(sample_raw)

    assert any("calendar.years.26：年度鍵必須是四位數" in problem for problem in problems)


def test_basic_living_year_key_must_be_four_digits(sample_raw: dict[str, object]) -> None:
    years = cast(dict[str, object], sample_raw["basic_living_expense"])
    years["25"] = years.pop("2025")

    problems = validate_tax_dataset(sample_raw)

    assert any(
        "basic_living_expense.25：所得年度鍵必須是四位數西元年。" in problem
        for problem in problems
    )


def test_basic_living_expense_is_required_but_may_be_empty(
    sample_raw: dict[str, object],
) -> None:
    sample_raw["basic_living_expense"] = {}
    assert validate_tax_dataset(sample_raw) == []

    del sample_raw["basic_living_expense"]
    problems = validate_tax_dataset(sample_raw)
    assert any(
        "dataset.basic_living_expense：缺少必要欄位。" in problem
        for problem in problems
    )


def test_income_tax_rejects_nested_basic_living_expense(
    sample_raw: dict[str, object],
) -> None:
    parameters = cast(dict[str, object], cast(dict[str, object], sample_raw["income_tax"])["2025"])
    parameters["basic_living_expense"] = {
        "value": 500000,
        "source_ids": ["income-example"],
    }

    problems = validate_tax_dataset(sample_raw)

    assert any(
        "income_tax.2025.basic_living_expense：應移至最上層 basic_living_expense 序列。"
        in problem
        for problem in problems
    )


def test_rule_effective_dates_must_increase(sample_raw: dict[str, object]) -> None:
    rules = cast(list[object], sample_raw["interest_withholding"])
    earlier = copy.deepcopy(cast(dict[str, object], rules[0]))
    earlier["effective_from"] = "2009-01-01"
    rules.append(earlier)

    problems = validate_tax_dataset(sample_raw)

    assert any("interest_withholding[1].effective_from：生效日必須嚴格遞增" in problem for problem in problems)


def test_window_for_prefers_published_window_and_falls_back_to_typical(
    sample_raw: dict[str, object],
) -> None:
    dataset = parse_tax_dataset(sample_raw)

    published = dataset.window_for(TaxKind.INCOME_TAX, 2026)
    typical = dataset.window_for(TaxKind.LAND_VALUE_TAX, 2027)

    assert published is not None
    assert published.start == date(2026, 5, 1)
    assert published.end == date(2026, 6, 1)
    assert published.note == "測試用期間順延說明"
    assert not published.estimated
    assert typical is not None
    assert typical.start == date(2027, 11, 1)
    assert typical.end == date(2027, 11, 30)
    assert typical.estimated


def test_window_for_returns_none_without_a_published_or_typical_window() -> None:
    dataset = parse_tax_dataset(_skeleton())

    assert dataset.window_for(TaxKind.INCOME_TAX, 2026) is None


def test_parameters_for_returns_only_requested_income_year(sample_raw: dict[str, object]) -> None:
    dataset = parse_tax_dataset(sample_raw)

    assert dataset.parameters_for(2025) is not None
    assert dataset.parameters_for(2040) is None


def test_rule_lookup_returns_none_before_first_effective_date_and_latest_rule(
    sample_raw: dict[str, object],
) -> None:
    withholding = cast(list[object], sample_raw["interest_withholding"])
    withholding.append(
        {
            "effective_from": "2025-01-01",
            "rate_ppm": 90000,
            "exempt_if_tax_at_most": 3000,
            "rounding": "half_up",
            "source_ids": ["rules-example"],
        }
    )
    premiums = cast(list[object], sample_raw["nhi_supplementary_premium"])
    premiums.append(
        {
            "effective_from": "2025-01-01",
            "rate_ppm": 30000,
            "threshold_at_least": 25000,
            "base_cap": 20000000,
            "rounding": "floor",
            "source_ids": ["rules-example"],
        }
    )
    dataset = parse_tax_dataset(sample_raw)

    assert dataset.withholding_rule_on(date(2009, 12, 31)) is None
    assert dataset.withholding_rule_on(date(2025, 1, 1)) == dataset.interest_withholding[1]
    assert dataset.premium_rule_on(date(2020, 12, 31)) is None
    assert dataset.premium_rule_on(date(2025, 1, 1)) == dataset.nhi_supplementary_premium[1]


def test_dataset_mappings_are_immutable_after_parsing(sample_raw: dict[str, object]) -> None:
    dataset = parse_tax_dataset(sample_raw)

    with pytest.raises(TypeError):
        dataset.typical[TaxKind.INCOME_TAX] = dataset.typical[TaxKind.HOUSE_TAX]
    with pytest.raises(TypeError):
        dataset.basic_living_expense[2025] = dataset.basic_living_expense[2026]


def test_rounding_model_contains_the_supported_values() -> None:
    assert tuple(Rounding) == (Rounding.FLOOR, Rounding.HALF_UP)
