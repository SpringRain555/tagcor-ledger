"""定存：合約、期、待確認事件。

**與 `automation.py` 分開**，雖然兩邊的待確認項目在畫面上合成一張表 ——
合併那件事是 `overview.py` 做的，不是這兩段各自要知道的。
"""

from __future__ import annotations

from typing import Any

from tagcor_ledger.application.result import Result
from tagcor_ledger.ui.controller.wiring import ControllerBase


class DepositSection(ControllerBase):
    def list_deposit_contracts(self, *, include_closed: bool = False) -> list[dict[str, Any]]:
        return self._rows(self.deposits.list_contracts(include_closed=include_closed), "contracts")

    def list_deposit_terms(self, contract_id: str | None = None) -> list[dict[str, Any]]:
        return self._rows(self.deposits.list_terms(contract_id), "terms")

    def create_deposit_contract(self, **values: Any) -> Result:
        return self.deposits.create_contract(**values)

    def update_deposit_contract(self, contract_id: str, **values: Any) -> Result:
        return self.deposits.update_contract(contract_id, **values)

    def delete_deposit_contract(self, contract_id: str) -> Result:
        return self.deposits.delete_contract(contract_id)

    def update_deposit_term(self, term_id: str, **values: Any) -> Result:
        return self.deposits.update_term(term_id, **values)

    def list_deposit_pending(self) -> list[dict[str, Any]]:
        return self._rows(self.deposits.list_pending(), "events")

    def confirm_deposit_event(
        self, event_id: str, *, actual_amount_minor: int | None = None
    ) -> Result:
        return self.deposits.confirm(event_id, actual_amount_minor=actual_amount_minor)

    def skip_deposit_event(self, event_id: str) -> Result:
        return self.deposits.skip(event_id)
