"""定存：三種計息方式 × 四種到期轉存方式，共十二種組合。

最重要的斷言在 `test_generating_events_never_writes_a_posting` —— **程式不自動入帳**。
其餘測試檢查每種組合到期時該產生哪些交易、以及該不該續約。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.application.deposits import DepositService
from tagcor_ledger.domain.dates import add_months
from tagcor_ledger.domain.deposits import (
    DepositEventType,
    DepositTermStatus,
    InterestMethod,
    MaturityAction,
    suggest_interest_minor,
    suggest_monthly_interest_minor,
)
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


RATE_1_60_PERCENT = 16_000  # 1.60% 以百萬分之一為單位


@pytest.fixture
def service(tmp_path: Path) -> DepositService:
    paths = resolve_app_paths(tmp_path / "data")
    store = LedgerStore(paths)
    store.create_account(name="郵局活儲")
    store.create_account(name="郵局定存")
    return DepositService(paths, store)


def _accounts(service: DepositService) -> tuple[str, str]:
    accounts = {item.name: item.account_id for item in service.store.list_accounts()}
    return accounts["郵局定存"], accounts["郵局活儲"]


def _make_contract(
    service: DepositService,
    *,
    interest_method: str,
    maturity_action: str,
    principal: str = "100000",
    start_date: str = "2026-02-15",
    rate: int | None = RATE_1_60_PERCENT,
    monthly_deposit: str | None = None,
) -> str:
    deposit_id, savings_id = _accounts(service)
    result = service.create_contract(
        account_id=deposit_id,
        name="郵局定存",
        interest_method=interest_method,
        maturity_action=maturity_action,
        interest_destination_account_id=savings_id,
        term_months=12,
        start_date=start_date,
        principal=principal,
        annual_rate_ppm=rate,
        monthly_deposit=monthly_deposit,
    )
    assert result.success, result.message
    return str(result.details["contract_id"])


def _posting_count(service: DepositService) -> int:
    with sqlite3.connect(service.paths.database_path) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM account_postings").fetchone()[0])


# --- 最重要的一條 -----------------------------------------------------------


def test_generating_events_never_writes_a_posting(service: DepositService) -> None:
    """**程式不自動入帳。** 產生待確認不得動到任何 posting。"""
    _make_contract(
        service,
        interest_method=str(InterestMethod.MONTHLY_INTEREST),
        maturity_action=str(MaturityAction.NONE),
    )
    before = _posting_count(service)

    result = service.generate_due(today="2027-02-15")
    assert result.success
    assert int(result.details["generated"]) > 0, "什麼都沒產生的話這個測試沒有在檢查東西"

    assert _posting_count(service) == before, "產生待確認項目竟然寫了 posting"


def test_generate_due_is_idempotent(service: DepositService) -> None:
    """「產生到期項目」可以按很多次，同一件事不該重複出現。"""
    _make_contract(
        service,
        interest_method=str(InterestMethod.LUMP_SUM),
        maturity_action=str(MaturityAction.RENEW_PRINCIPAL_ONLY),
    )
    first = service.generate_due(today="2027-02-15")
    second = service.generate_due(today="2027-02-15")

    assert int(first.details["generated"]) == 1
    assert int(second.details["generated"]) == 0
    assert len(service.list_pending().details["events"]) == 1


def test_maturity_appears_seven_days_early(service: DepositService) -> None:
    """「不自動轉存」要本人跑一趟郵局，所以提前七天提醒。"""
    _make_contract(
        service,
        interest_method=str(InterestMethod.LUMP_SUM),
        maturity_action=str(MaturityAction.NONE),
    )
    assert int(service.generate_due(today="2027-02-07").details["generated"]) == 0
    assert int(service.generate_due(today="2027-02-08").details["generated"]) == 1


# --- 十二種組合的到期效果 ---------------------------------------------------


@pytest.mark.parametrize("interest_method", list(InterestMethod))
@pytest.mark.parametrize("maturity_action", list(MaturityAction))
def test_every_combination_plans_the_right_postings(
    service: DepositService, interest_method: InterestMethod, maturity_action: MaturityAction
) -> None:
    monthly = "3000" if interest_method is InterestMethod.INSTALLMENT_SAVINGS else None
    _make_contract(
        service,
        interest_method=str(interest_method),
        maturity_action=str(maturity_action),
        monthly_deposit=monthly,
    )
    service.generate_due(today="2027-02-15")
    maturity = [
        event
        for event in service.store.list_pending_events()
        if event.event_type == DepositEventType.MATURITY
    ]
    assert len(maturity) == 1

    deposit_id, savings_id = _accounts(service)
    postings = service.plan_postings(maturity[0], 1_600)

    interest = [item for item in postings if item.entry_type == "income"]
    transfers = [item for item in postings if item.entry_type == "transfer"]

    assert len(interest) == 1, "每種組合到期都會產生利息收入"
    if maturity_action is MaturityAction.RENEW_PRINCIPAL_AND_INTEREST:
        assert interest[0].account_id == deposit_id, "本息續存時利息留在定存帳戶"
    else:
        assert interest[0].account_id == savings_id, "其餘情況利息轉進指定帳戶"

    if maturity_action in {MaturityAction.NONE, MaturityAction.PRINCIPAL_INTEREST_TO_ACCOUNT}:
        assert len(transfers) == 1, "不續存時本金要離開定存帳戶"
        assert transfers[0].account_id == deposit_id
        assert transfers[0].destination_account_id == savings_id
        assert transfers[0].amount_minor == 100_000
    else:
        assert transfers == [], "續存時本金留在定存，不該產生轉帳"


@pytest.mark.parametrize(
    ("maturity_action", "expected_status", "expected_principal"),
    [
        (MaturityAction.NONE, DepositTermStatus.SETTLED, None),
        (MaturityAction.PRINCIPAL_INTEREST_TO_ACCOUNT, DepositTermStatus.SETTLED, None),
        (MaturityAction.RENEW_PRINCIPAL_ONLY, DepositTermStatus.RENEWED, 100_000),
        (
            MaturityAction.RENEW_PRINCIPAL_AND_INTEREST,
            DepositTermStatus.RENEWED,
            101_600,
        ),
    ],
)
def test_confirming_maturity_settles_or_renews(
    service: DepositService,
    maturity_action: MaturityAction,
    expected_status: DepositTermStatus,
    expected_principal: int | None,
) -> None:
    contract_id = _make_contract(
        service,
        interest_method=str(InterestMethod.LUMP_SUM),
        maturity_action=str(maturity_action),
    )
    service.generate_due(today="2027-02-15")
    event = service.store.list_pending_events()[0]

    result = service.confirm(event.event_id, actual_amount_minor=1_600)
    assert result.success, result.message

    terms = service.store.list_terms(contract_id=contract_id)
    first = next(item for item in terms if item.sequence == 1)
    assert first.status == expected_status
    assert first.actual_interest_minor == 1_600

    if expected_principal is None:
        assert len(terms) == 1, "不續存不該開新的一期"
        return
    renewed = next(item for item in terms if item.sequence == 2)
    assert renewed.principal_minor == expected_principal
    assert renewed.start_date == "2027-02-15"
    assert renewed.maturity_date == "2028-02-15"
    # 續存照當時牌告利率，所以新一期利率留空等使用者填。
    assert renewed.annual_rate_ppm is None


def test_confirming_actually_creates_transactions(service: DepositService) -> None:
    _make_contract(
        service,
        interest_method=str(InterestMethod.LUMP_SUM),
        maturity_action=str(MaturityAction.NONE),
    )
    service.generate_due(today="2027-02-15")
    event = service.store.list_pending_events()[0]
    before = _posting_count(service)

    assert service.confirm(event.event_id, actual_amount_minor=1_600).success

    # 利息收入 1 筆 posting ＋ 本金轉帳 2 筆 posting
    assert _posting_count(service) == before + 3


def test_monthly_interest_generates_one_event_per_month(service: DepositService) -> None:
    _make_contract(
        service,
        interest_method=str(InterestMethod.MONTHLY_INTEREST),
        maturity_action=str(MaturityAction.NONE),
    )
    service.generate_due(today="2026-06-20")
    payouts = [
        event
        for event in service.store.list_pending_events()
        if event.event_type == DepositEventType.INTEREST_PAYOUT
    ]
    # 起存 2/15，到 6/20 為止是 3/15、4/15、5/15、6/15 四期。
    assert [event.due_date for event in payouts] == [
        "2026-03-15",
        "2026-04-15",
        "2026-05-15",
        "2026-06-15",
    ]
    assert payouts[0].suggested_amount_minor == suggest_monthly_interest_minor(
        principal_minor=100_000, annual_rate_ppm=RATE_1_60_PERCENT
    )


def test_installment_savings_asks_for_a_monthly_deposit(service: DepositService) -> None:
    deposit_id, savings_id = _accounts(service)
    result = service.create_contract(
        account_id=deposit_id,
        name="零存整付",
        interest_method=str(InterestMethod.INSTALLMENT_SAVINGS),
        maturity_action=str(MaturityAction.NONE),
        interest_destination_account_id=savings_id,
        term_months=12,
        start_date="2026-02-15",
        principal="0",
        annual_rate_ppm=RATE_1_60_PERCENT,
    )
    assert not result.success
    assert result.error_code == "DEPOSIT_MONTHLY_DEPOSIT_REQUIRED"


def test_installment_events_are_transfers_into_the_deposit(service: DepositService) -> None:
    _make_contract(
        service,
        interest_method=str(InterestMethod.INSTALLMENT_SAVINGS),
        maturity_action=str(MaturityAction.NONE),
        principal="0",
        monthly_deposit="3000",
    )
    service.generate_due(today="2026-04-20")
    installments = [
        event
        for event in service.store.list_pending_events()
        if event.event_type == DepositEventType.INSTALLMENT
    ]
    assert installments

    deposit_id, savings_id = _accounts(service)
    posting = service.plan_postings(installments[0], 3_000)[0]
    assert posting.entry_type == "transfer"
    assert posting.account_id == savings_id
    assert posting.destination_account_id == deposit_id


# --- 利率未知 ---------------------------------------------------------------


def test_contract_can_be_created_before_the_rate_is_known(service: DepositService) -> None:
    """年利率查到再填。**不知道利率不該擋住把定存記下來。**"""
    contract_id = _make_contract(
        service,
        interest_method=str(InterestMethod.LUMP_SUM),
        maturity_action=str(MaturityAction.RENEW_PRINCIPAL_ONLY),
        rate=None,
    )
    terms = service.store.list_terms(contract_id=contract_id)
    assert terms[0].annual_rate_ppm is None

    service.generate_due(today="2027-02-15")
    event = service.store.list_pending_events()[0]
    assert event.suggested_amount_minor is None


def test_confirming_without_a_rate_requires_an_explicit_amount(service: DepositService) -> None:
    _make_contract(
        service,
        interest_method=str(InterestMethod.LUMP_SUM),
        maturity_action=str(MaturityAction.NONE),
        rate=None,
    )
    service.generate_due(today="2027-02-15")
    event = service.store.list_pending_events()[0]

    result = service.confirm(event.event_id)
    assert not result.success
    assert result.error_code == "DEPOSIT_AMOUNT_REQUIRED"
    assert "存摺" in result.message

    assert service.confirm(event.event_id, actual_amount_minor=1_580).success


def test_user_amount_overrides_the_suggestion(service: DepositService) -> None:
    """建議值永遠不是權威值 —— 以存摺為準。"""
    _make_contract(
        service,
        interest_method=str(InterestMethod.LUMP_SUM),
        maturity_action=str(MaturityAction.NONE),
    )
    service.generate_due(today="2027-02-15")
    event = service.store.list_pending_events()[0]
    assert event.suggested_amount_minor is not None

    service.confirm(event.event_id, actual_amount_minor=1_234)
    term = service.store.get_term(event.term_id)
    assert term.actual_interest_minor == 1_234


# --- 試算 -------------------------------------------------------------------


def test_lump_sum_compounds_and_monthly_interest_does_not() -> None:
    """整存整付是複利、存本取息是單利，所以前者一定比較多。"""
    compound = suggest_interest_minor(
        interest_method=str(InterestMethod.LUMP_SUM),
        principal_minor=100_000,
        annual_rate_ppm=RATE_1_60_PERCENT,
        term_months=12,
    )
    simple = suggest_interest_minor(
        interest_method=str(InterestMethod.MONTHLY_INTEREST),
        principal_minor=100_000,
        annual_rate_ppm=RATE_1_60_PERCENT,
        term_months=12,
    )
    assert compound is not None and simple is not None
    assert simple == 1_600  # 100000 × 1.6%
    assert compound > simple
    assert compound == 1_612


def test_suggestions_are_integers_never_floats() -> None:
    """金額禁止 float。這裡順便確認試算沒有偷偷回傳浮點數。"""
    value = suggest_interest_minor(
        interest_method=str(InterestMethod.LUMP_SUM),
        principal_minor=123_457,
        annual_rate_ppm=15_950,  # 1.595%
        term_months=12,
    )
    assert isinstance(value, int)


def test_no_rate_means_no_suggestion() -> None:
    assert (
        suggest_interest_minor(
            interest_method=str(InterestMethod.LUMP_SUM),
            principal_minor=100_000,
            annual_rate_ppm=None,
            term_months=12,
        )
        is None
    )


# --- 日期 -------------------------------------------------------------------


def test_add_months_clamps_to_the_end_of_short_months() -> None:
    assert add_months("2026-01-31", 1) == "2026-02-28"
    assert add_months("2026-02-15", 12) == "2027-02-15"
    assert add_months("2024-02-29", 12) == "2025-02-28"
    assert add_months("2026-12-15", 1) == "2027-01-15"


def test_start_date_may_precede_the_first_transaction(service: DepositService) -> None:
    """既有定存比開始記帳早。**這必須合法**，否則得先補完好幾個月的歷史才記得下來。"""
    contract_id = _make_contract(service,
        interest_method=str(InterestMethod.LUMP_SUM),
        maturity_action=str(MaturityAction.RENEW_PRINCIPAL_ONLY),
        start_date="2026-02-15",
    )
    terms = service.store.list_terms(contract_id=contract_id)
    assert terms[0].start_date == "2026-02-15"
    assert terms[0].maturity_date == "2027-02-15"
