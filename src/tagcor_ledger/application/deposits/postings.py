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
    DepositContract,
    DepositEvent,
    DepositEventStatus,
    DepositEventType,
    DepositTerm,
    DepositTermStatus,
    InterestMethod,
    derive_annual_rate_ppm,
    interest_goes_to_deposit_account,
    matured_principal_minor,
    maturity_returns_principal,
    renewed_principal_minor,
)
from tagcor_ledger.domain.dates import add_months
from tagcor_ledger.domain.money import Money


def _principal_move(
    *,
    amount_minor: int,
    source_account_id: str,
    destination_account_id: str,
    description: str,
) -> list[DepositPosting]:
    """本金從定存帳戶回到指定帳戶的那一筆轉帳。**沒有動到就不要記。**

    兩種情形回空清單：

    - **金額是 0。** 零存整付一期都沒存過就解約是真的會發生。
    - **轉出與轉入是同一個帳戶。** 「利息轉入帳戶」選成定存帳戶本身是合法設定
      （使用者只有一個郵局帳戶時就會這樣填），此時本金根本沒有移動。
      硬記一筆會撞上 `create_transfer()` 的 `TRANSFER_SAME_ACCOUNT` —— 而使用者
      看到的會是「轉出與轉入不能是同一個帳戶」，一句與他正在做的事無關的話。
    """
    if amount_minor <= 0 or source_account_id == destination_account_id:
        return []
    return [
        DepositPosting(
            entry_type="transfer",
            amount_minor=amount_minor,
            account_id=source_account_id,
            destination_account_id=destination_account_id,
            description=description,
        )
    ]


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
            postings.extend(
                _principal_move(
                    amount_minor=self._matured_principal(contract, term),
                    source_account_id=contract.account_id,
                    destination_account_id=destination or contract.account_id,
                    description=f"{contract.name} 到期本金",
                )
            )
        return postings

    @staticmethod
    def _matured_principal(contract: DepositContract, term: DepositTerm) -> int:
        return matured_principal_minor(
            interest_method=contract.interest_method,
            principal_minor=term.principal_minor,
            monthly_deposit_minor=term.monthly_deposit_minor,
            term_months=contract.term_months,
        )

    def confirm(
        self,
        event_id: str,
        *,
        actual_amount_minor: int | None = None,
        occurred_on: str | None = None,
    ) -> Result:
        """確認一件事件：建立交易、更新期狀態、必要時開出下一期。

        `occurred_on` 是**交易日期**（ISO 日期），預設為這件事件的到期日。

        v0.24.0 之前它寫死成 `today_taipei()` —— 而到期項目提前七天出現，所以照著提示
        馬上確認，交易日期會比錢真的動的那天早七天。這與 ADR-0011 拿來否決定期收支的
        那個缺陷是同一類（日期由程式決定、對話框沒有欄位可改），只是偏的方向相反。
        """
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
            transaction_id = self._write_postings(postings, occurred_on or event.due_date)
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
        """略過 =「我看過，這一期不記」。**到期不能略過。**

        略過只改事件狀態，不動那一期。而 `deposit_events` 有
        `UNIQUE (term_id, event_type, due_date)` ＋ `INSERT OR IGNORE`，所以略過掉的
        事件**永遠不會再生出來** —— 略過每月領息只是少記一筆，略過到期會讓那一期
        永遠停在「存續中」：不續存、不結清，之後任何一天再產生都是 0 件，而畫面上
        看不出有什麼不對。2026-08-23 實測確認。

        利息不想記就確認、金額填 0（`plan_postings()` 會跳過那筆收入，本金照樣處理）；
        整份定存不想再追蹤就到「操作設定 → 定存」結束合約或中途解約。
        """
        try:
            event = self.store.get_event(event_id)
            if DepositEventType(event.event_type) is DepositEventType.MATURITY:
                return Result.fail(
                    "DEPOSIT_MATURITY_CANNOT_BE_SKIPPED",
                    "到期項目不能略過，略過會讓這一期永遠停在「存續中」。"
                    "利息不想記就按確認入帳、金額填 0；"
                    "整份定存不再追蹤請到「操作設定 → 定存」結束合約或中途解約。",
                )
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

    # --- 中途解約 -----------------------------------------------------------

    def terminate_term(
        self,
        term_id: str,
        *,
        occurred_on: str,
        principal_minor: int,
        interest_minor: int,
    ) -> Result:
        """提前解約：錢全部回到指定帳戶，這一期標成已解約，合約跟著結束。

        **本金與利息都由使用者填，程式一個都不猜。** 提前解約的利息通常會被打折
        （郵局按已存期間的牌告利率再乘一個折數），而 REQ-0007 §邊界 明確不做違約利息
        計算 —— 猜一個數字出來只會讓使用者以為那是算過的。

        解約之後合約一定跟著結束：這一期沒有下一期，而合約留著只會在清單上掛一份
        永遠不會再動的定存。要重新存就開一份新合約。
        """
        correlation_id = new_correlation_id()
        if principal_minor < 0 or interest_minor < 0:
            return Result.fail("DEPOSIT_AMOUNT_INVALID", "本金與利息都不能是負數。")
        try:
            term = self.store.get_term(term_id)
            if term.status != DepositTermStatus.ACTIVE:
                return Result.fail(
                    "DEPOSIT_TERM_NOT_ACTIVE",
                    "只有「存續中」的期可以中途解約。這一期已經結清、續約或解約過了。",
                )
            contract = self.store.get_contract(term.contract_id)
            destination = contract.interest_destination_account_id or contract.account_id
            postings = _principal_move(
                amount_minor=principal_minor,
                source_account_id=contract.account_id,
                destination_account_id=destination,
                description=f"{contract.name} 解約本金",
            )
            if interest_minor > 0:
                postings.append(
                    DepositPosting(
                        entry_type="income",
                        amount_minor=interest_minor,
                        account_id=destination,
                        destination_account_id=None,
                        description=f"{contract.name} 解約利息",
                    )
                )
            transaction_id = self._write_postings(postings, occurred_on)
            self.store.set_term_status(
                term_id,
                str(DepositTermStatus.TERMINATED),
                actual_interest_minor=interest_minor,
            )
            self.store.close_contract(contract.contract_id)
        except STORE_FAILURES as exc:
            return failure(
                exc,
                fallback_code="DEPOSIT_TERMINATE_FAILED",
                fallback_message="定存無法中途解約。請匯出診斷資訊回報。",
                correlation_id=correlation_id,
            )
        return Result.ok(
            "已中途解約，這份合約也一起結束了。",
            details={"transaction_id": transaction_id},
            correlation_id=correlation_id,
        )

    def _write_postings(self, postings: list[DepositPosting], occurred_on: str) -> str | None:
        """建立這件事件對應的交易，回傳**主要**那一筆的 id。

        每一筆各自產生 `correlation_id` —— `transactions.correlation_id` 是
        `UNIQUE`，那是刻意的設計（一次操作一筆交易），所以共用會撞。

        到期若同時有利息與本金，會產生兩筆交易，而 `deposit_events.transaction_id`
        只存得下一筆。存的是**第一筆（利息）**，和已經移除的定期收支當初只連
        一筆交易的做法一致。兩筆的日期、描述與定存名稱都對得起來，人工要找得回來。

        時分補 09:00 而不是現在的時刻：`occurred_on` 通常不是今天，補一個「現在」
        的時分沒有任何意義，而固定值讓同一天的兩筆（利息與本金）維持插入順序。
        """
        primary: str | None = None
        occurred_at = f"{occurred_on}T09:00:00+08:00"
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
        earned = self._term_interest(contract, term, interest_minor)
        principal = self._matured_principal(contract, term)
        effective = derive_annual_rate_ppm(
            interest_method=contract.interest_method,
            principal_minor=principal,
            interest_minor=earned,
            term_months=contract.term_months,
            monthly_deposit_minor=term.monthly_deposit_minor,
        )
        next_principal = renewed_principal_minor(
            maturity_action=contract.maturity_action,
            principal_minor=principal,
            interest_minor=interest_minor,
        )
        if next_principal is None:
            self.store.set_term_status(
                term.term_id,
                str(DepositTermStatus.SETTLED),
                actual_interest_minor=earned,
                effective_rate_ppm=effective,
            )
            return None
        self.store.set_term_status(
            term.term_id,
            str(DepositTermStatus.RENEWED),
            actual_interest_minor=earned,
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

    def _term_interest(
        self, contract: DepositContract, term: DepositTerm, maturity_amount: int
    ) -> int:
        """這一期實際領到的利息合計。

        存本取息到期那筆金額是 0（利息每個月就領走了），所以要把已經確認過的
        領息加起來 —— 否則 `actual_interest_minor` 會被寫成 0，而反推出來的實際
        年利率也會是 0，可是那一期明明有利息。
        """
        if InterestMethod(contract.interest_method) is not InterestMethod.MONTHLY_INTEREST:
            return maturity_amount
        paid = self.store.sum_confirmed_amount(
            term.term_id, str(DepositEventType.INTEREST_PAYOUT)
        )
        return paid + maturity_amount
