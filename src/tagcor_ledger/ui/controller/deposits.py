"""定存：合約、期、待確認事件。

**待確認清單由 `overview.py` 組**，不是這一段自己知道要怎麼顯示。
v0.23.0 之前那裡還要跟定期收支合成一張表；現在只剩定存一個來源，但那條界線留著 ——
「待確認有什麼」是待確認頁的問題，「定存有什麼待處理」才是這一段的問題。
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

    def close_deposit_contract(self, contract_id: str) -> Result:
        return self.deposits.close_contract(contract_id)

    def delete_deposit_contract(self, contract_id: str) -> Result:
        return self.deposits.delete_contract(contract_id)

    def terminate_deposit_term(self, term_id: str, **values: Any) -> Result:
        return self.deposits.terminate_term(term_id, **values)

    def update_deposit_term(self, term_id: str, **values: Any) -> Result:
        return self.deposits.update_term(term_id, **values)

    def generate_deposit_events(self) -> Result:
        """把已經到期（與未來 7 天內到期）的定存事件放進待確認。

        **啟動時本來就會跑一次**（`ControllerBase._run_startup_tasks`），這裡是給
        「程式開著的時候剛建了一份合約」用的 —— 沒有它就要重開程式才看得到。
        重複按沒有副作用：`deposit_events` 有 `UNIQUE (term_id, event_type, due_date)`。

        v0.23.0 之前這件事混在 `controller.generate_due()` 裡跟定期收支一起做，
        而唯一的入口是定期收支頁那顆按鈕 —— 那一頁移除之後就沒有手動觸發了
        （[ADR-0011](../../../../docs/decisions/ADR-0011-drop-recurring-schedules.md)）。
        """
        return self.deposits.generate_due()

    def list_deposit_pending(self) -> list[dict[str, Any]]:
        return self._rows(self.deposits.list_pending(), "events")

    def confirm_deposit_event(
        self,
        event_id: str,
        *,
        actual_amount_minor: int | None = None,
        occurred_on: str | None = None,
    ) -> Result:
        """`occurred_on` 是交易日期（ISO 日期），不傳就用事件的到期日。"""
        return self.deposits.confirm(
            event_id, actual_amount_minor=actual_amount_minor, occurred_on=occurred_on
        )

    def skip_deposit_event(self, event_id: str) -> Result:
        return self.deposits.skip(event_id)
