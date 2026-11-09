"""將已驗證的公開稅務資料轉成不可變領域模型。"""

from __future__ import annotations

from datetime import date
from typing import Mapping, cast

from tagcor_ledger.domain.tax.arithmetic import Rounding
from tagcor_ledger.domain.tax.dataset import (
    Bracket,
    IncomeTaxParameters,
    InterestWithholdingRule,
    NhiPremiumRule,
    SourcedAmount,
    TaxDataset,
    TaxSource,
    TypicalWindow,
    Window,
)
from tagcor_ledger.domain.tax.dataset_validate import validate_tax_dataset
from tagcor_ledger.domain.tax.kinds import TaxKind


class TaxDatasetInvalid(ValueError):
    """驗證未通過的稅務資料集與完整問題清單。"""

    def __init__(self, problems: tuple[str, ...]) -> None:
        super().__init__("TAX_DATASET_INVALID")
        self.problems = problems

    def __str__(self) -> str:
        return "TAX_DATASET_INVALID"


def _obj(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value)


def _ids(obj: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(cast(list[str], obj["source_ids"]))


def _amount(value: object) -> SourcedAmount:
    obj = _obj(value)
    return SourcedAmount(cast(int, obj["value"]), _ids(obj))


def _window(kind: TaxKind, year: int, raw: object) -> Window:
    obj = _obj(raw)
    return Window(
        kind=kind,
        year=year,
        start=date.fromisoformat(cast(str, obj["start"])),
        end=date.fromisoformat(cast(str, obj["end"])),
        estimated=False,
        note=cast(str | None, obj["note"]),
        source_ids=_ids(obj),
    )


def _parameters(year: int, raw: object) -> IncomeTaxParameters:
    obj = _obj(raw)
    brackets_obj = _obj(obj["brackets"])
    rows = cast(list[object], brackets_obj["rows"])
    brackets = tuple(
        Bracket(
            up_to=cast(int | None, _obj(row)["up_to"]),
            rate_ppm=cast(int, _obj(row)["rate_ppm"]),
            progressive_difference=cast(int, _obj(row)["progressive_difference"]),
        )
        for row in rows
    )
    rounding_obj = _obj(obj["tax_rounding"])
    return IncomeTaxParameters(
        income_year=year,
        exemption=_amount(obj["exemption"]),
        exemption_70_plus=_amount(obj["exemption_70_plus"]),
        standard_deduction_single=_amount(obj["standard_deduction_single"]),
        salary_special_deduction_cap=_amount(obj["salary_special_deduction_cap"]),
        savings_investment_cap=_amount(obj["savings_investment_cap"]),
        writing_lecture_exemption_cap=_amount(obj["writing_lecture_exemption_cap"]),
        foreign_income_amt_threshold=_amount(obj["foreign_income_amt_threshold"]),
        amt_basic_exemption=_amount(obj["amt_basic_exemption"]),
        brackets=brackets,
        brackets_source_ids=_ids(brackets_obj),
        tax_rounding=Rounding(cast(str, rounding_obj["value"])),
        tax_rounding_source_ids=_ids(rounding_obj),
    )


def _withholding_rule(raw: object) -> InterestWithholdingRule:
    obj = _obj(raw)
    return InterestWithholdingRule(
        effective_from=date.fromisoformat(cast(str, obj["effective_from"])),
        rate_ppm=cast(int, obj["rate_ppm"]),
        exempt_if_tax_at_most=cast(int, obj["exempt_if_tax_at_most"]),
        rounding=Rounding(cast(str, obj["rounding"])),
        source_ids=cast(tuple[str, ...], tuple(cast(list[str], obj["source_ids"]))),
    )


def _premium_rule(raw: object) -> NhiPremiumRule:
    obj = _obj(raw)
    return NhiPremiumRule(
        effective_from=date.fromisoformat(cast(str, obj["effective_from"])),
        rate_ppm=cast(int, obj["rate_ppm"]),
        threshold_at_least=cast(int, obj["threshold_at_least"]),
        base_cap=cast(int, obj["base_cap"]),
        rounding=Rounding(cast(str, obj["rounding"])),
        source_ids=tuple(cast(list[str], obj["source_ids"])),
    )


def parse_tax_dataset(raw: object) -> TaxDataset:
    """先完整驗證資料集，再轉為領域模型。"""
    problems = validate_tax_dataset(raw)
    if problems:
        raise TaxDatasetInvalid(tuple(problems))
    root = _obj(raw)
    sources = tuple(
        TaxSource(
            id=cast(str, _obj(item)["id"]),
            title=cast(str, _obj(item)["title"]),
            publisher=cast(str, _obj(item)["publisher"]),
            url=cast(str, _obj(item)["url"]),
            published_on=(
                date.fromisoformat(cast(str, _obj(item)["published_on"]))
                if _obj(item)["published_on"] is not None
                else None
            ),
            sha256=cast(str, _obj(item)["sha256"]),
            fetched_at=cast(str, _obj(item)["fetched_at"]),
        )
        for item in cast(list[object], root["sources"])
    )
    calendar = _obj(root["calendar"])
    typical: dict[TaxKind, TypicalWindow] = {}
    for raw_kind, item in _obj(calendar["typical"]).items():
        kind = TaxKind(raw_kind)
        window = _obj(item)
        start_month, start_day = (int(part) for part in cast(str, window["start"]).split("-"))
        end_month, end_day = (int(part) for part in cast(str, window["end"]).split("-"))
        typical[kind] = TypicalWindow(
            kind=kind,
            start_month=start_month,
            start_day=start_day,
            end_month=end_month,
            end_day=end_day,
            basis=cast(str, window["basis"]),
            source_ids=_ids(window),
        )
    years: dict[int, dict[TaxKind, Window]] = {}
    for raw_year, windows in _obj(calendar["years"]).items():
        year = int(raw_year)
        years[year] = {
            TaxKind(raw_kind): _window(TaxKind(raw_kind), year, item)
            for raw_kind, item in _obj(windows).items()
        }
    income_tax = {
        int(raw_year): _parameters(int(raw_year), parameters)
        for raw_year, parameters in _obj(root["income_tax"]).items()
    }
    basic_living_expense = {
        int(raw_year): _amount(amount)
        for raw_year, amount in _obj(root["basic_living_expense"]).items()
    }
    withholding = tuple(
        _withholding_rule(item) for item in cast(list[object], root["interest_withholding"])
    )
    premium = tuple(
        _premium_rule(item) for item in cast(list[object], root["nhi_supplementary_premium"])
    )
    return TaxDataset(
        schema_version=cast(int, root["schema_version"]),
        reviewed_at=(
            date.fromisoformat(cast(str, root["reviewed_at"]))
            if root["reviewed_at"] is not None
            else None
        ),
        next_review_on=(
            date.fromisoformat(cast(str, root["next_review_on"]))
            if root["next_review_on"] is not None
            else None
        ),
        notes=tuple(cast(list[str], root["notes"])),
        sources=sources,
        typical=typical,
        years=years,
        income_tax=income_tax,
        basic_living_expense=basic_living_expense,
        interest_withholding=withholding,
        nhi_supplementary_premium=premium,
    )
