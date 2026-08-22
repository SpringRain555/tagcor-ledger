"""到期與每月領息的待確認項目怎麼長出來。

**只產生待確認項目，不入帳。** 成為交易一定要經過使用者按下確認，
見套件 docstring 的第一條。
"""

from __future__ import annotations

from tagcor_ledger.application.deposits.base import MATURITY_LEAD_DAYS, DepositServiceBase
from tagcor_ledger.application.deposits.views import _event_view
from tagcor_ledger.application.failures import STORE_FAILURES, failure
from tagcor_ledger.application.result import Result
from tagcor_ledger.domain.deposits import (
    DepositContract,
    DepositEventType,
    DepositTerm,
    InterestMethod,
    suggest_interest_minor,
    suggest_monthly_interest_minor,
)
from tagcor_ledger.domain.dates import monthly_dates, shift_days
from tagcor_ledger.infrastructure.clock import today_taipei


class EventSection(DepositServiceBase):
    # --- 產生待確認 ---------------------------------------------------------

    def generate_due(self, today: str | None = None) -> Result:
        """把已到期或即將到期的事件放進待確認。**不建立任何交易。**

        可以重複按 —— `deposit_events` 有 `UNIQUE (term_id, event_type, due_date)`，
        同一件事只會出現一次。
        """
        current = today or today_taipei().isoformat()
        horizon = shift_days(current, MATURITY_LEAD_DAYS)
        generated = 0
        try:
            for term in self.store.list_active_terms():
                contract = self.store.get_contract(term.contract_id)
                generated += self._generate_for_term(contract, term, current, horizon)
        except STORE_FAILURES as exc:
            return failure(
                exc,
                fallback_code="DEPOSIT_GENERATE_FAILED",
                fallback_message="定存待確認項目無法產生。請匯出診斷資訊回報。",
            )
        return Result.ok(
            f"已產生 {generated} 件定存待確認項目。", details={"generated": generated}
        )

    def _generate_for_term(
        self, contract: DepositContract, term: DepositTerm, today: str, horizon: str
    ) -> int:
        generated = 0
        method = InterestMethod(contract.interest_method)

        if method is InterestMethod.MONTHLY_INTEREST:
            suggested = suggest_monthly_interest_minor(
                principal_minor=term.principal_minor, annual_rate_ppm=term.annual_rate_ppm
            )
            for due in monthly_dates(term.start_date, term.maturity_date, today):
                if self.store.add_event(
                    term_id=term.term_id,
                    event_type=str(DepositEventType.INTEREST_PAYOUT),
                    due_date=due,
                    suggested_amount_minor=suggested,
                    note=f"{contract.name} 每月利息",
                ):
                    generated += 1

        if method is InterestMethod.INSTALLMENT_SAVINGS:
            for due in monthly_dates(term.start_date, term.maturity_date, today):
                if self.store.add_event(
                    term_id=term.term_id,
                    event_type=str(DepositEventType.INSTALLMENT),
                    due_date=due,
                    suggested_amount_minor=term.monthly_deposit_minor,
                    note=f"{contract.name} 每月存入",
                ):
                    generated += 1

        # 到期提前 MATURITY_LEAD_DAYS 天出現，「不自動轉存」才來得及處理。
        if term.maturity_date <= horizon:
            interest = suggest_interest_minor(
                interest_method=contract.interest_method,
                principal_minor=term.principal_minor,
                annual_rate_ppm=term.annual_rate_ppm,
                term_months=contract.term_months,
                monthly_deposit_minor=term.monthly_deposit_minor,
            )
            if self.store.add_event(
                term_id=term.term_id,
                event_type=str(DepositEventType.MATURITY),
                due_date=term.maturity_date,
                suggested_amount_minor=interest,
                note=f"{contract.name} 到期",
            ):
                generated += 1
        return generated

    def list_pending(self) -> Result:
        events = self.store.list_pending_events()
        return Result.ok(details={"events": [_event_view(item) for item in events]})
