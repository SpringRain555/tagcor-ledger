"""定存的 use case：建合約、產生到期待確認、確認入帳、續約。

## 最重要的一條：程式不自動入帳

到期與每月領息**只產生待確認項目**，成為交易一定要經過使用者按下確認。這與既有的
「排程只產生待確認項目」一致，也與「手動輸入才感受得到花費」的初衷一致。

`tests/integration/test_deposits.py` 有一個測試專門斷言：產生事件之後
**`account_postings` 一列都沒有增加**。

## 三 × 四效果矩陣

| 計息方式 | 期間內每月 | 到期 |
|---|---|---|
| 整存整付 | 無 | 依到期轉存方式 |
| 存本取息 | 收入：利息 → 指定帳戶 | 依到期轉存方式（本金部分） |
| 零存整付 | 轉帳：指定帳戶 → 定存 | 依到期轉存方式 |

到期那天做什麼：

| 到期轉存方式 | 本金 | 利息 | 這一期 |
|---|---|---|---|
| 不自動轉存 | 轉帳：定存 → 指定帳戶 | 收入 → 指定帳戶 | 已結清 |
| 本息自動轉存本人帳戶 | 轉帳：定存 → 指定帳戶 | 收入 → 指定帳戶 | 已結清 |
| 本金續存、利息轉存帳戶 | 留在定存（不產生交易） | 收入 → 指定帳戶 | 已續約 |
| 本息續存 | 留在定存 | 收入 → **定存帳戶** | 已續約，下期本金含息 |

前兩種在帳本上的效果**完全相同**，差別只在銀行端是否自動處理。這裡誠實記下來，
免得日後有人以為漏實作了什麼。

## 利息是收入，不是轉帳

利息是新產生的錢，所以記成**收入**；只有本金在兩個帳戶之間移動時才是**轉帳**。
把利息記成轉帳會讓總資產憑空不變，看不出來自己賺了多少。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import sqlite3
from uuid import uuid4

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.application.result import Result, new_correlation_id
from tagcor_ledger.domain.deposits import (
    DEPOSIT_EVENT_TYPE_NAMES,
    DepositContract,
    DepositEvent,
    DepositEventStatus,
    DepositEventType,
    DepositTerm,
    DepositTermStatus,
    InterestMethod,
    MaturityAction,
    RateType,
    derive_annual_rate_ppm,
    interest_goes_to_deposit_account,
    maturity_returns_principal,
    renewed_principal_minor,
    suggest_interest_minor,
    suggest_monthly_interest_minor,
)
from tagcor_ledger.domain.money import Money
from tagcor_ledger.infrastructure.clock import today_taipei
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore, NotFoundError

# 到期前幾天產生待確認項目。給「不自動轉存」留反應時間 —— 那種情況要本人去郵局處理。
MATURITY_LEAD_DAYS = 7


@dataclass(frozen=True, slots=True)
class DepositPosting:
    """確認一件定存事件會產生的一筆交易。"""

    entry_type: str
    amount_minor: int
    account_id: str
    destination_account_id: str | None
    description: str


class DepositService:
    def __init__(self, paths: AppPaths, store: LedgerStore | None = None) -> None:
        self.paths = paths
        self.store = store or LedgerStore(paths)

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
            return Result.fail("DEPOSIT_AMOUNT_INVALID", "金額格式不正確。", details={"reason": str(exc)})

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
        except (ValueError, sqlite3.Error, NotFoundError) as exc:
            return Result.fail(
                "DEPOSIT_CONTRACT_CREATE_FAILED",
                "定存合約無法建立。",
                details={"reason": str(exc)},
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
        note: str = "",
    ) -> Result:
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
        except (ValueError, sqlite3.Error, NotFoundError) as exc:
            return Result.fail(
                "DEPOSIT_CONTRACT_UPDATE_FAILED",
                "定存合約無法修改。",
                details={"reason": str(exc)},
            )
        return Result.ok("定存合約已更新。")

    def delete_contract(self, contract_id: str) -> Result:
        try:
            self.store.delete_contract(contract_id)
        except ValueError as exc:
            if str(exc) == "DEPOSIT_CONTRACT_IN_USE":
                return Result.fail(
                    "DEPOSIT_CONTRACT_IN_USE",
                    "這個定存已經有入帳紀錄，不能刪除。可以改用「結束合約」。",
                )
            return Result.fail(
                "DEPOSIT_CONTRACT_DELETE_FAILED",
                "定存合約無法刪除。",
                details={"reason": str(exc)},
            )
        except (sqlite3.Error, NotFoundError) as exc:
            return Result.fail(
                "DEPOSIT_CONTRACT_DELETE_FAILED",
                "定存合約無法刪除。",
                details={"reason": str(exc)},
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
            return Result.fail(
                "DEPOSIT_AMOUNT_INVALID", "金額格式不正確。", details={"reason": str(exc)}
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
        except NotFoundError:
            return Result.fail(
                "DEPOSIT_TERM_NOT_EDITABLE",
                "只有存續中的期可以修改。已續約或已結清的期已經產生過交易，改了會對不起帳。",
            )
        except (ValueError, sqlite3.Error) as exc:
            return Result.fail(
                "DEPOSIT_TERM_UPDATE_FAILED", "這一期無法修改。", details={"reason": str(exc)}
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

    # --- 產生待確認 ---------------------------------------------------------

    def generate_due(self, today: str | None = None) -> Result:
        """把已到期或即將到期的事件放進待確認。**不建立任何交易。**

        可以重複按 —— `deposit_events` 有 `UNIQUE (term_id, event_type, due_date)`，
        同一件事只會出現一次。
        """
        current = today or today_taipei().isoformat()
        horizon = _shift_days(current, MATURITY_LEAD_DAYS)
        generated = 0
        try:
            for term in self.store.list_active_terms():
                contract = self.store.get_contract(term.contract_id)
                generated += self._generate_for_term(contract, term, current, horizon)
        except (sqlite3.Error, NotFoundError, ValueError) as exc:
            return Result.fail(
                "DEPOSIT_GENERATE_FAILED",
                "定存待確認項目無法產生。",
                details={"reason": str(exc)},
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
            for due in _monthly_dates(term.start_date, term.maturity_date, today):
                if self.store.add_event(
                    term_id=term.term_id,
                    event_type=str(DepositEventType.INTEREST_PAYOUT),
                    due_date=due,
                    suggested_amount_minor=suggested,
                    note=f"{contract.name} 每月利息",
                ):
                    generated += 1

        if method is InterestMethod.INSTALLMENT_SAVINGS:
            for due in _monthly_dates(term.start_date, term.maturity_date, today):
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
        except NotFoundError:
            return Result.fail("DEPOSIT_EVENT_NOT_FOUND", "找不到這件定存項目。")
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
        except (ValueError, sqlite3.Error, NotFoundError) as exc:
            return Result.fail(
                "DEPOSIT_CONFIRM_FAILED",
                "定存項目無法確認入帳。",
                details={"reason": str(exc)},
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
        except NotFoundError:
            return Result.fail("DEPOSIT_EVENT_NOT_PENDING", "這件項目已經處理過了。")
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


def add_months(iso_date: str, months: int) -> str:
    """加月份。目標月份沒有那一天時退到當月最後一天（1/31 加一個月是 2/28）。"""
    base = date.fromisoformat(iso_date)
    total = base.month - 1 + months
    year = base.year + total // 12
    month = total % 12 + 1
    day = min(base.day, _days_in_month(year, month))
    return date(year, month, day).isoformat()


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def _shift_days(iso_date: str, days: int) -> str:
    return (date.fromisoformat(iso_date) + timedelta(days=days)).isoformat()


def _monthly_dates(start_date: str, maturity_date: str, today: str) -> list[str]:
    """從起存日到今天（不超過到期日）之間的每月同日。"""
    dates: list[str] = []
    index = 1
    while True:
        due = add_months(start_date, index)
        if due > maturity_date or due > today:
            break
        dates.append(due)
        index += 1
    return dates


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
