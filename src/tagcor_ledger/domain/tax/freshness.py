"""稅務資料載入狀態與新鮮度問題判斷。"""

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import Iterable

from tagcor_ledger.domain.tax.dataset import TaxDataset
from tagcor_ledger.domain.tax.kinds import TaxKind


class DatasetLoadState(StrEnum):
    """公開稅務資料集載入結果。"""

    OK = "ok"
    MISSING = "missing"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class DatasetLoad:
    state: DatasetLoadState
    dataset: TaxDataset | None = None
    problems: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """確認載入狀態、資料與錯誤清單彼此一致。"""
        if (self.state is DatasetLoadState.OK) != (self.dataset is not None):
            raise ValueError("ok 狀態必須且只能搭配 dataset")
        if self.state is DatasetLoadState.INVALID:
            if not self.problems:
                raise ValueError("invalid 狀態必須帶有問題清單")
        elif self.problems:
            raise ValueError("非 invalid 狀態不得帶有問題清單")


class FreshnessIssue(StrEnum):
    """新鮮度問題及其優先順序。"""

    DATASET_MISSING = "dataset_missing"
    DATASET_INVALID = "dataset_invalid"
    NOT_POPULATED = "not_populated"
    PARAMETERS_MISSING = "parameters_missing"
    REVIEW_DUE = "review_due"
    LAW_REVIEW_DUE = "law_review_due"


BLOCKING_ISSUES = (
    FreshnessIssue.DATASET_MISSING,
    FreshnessIssue.DATASET_INVALID,
    FreshnessIssue.NOT_POPULATED,
)


@dataclass(frozen=True, slots=True)
class FreshnessProblem:
    issue: FreshnessIssue
    years: tuple[int, ...] = ()
    due_on: date | None = None
    details: tuple[str, ...] = ()


def required_parameter_years(today: date) -> tuple[int, ...]:
    """回傳目前應備妥的所得年度參數。"""
    years = (today.year - 1, today.year)
    if (today.month, today.day) >= (12, 15):
        return (*years, today.year + 1)
    return years


def required_basic_living_years(today: date) -> tuple[int, ...]:
    """回傳依基本生活費公告時程目前應備妥的所得年度。"""
    years = (today.year - 1,)
    if (today.month, today.day) >= (12, 15):
        return (*years, today.year)
    return years


def assess_freshness(
    *,
    today: date,
    load: DatasetLoad,
    law_oldest_reviewed_at: date | None,
) -> tuple[FreshnessProblem, ...]:
    """依優先順序回傳今天所有成立的新鮮度問題。"""
    if load.state is DatasetLoadState.MISSING:
        return (FreshnessProblem(FreshnessIssue.DATASET_MISSING),)
    if load.state is DatasetLoadState.INVALID:
        return (
            FreshnessProblem(
                FreshnessIssue.DATASET_INVALID,
                details=load.problems,
            ),
        )
    dataset = load.dataset
    if dataset is None:
        raise ValueError("ok 狀態必須包含 dataset")
    if dataset.reviewed_at is None:
        return (FreshnessProblem(FreshnessIssue.NOT_POPULATED),)

    missing_parameter_years = {
        year for year in required_parameter_years(today) if dataset.parameters_for(year) is None
    }
    missing_basic_living_years = {
        year
        for year in required_basic_living_years(today)
        if dataset.basic_living_for(year) is None
    }
    missing_years = tuple(sorted(missing_parameter_years | missing_basic_living_years))
    problems: list[FreshnessProblem] = []
    if missing_years:
        problems.append(
            FreshnessProblem(
                FreshnessIssue.PARAMETERS_MISSING,
                years=missing_years,
            )
        )
    if dataset.next_review_on is not None and today >= dataset.next_review_on:
        problems.append(
            FreshnessProblem(
                FreshnessIssue.REVIEW_DUE,
                due_on=dataset.next_review_on,
            )
        )

    if law_oldest_reviewed_at is not None:
        income_window = dataset.window_for(TaxKind.INCOME_TAX, today.year)
        if income_window is not None:
            within_review_period = (
                income_window.start - timedelta(days=30)
                <= today
                <= income_window.end
            )
            if (
                within_review_period
                and law_oldest_reviewed_at < date(today.year, 1, 1)
            ):
                problems.append(FreshnessProblem(FreshnessIssue.LAW_REVIEW_DUE))
    priority = {issue: index for index, issue in enumerate(FreshnessIssue)}
    return tuple(sorted(problems, key=lambda item: priority[item.issue]))


def missing_exact_windows(
    dataset: TaxDataset,
    *,
    today: date,
    kinds: Iterable[TaxKind],
) -> tuple[tuple[TaxKind, int], ...]:
    """列出今年與明年沒有公告期間、只能採用預估的稅目。"""
    ordered_kinds = tuple(dict.fromkeys(kinds))
    return tuple(
        (kind, year)
        for year in (today.year, today.year + 1)
        for kind in ordered_kinds
        if kind not in dataset.years.get(year, {})
    )
