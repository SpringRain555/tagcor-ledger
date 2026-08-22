"""確認一件事件會產生哪幾筆交易，以及確認之後這一期怎麼走。

「哪幾筆」由 `plan_postings()` 算出來（純函式性質，好測），
「真的寫進去」由 `_write_postings()` 做。分開是為了讓
`tests/integration/test_deposits.py` 能在不寫入的情況下斷言規劃結果。
"""

from __future__ import annotations

from uuid import uuid4

from tagcor_ledger.application.deposits.base import DepositPosting, DepositServiceBase
from tagcor_ledger.application.failures import STORE_FAILURES, failure
from tagcor_ledger.application.result import Result, new_correlation_id
from tagcor_ledger.domain.deposits import (
    DepositEvent,
    DepositEventStatus,
    DepositEventType,
    DepositTermStatus,
    derive_annual_rate_ppm,
    interest_goes_to_deposit_account,
    maturity_returns_principal,
    renewed_principal_minor,
)
from tagcor_ledger.domain.dates import add_months
from tagcor_ledger.domain.money import Money
from tagcor_ledger.infrastructure.clock import today_taipei


class PostingSection(DepositServiceBase):
    # --- 確認入帳 -----------------------------------------------------------

    def plan_postings(self, event: DepositEvent, amount_minor: int) -> list[DepositPosting]:
        """算出確認這件事會產生哪些交易。**純函式，不寫入任何東西。**

        單獨拆出來是為了讓 UI 可以先給使用者看「按下去會發生什麼」，
        也讓 12 種組合可以逐一測試而不必真的入帳。
        """
        term = self.store.get_term(event.term_id)
        contract = self.store.get_contract(event.contract_id)
        destination = contract.interest_destination_account_id
        event_type = DepositEventType(event.event_type)

        if event_type is DepositEventType.INTEREST_PAYOUT:
            return [
                DepositPosting(
                    entry_type="income",
                    amount_minor=amount_minor,
                    account_id=destination or contract.account_id,
                    destination_account_id=None,
                    description=f"{contract.name} 利息",
                )
            ]

        if event_type is DepositEventType.INSTALLMENT:
            return [
                DepositPosting(
                    entry_type="transfer",
                    amount_minor=amount_minor,
                    account_id=destination or contract.account_id,
                    destination_account_id=contract.account_id,
                    description=f"{contract.name} 每月存入",
                )
            ]

        postings: list[DepositPosting] = []
        if amount_minor > 0:
            interest_account = (
                contract.account_id
                if interest_goes_to_deposit_account(contract.maturity_action)
                else (destination or contract.account_id)
            )
            postings.append(
                DepositPosting(
                    entry_type="income",
                    amount_minor=amount_minor,
                    account_id=interest_account,
                    destination_account_id=None,
                    description=f"{contract.name} 到期利息",
                )
            )
        if maturity_returns_principal(contract.maturity_action):
            postings.append(
                DepositPosting(
                    entry_type="transfer",
                    amount_minor=term.principal_minor,
                    account_id=contract.account_id,
                    destination_account_id=destination or contract.account_id,
                    description=f"{contract.name} 到期本金",
                )
            )
        return postings

    def confirm(self, event_id: str, *, actual_amount_minor: int | None = None) -> Result:
        """確認一件事件：建立交易、更新期狀態、必要時開出下一期。"""
        correlation_id = new_correlation_id()
        try:
            event = self.store.get_event(event_id)
        except STORE_FAILURES as exc:
            return failure(
                exc,
                fallback_code="DEPOSIT_CONFIRM_FAILED",
                fallback_message="定存項目無法確認入帳。請匯出診斷資訊回報。",
                correlation_id=correlation_id,
            )
        if event.status != DepositEventStatus.PENDING:
            return Result.fail("DEPOSIT_EVENT_NOT_PENDING", "這件項目已經處理過了。")

        amount = (
            actual_amount_minor
            if actual_amount_minor is not None
            else event.suggested_amount_minor
        )
        if amount is None:
            return Result.fail(
                "DEPOSIT_AMOUNT_REQUIRED",
                "請填入實際金額。利率尚未填寫時算不出建議值，需要照存摺輸入。",
            )

        try:
            postings = self.plan_postings(event, amount)
            transaction_id = self._write_postings(postings)
            self.store.settle_event(
                event_id,
                status=str(DepositEventStatus.CONFIRMED),
                actual_amount_minor=amount,
                transaction_id=transaction_id,
            )
            renewed = self._advance_term(event, amount)
        except STORE_FAILURES as exc:
            return failure(
                exc,
                fallback_code="DEPOSIT_CONFIRM_FAILED",
                fallback_message="定存項目無法確認入帳。請匯出診斷資訊回報。",
                correlation_id=correlation_id,
            )
        return Result.ok(
            "定存項目已入帳。",
            details={"transaction_id": transaction_id, "renewed_term_id": renewed},
            correlation_id=correlation_id,
        )

    def skip(self, event_id: str) -> Result:
        try:
            self.store.settle_event(event_id, status=str(DepositEventStatus.SKIPPED))
        except STORE_FAILURES as exc:
            # 以前這裡無條件回 `DEPOSIT_EVENT_NOT_PENDING`，但 `settle_event()` 的
            # `NotFoundError` 也可能是 `DEPOSIT_EVENT_NOT_FOUND` —— 那句「已經處理過了」
            # 會在「這件項目根本不存在」時說錯話。同 `update_term()` 那個修法。
            return failure(
                exc,
                fallback_code="DEPOSIT_SKIP_FAILED",
                fallback_message="定存項目無法略過。請匯出診斷資訊回報。",
            )
        return Result.ok("已略過這件定存項目。")

    def _write_postings(self, postings: list[DepositPosting]) -> str | None:
        """建立這件事件對應的交易，回傳**主要**那一筆的 id。

        每一筆各自產生 `correlation_id` —— `transactions.correlation_id` 是
        `UNIQUE`，那是刻意的設計（一次操作一筆交易），所以共用會撞。

        到期若同時有利息與本金，會產生兩筆交易，而 `deposit_events.transaction_id`
        只存得下一筆。存的是**第一筆（利息）**，和既有 `scheduled_occurrences` 只連
        一筆交易的做法一致。兩筆的日期、描述與定存名稱都對得起來，人工要找得回來。
        """
        primary: str | None = None
        occurred_at = f"{today_taipei().isoformat()}T09:00:00+08:00"
        for posting in postings:
            transaction_id = f"txn_{uuid4().hex}"
            if posting.entry_type == "transfer":
                if posting.destination_account_id is None:
                    raise ValueError("TRANSFER_DESTINATION_REQUIRED")
                record = self.store.create_transfer(
                    transaction_id=transaction_id,
                    occurred_at=occurred_at,
                    money=Money(posting.amount_minor),
                    source_account_id=posting.account_id,
                    destination_account_id=posting.destination_account_id,
                    description=posting.description,
                    correlation_id=new_correlation_id(),
                )
            else:
                record = self.store.create_transaction(
                    transaction_id=transaction_id,
                    entry_type=posting.entry_type,
                    occurred_at=occurred_at,
                    money=Money(posting.amount_minor),
                    account_id=posting.account_id,
                    category_id=self._interest_category_id(),
                    description=posting.description,
                    source="deposit",
                    correlation_id=new_correlation_id(),
                )
            if primary is None:
                primary = record.transaction_id
        return primary

    def _interest_category_id(self) -> str:
        """利息收入要記在哪個項目。沒有就建一組「利息收入／定存利息」。"""
        for parent in self.store.list_categories():
            if parent.name == "利息收入":
                children = self.store.list_categories(parent_id=parent.category_id)
                if children:
                    return children[0].category_id
                return self.store.create_category(
                    name="定存利息", parent_id=parent.category_id
                ).category_id
        parent = self.store.create_category(name="利息收入")
        return self.store.create_category(name="定存利息", parent_id=parent.category_id).category_id

    def _advance_term(self, event: DepositEvent, interest_minor: int) -> str | None:
        """到期事件確認後，把這一期收掉，需要續約就開下一期。

        同時**從實際利息反推出這一期真正的年利率**存起來。機動利率沒有事前的利率可填，
        這個反推值就是唯一有意義的利率紀錄；固定利率則可以拿它跟當初填的值對照，
        差太多通常代表計息基準的假設有誤。
        """
        if DepositEventType(event.event_type) is not DepositEventType.MATURITY:
            return None
        term = self.store.get_term(event.term_id)
        contract = self.store.get_contract(event.contract_id)
        effective = derive_annual_rate_ppm(
            interest_method=contract.interest_method,
            principal_minor=term.principal_minor,
            interest_minor=interest_minor,
            term_months=contract.term_months,
            monthly_deposit_minor=term.monthly_deposit_minor,
        )
        next_principal = renewed_principal_minor(
            maturity_action=contract.maturity_action,
            principal_minor=term.principal_minor,
            interest_minor=interest_minor,
        )
        if next_principal is None:
            self.store.set_term_status(
                term.term_id,
                str(DepositTermStatus.SETTLED),
                actual_interest_minor=interest_minor,
                effective_rate_ppm=effective,
            )
            return None
        self.store.set_term_status(
            term.term_id,
            str(DepositTermStatus.RENEWED),
            actual_interest_minor=interest_minor,
            effective_rate_ppm=effective,
        )
        # 續存照當時的牌告利率，所以新一期的利率先留空等使用者填。
        renewed = self.store.create_term(
            contract_id=contract.contract_id,
            sequence=self.store.next_sequence(contract.contract_id),
            start_date=term.maturity_date,
            maturity_date=add_months(term.maturity_date, contract.term_months),
            principal_minor=next_principal,
            annual_rate_ppm=None,
            monthly_deposit_minor=term.monthly_deposit_minor,
            note="續存，利率請依當時牌告填入",
        )
        return renewed.term_id
