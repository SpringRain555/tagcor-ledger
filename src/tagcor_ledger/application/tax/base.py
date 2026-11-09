"""`TaxService` 各 section 共用的資料、設定與日期來源。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.application.reference import ReferenceLibrary
from tagcor_ledger.application.settings import SettingsService
from tagcor_ledger.application.tax.loader import (
    dataset_stat_signature,
    default_tax_dataset_path,
    load_tax_dataset,
)
from tagcor_ledger.domain.tax.dataset import TaxDataset
from tagcor_ledger.domain.tax.freshness import DatasetLoad, DatasetLoadState
from tagcor_ledger.infrastructure.clock import today_taipei
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


class TaxServiceBase:
    def __init__(
        self,
        paths: AppPaths,
        store: LedgerStore | None = None,
        *,
        dataset_path: Path | None = None,
        reference: ReferenceLibrary | None = None,
        settings: SettingsService | None = None,
    ) -> None:
        self.paths = paths
        self.store = store or LedgerStore(paths)
        self.dataset_path = dataset_path or default_tax_dataset_path()
        self.reference = reference or ReferenceLibrary()
        self.settings = settings or SettingsService(paths)
        self._dataset_cache_key: tuple[Path, int | None, int | None] | None = None
        self._dataset_cache: DatasetLoad | None = None

    def _dataset_load(self) -> DatasetLoad:
        key = dataset_stat_signature(self.dataset_path)
        if key != self._dataset_cache_key or self._dataset_cache is None:
            self._dataset_cache = load_tax_dataset(self.dataset_path)
            self._dataset_cache_key = key
        return self._dataset_cache

    def _usable_dataset(self) -> TaxDataset | None:
        load = self._dataset_load()
        if load.state is not DatasetLoadState.OK or load.dataset is None:
            return None
        if not load.dataset.populated:
            return None
        return load.dataset

    @staticmethod
    def _today(today: date | None) -> date:
        return today if today is not None else today_taipei()
