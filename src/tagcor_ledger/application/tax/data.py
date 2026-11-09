"""稅務資料載入、新鮮度摘要與定存利息扣款試算。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from tagcor_ledger.application.tax.base import TaxServiceBase
from tagcor_ledger.domain.tax.dataset import TaxDataset, TaxSource
from tagcor_ledger.domain.tax.freshness import (
    DatasetLoad,
    DatasetLoadState,
    FreshnessProblem,
    assess_freshness,
    missing_exact_windows,
)
from tagcor_ledger.domain.tax.kinds import TaxKind
from tagcor_ledger.domain.tax.withholding import InterestDeductions, interest_deductions


@dataclass(frozen=True, slots=True)
class TaxDataStatus:
    path: Path
    load: DatasetLoad
    dataset: TaxDataset | None
    problems: tuple[FreshnessProblem, ...]
    sources: tuple[TaxSource, ...]
    reviewed_at: date | None
    next_review_on: date | None
    missing_windows: tuple[tuple[TaxKind, int], ...]
    law_oldest_reviewed_at: date | None


class TaxDataSection(TaxServiceBase):
    def dataset_load(self) -> DatasetLoad:
        return self._dataset_load()

    def freshness(self, *, today: date | None = None) -> tuple[FreshnessProblem, ...]:
        return assess_freshness(
            today=self._today(today),
            load=self._dataset_load(),
            law_oldest_reviewed_at=self.reference.oldest_reviewed_at(),
        )

    def data_status(self, *, today: date | None = None) -> TaxDataStatus:
        current = self._today(today)
        load = self._dataset_load()
        dataset = load.dataset if load.state is DatasetLoadState.OK else None
        law_reviewed = self.reference.oldest_reviewed_at()
        problems = assess_freshness(
            today=current,
            load=load,
            law_oldest_reviewed_at=law_reviewed,
        )
        switches = self.settings.get_tax_reminder_switches()
        active_kinds = tuple(kind for kind in TaxKind if switches[kind].value == "on")
        missing = (
            missing_exact_windows(dataset, today=current, kinds=active_kinds)
            if dataset is not None
            else ()
        )
        return TaxDataStatus(
            path=self.dataset_path,
            load=load,
            dataset=dataset,
            problems=problems,
            sources=dataset.sources if dataset is not None else (),
            reviewed_at=dataset.reviewed_at if dataset is not None else None,
            next_review_on=dataset.next_review_on if dataset is not None else None,
            missing_windows=missing,
            law_oldest_reviewed_at=law_reviewed,
        )

    def interest_deductions(self, gross_minor: int, *, on: date) -> InterestDeductions | None:
        dataset = self._usable_dataset()
        if dataset is None:
            return None
        return interest_deductions(gross_minor, on=on, dataset=dataset)
