"""合約與期的 use case：建立、修改、刪除、列出。"""

from __future__ import annotations

from tagcor_ledger.application.deposits.base import DepositServiceBase
from tagcor_ledger.application.deposits.views import _contract_view, _term_view
from tagcor_ledger.application.failures import STORE_FAILURES, failure
from tagcor_ledger.application.result import Result, new_correlation_id
from tagcor_ledger.domain.deposits import (
    DepositEventType,
    InterestMethod,
    MaturityAction,
    RateType,
    suggest_interest_minor,
    suggest_monthly_interest_minor,
)
from tagcor_ledger.domain.dates import add_months
from tagcor_ledger.domain.money import Money


class ContractSection(DepositServiceBase):
    # --- 合約與期 -----------------------------------------------------------

    def create_contract(
        self,
        *,
        account_id: str,
        name: str,
        interest_method: str,
        maturity_action: str,
        interest_destination_account_id: str | None,
        term_months: int,
        start_date: str,
        principal: str,
        annual_rate_ppm: int | None = None,
        monthly_deposit: str | None = None,
        rate_type: str = "fixed",
        note: str = "",
    ) -> Result:
        """建立合約並開出第一期。

        `start_date` **允許早於帳本的第一筆交易** —— 既有的定存本來就比開始記帳早，
        逼使用者補完所有歷史才記得下來是本末倒置的。
        """
        try:
            InterestMethod(interest_method)
            MaturityAction(maturity_action)
            RateType(rate_type)
        except ValueError:
            return Result.fail("DEPOSIT_METHOD_INVALID", "計息方式、到期轉存方式或利率類型不正確。")

        # 機動利率不預先填數字：存的當下填的值到期時多半已經不是那個值了。
        if RateType(rate_type) is RateType.FLOATING:
            annual_rate_ppm = None
        if maturity_action != MaturityAction.RENEW_PRINCIPAL_AND_INTEREST and (
            interest_destination_account_id is None
        ):
            return Result.fail(
                "DEPOSIT_INTEREST_DESTINATION_REQUIRED",
                "請指定利息要轉入哪個帳戶。",
            )
        try:
            principal_minor = Money.from_decimal_string(principal, allow_zero=True).amount_minor
            monthly_minor = (
                Money.from_decimal_string(monthly_deposit, allow_zero=True).amount_minor
                if monthly_deposit
                else None
            )
        except ValueError as exc:
            return failure(
                exc,
                fallback_code="DEPOSIT_AMOUNT_INVALID",
                fallback_message="金額格式不正確。只接受整數元，不要加逗號或單位。",
            )

        if InterestMethod(interest_method) is InterestMethod.INSTALLMENT_SAVINGS and not monthly_minor:
            return Result.fail("DEPOSIT_MONTHLY_DEPOSIT_REQUIRED", "零存整付需要每月存入金額。")

        correlation_id = new_correlation_id()
        try:
            contract = self.store.create_contract(
                account_id=account_id,
                name=name,
                interest_method=interest_method,
                maturity_action=maturity_action,
                interest_destination_account_id=interest_destination_account_id,
                term_months=term_months,
                rate_type=rate_type,
                note=note,
            )
            term = self.store.create_term(
                contract_id=contract.contract_id,
                sequence=1,
                start_date=start_date,
                maturity_date=add_months(start_date, term_months),
                principal_minor=principal_minor,
                annual_rate_ppm=annual_rate_ppm,
                monthly_deposit_minor=monthly_minor,
            )
        except STORE_FAILURES as exc:
            return failure(
                exc,
                fallback_code="DEPOSIT_CONTRACT_CREATE_FAILED",
                fallback_message="定存合約無法建立。請匯出診斷資訊回報。",
                correlation_id=correlation_id,
            )
        return Result.ok(
            "定存合約已建立。",
            details={"contract_id": contract.contract_id, "term_id": term.term_id},
            correlation_id=correlation_id,
        )

    def update_contract(
        self,
        contract_id: str,
        *,
        name: str,
        maturity_action: str,
        interest_destination_account_id: str | None,
        note: str | None = None,
    ) -> Result:
        """`note=None` 表示不要動備註。傳 `""` 才是清空。"""
        try:
            MaturityAction(maturity_action)
        except ValueError:
            return Result.fail("DEPOSIT_METHOD_INVALID", "到期轉存方式不正確。")
        if maturity_action != MaturityAction.RENEW_PRINCIPAL_AND_INTEREST and (
            interest_destination_account_id is None
        ):
            return Result.fail(
                "DEPOSIT_INTEREST_DESTINATION_REQUIRED", "請指定利息要轉入哪個帳戶。"
            )
        try:
            self.store.update_contract(
                contract_id,
                name=name,
                maturity_action=maturity_action,
                interest_destination_account_id=interest_destination_account_id,
                note=note,
            )
        except STORE_FAILURES as exc:
            return failure(
                exc,
                fallback_code="DEPOSIT_CONTRACT_UPDATE_FAILED",
                fallback_message="定存合約無法修改。請匯出診斷資訊回報。",
            )
        return Result.ok("定存合約已更新。")

    def delete_contract(self, contract_id: str) -> Result:
        """刪除合約。

        以前這裡有一個 `if str(exc) == "DEPOSIT_CONTRACT_IN_USE"` 的手動分支 ——
        那是「唯一一個值得講清楚的失敗」被特別挑出來的痕跡。`failure()` 對每一個
        碼都這樣做，所以那個分支連同它下面重複的 `except` 一起沒了。
        """
        try:
            self.store.delete_contract(contract_id)
        except STORE_FAILURES as exc:
            return failure(
                exc,
                fallback_code="DEPOSIT_CONTRACT_DELETE_FAILED",
                fallback_message="定存合約無法刪除。請匯出診斷資訊回報。",
            )
        return Result.ok("定存合約已刪除。")

    def update_term(
        self,
        term_id: str,
        *,
        start_date: str,
        maturity_date: str,
        principal: str,
        annual_rate_ppm: int | None,
        monthly_deposit: str | None = None,
        note: str = "",
    ) -> Result:
        """修改一期 —— 主要用途是**查到牌告利率之後回來補**。"""
        try:
            principal_minor = Money.from_decimal_string(principal, allow_zero=True).amount_minor
            monthly_minor = (
                Money.from_decimal_string(monthly_deposit, allow_zero=True).amount_minor
                if monthly_deposit
                else None
            )
        except ValueError as exc:
            return failure(
                exc,
                fallback_code="DEPOSIT_AMOUNT_INVALID",
                fallback_message="金額格式不正確。只接受整數元，不要加逗號或單位。",
            )
        try:
            self.store.update_term(
                term_id,
                start_date=start_date,
                maturity_date=maturity_date,
                principal_minor=principal_minor,
                annual_rate_ppm=annual_rate_ppm,
                monthly_deposit_minor=monthly_minor,
                note=note,
            )
        except STORE_FAILURES as exc:
            # 以前這裡有一個 `except NotFoundError:` 無條件回 `DEPOSIT_TERM_NOT_EDITABLE`
            # 的分支 —— 但 store 的 `NotFoundError` 也可能是 `DEPOSIT_TERM_NOT_FOUND`，
            # 那句「只有存續中的期可以修改」會在「這一期根本不存在」時說錯話。
            return failure(
                exc,
                fallback_code="DEPOSIT_TERM_UPDATE_FAILED",
                fallback_message="這一期無法修改。請匯出診斷資訊回報。",
            )
        self._refresh_suggestions(term_id)
        return Result.ok("這一期已更新。")

    def _refresh_suggestions(self, term_id: str) -> None:
        """利率或本金改了之後，把待確認裡過期的建議金額重算一次。"""
        term = self.store.get_term(term_id)
        contract = self.store.get_contract(term.contract_id)
        for event in self.store.list_pending_events_for_term(term_id):
            event_type = DepositEventType(event.event_type)
            if event_type is DepositEventType.INTEREST_PAYOUT:
                amount = suggest_monthly_interest_minor(
                    principal_minor=term.principal_minor,
                    annual_rate_ppm=term.annual_rate_ppm,
                )
            elif event_type is DepositEventType.INSTALLMENT:
                amount = term.monthly_deposit_minor
            else:
                amount = suggest_interest_minor(
                    interest_method=contract.interest_method,
                    principal_minor=term.principal_minor,
                    annual_rate_ppm=term.annual_rate_ppm,
                    term_months=contract.term_months,
                    monthly_deposit_minor=term.monthly_deposit_minor,
                )
            self.store.update_event_suggestion(event.event_id, amount)

    def list_contracts(self, *, include_closed: bool = False) -> Result:
        contracts = self.store.list_contracts(include_closed=include_closed)
        return Result.ok(details={"contracts": [_contract_view(item) for item in contracts]})

    def list_terms(self, contract_id: str | None = None) -> Result:
        terms = self.store.list_terms(contract_id=contract_id)
        return Result.ok(details={"terms": [_term_view(item) for item in terms]})
