"""合約／期／事件送給 UI 的 dict。

**這些是 UI 契約，不是領域模型。** 領域模型在 `domain/deposits.py`，那裡的
dataclass 不該為了畫面好顯示而多長欄位；反過來，這裡多一個「已顯示成中文的狀態」
也不代表領域多了一個概念。
"""

from __future__ import annotations

from tagcor_ledger.domain.deposits import (
    DEPOSIT_EVENT_TYPE_NAMES,
    DepositContract,
    DepositEvent,
    DepositEventType,
    DepositTerm,
)



def _contract_view(contract: DepositContract) -> dict[str, object]:
    return {
        "contract_id": contract.contract_id,
        "account_id": contract.account_id,
        "name": contract.name,
        "interest_method": contract.interest_method,
        "maturity_action": contract.maturity_action,
        "interest_destination_account_id": contract.interest_destination_account_id,
        "term_months": contract.term_months,
        "status": contract.status,
        "note": contract.note,
        "rate_type": contract.rate_type,
    }


def _term_view(term: DepositTerm) -> dict[str, object]:
    return {
        "term_id": term.term_id,
        "contract_id": term.contract_id,
        "sequence": term.sequence,
        "start_date": term.start_date,
        "maturity_date": term.maturity_date,
        "principal_minor": term.principal_minor,
        "annual_rate_ppm": term.annual_rate_ppm,
        "monthly_deposit_minor": term.monthly_deposit_minor,
        "actual_interest_minor": term.actual_interest_minor,
        "status": term.status,
        "note": term.note,
        "effective_rate_ppm": term.effective_rate_ppm,
    }


def _event_view(event: DepositEvent) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "term_id": event.term_id,
        "contract_id": event.contract_id,
        "contract_name": event.contract_name,
        "event_type": event.event_type,
        "event_type_name": DEPOSIT_EVENT_TYPE_NAMES.get(
            DepositEventType(event.event_type), event.event_type
        ),
        "due_date": event.due_date,
        "status": event.status,
        "suggested_amount_minor": event.suggested_amount_minor,
        "actual_amount_minor": event.actual_amount_minor,
        "transaction_id": event.transaction_id,
        "note": event.note,
    }
