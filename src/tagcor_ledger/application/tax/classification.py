"""帳戶類別與稅務所得／稅目之間的明確對應。"""

from __future__ import annotations

from tagcor_ledger.application.failures import STORE_FAILURES, failure
from tagcor_ledger.application.result import Result
from tagcor_ledger.application.tax.base import TaxServiceBase
from tagcor_ledger.domain.tax.kinds import Flow
from tagcor_ledger.domain.tax.records import TaxMappingRow


class TaxClassificationSection(TaxServiceBase):
    def mapping_rows(self, income_year: int) -> list[TaxMappingRow]:
        return self.store.list_tax_mapping_rows(income_year)

    def set_mapping(
        self, *, category_id: str, flow: Flow, tax_kind: str | None
    ) -> Result:
        try:
            self.store.set_tax_mapping(category_id=category_id, flow=flow, tax_kind=tax_kind)
            return Result.ok("所得歸類已儲存。")
        except STORE_FAILURES as exc:
            return failure(
                exc,
                fallback_code="TAX_MAPPING_SAVE_FAILED",
                fallback_message="所得歸類無法儲存。請匯出診斷資訊回報。",
            )
