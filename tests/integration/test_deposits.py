"""定存：三種計息方式 × 四種到期及轉存方式，共十二種組合。

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
    opened_on: str = "2026-02-15",
    rate: int | None = RATE_1_60_PERCENT,
    monthly_deposit: str | None = None,
    recorded_on: str | None = None,
    term_months: int = 12,
) -> str:
    """`recorded_on` 預設等於首次起存日 —— 「這份定存一存進去就記進帳本了」。

    **不留成預設的今天。** `recorded_on` 是產生待確認項目的下界（ADR-0012），
    而這一整個檔案用的是 2026／2027 的假日期；黏在真實時鐘上的話每一條
    `generate_due(today=...)` 都會變成「什麼都沒產生也算通過」。
    補記歷史那條路自己傳一個晚一點的日期，見
    `test_events_before_the_record_date_are_not_generated`。
    """
    deposit_id, savings_id = _accounts(service)
    result = service.create_contract(
        account_id=deposit_id,
        name="郵局定存",
        interest_method=interest_method,
        maturity_action=maturity_action,
        interest_destination_account_id=savings_id,
        term_months=term_months,
        opened_on=opened_on,
        principal=principal,
        annual_rate_ppm=rate,
        monthly_deposit=monthly_deposit,
        recorded_on=recorded_on or opened_on,
    )
    assert result.success, result.message
    return str(result.details["contract_id"])


def _posting_count(service: DepositService) -> int:
    with sqlite3.connect(service.paths.database_path) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM account_postings").fetchone()[0])


def test_confirming_a_deposit_event_goes_through_the_same_transaction_writer(
    service: DepositService,
) -> None:
    """定存確認不得自己另寫一份「建立交易」。

    **這條從 `test_phase2_automation.py` 搬過來**（v0.23.0 移除定期收支時）。
    原本守的是定期收支確認，而那條路已經不存在了 —— 但不變量本身沒有變：
    「一筆交易長什麼樣」只有 `stores/base.py` 的 `_write_transaction()` /
    `_write_transfer()` 說了算，任何會建立交易的路徑都必須走它。

    自己寫一份的代價不是重複，是**分岔**：schema 一改要改兩個地方，而只有一邊有
    測試盯著。判準用稽核列 —— 走共用寫入路徑就一定會留下 `transaction.create`，
    自己另寫一份就不會。

    `test_architecture.py` 從 AST 那一側守同一件事（那三張表只能有一個寫入點）；
    這一條是行為面的交叉驗證，兩邊都要有。
    """
    _make_contract(
        service,
        interest_method=str(InterestMethod.LUMP_SUM),
        maturity_action=str(MaturityAction.NONE),
    )
    service.generate_due(today="2027-02-15")
    event = service.store.list_pending_events()[0]

    result = service.confirm(event.event_id, actual_amount_minor=1_600)
    assert result.success, result.message
    transaction_id = str(result.details["transaction_id"])

    with sqlite3.connect(service.paths.database_path) as connection:
        rows = [
            dict(zip(("action", "entity_id"), row, strict=True))
            for row in connection.execute(
                "SELECT action, entity_id FROM audit_events ORDER BY audit_id"
            )
        ]
    created = [
        row
        for row in rows
        if row["action"] == "transaction.create" and row["entity_id"] == transaction_id
    ]
    assert created, (
        "定存確認出來的交易沒有 transaction.create 稽核列 —— "
        f"表示它沒有走共用的寫入路徑。實際稽核列：{rows}"
    )


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
    # **零存整付的本金是 0**，錢是每月存進去的。v0.24.0 之前這裡三種計息方式都給
    # `principal="100000"` —— 一個現實中不存在的零存整付，於是下面那句
    # `amount_minor == 100_000` 照樣通過，而真正的零存整付到期轉回的是 **0 元**。
    # 那個 bug 活了十五個版本，就是因為這條測試餵的資料不是真的。
    installment = interest_method is InterestMethod.INSTALLMENT_SAVINGS
    _make_contract(
        service,
        interest_method=str(interest_method),
        maturity_action=str(maturity_action),
        principal="0" if installment else "100000",
        monthly_deposit="3000" if installment else None,
    )
    expected_principal = 3_000 * 12 if installment else 100_000
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
        assert transfers[0].amount_minor == expected_principal
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
        opened_on="2026-02-15",
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
        opened_on="2026-02-15",
    )
    terms = service.store.list_terms(contract_id=contract_id)
    assert terms[0].start_date == "2026-02-15"
    assert terms[0].maturity_date == "2027-02-15"


# --- 補記歷史定存：建檔日是產生的下界（ADR-0012）--------------------------------


def test_events_that_fell_due_before_the_record_date_are_not_generated(
    service: DepositService,
) -> None:
    """**這條是 v0.24.0 這次改動存在的理由。**

    使用者今天才建郵局帳戶、期初餘額填的是當下的餘額，然後照存單把起存日填成
    2025-02-15。那一整年的領息早就進了那個帳戶，也就是**已經含在期初餘額裡** ——
    再產生一次草稿就是邀請他把同一筆錢記第二次。

    2026-08-23 實測（改動之前）：這個組合會一次倒 **13 筆**日期全在過去的項目進待確認。
    """
    _make_contract(
        service,
        interest_method=str(InterestMethod.MONTHLY_INTEREST),
        maturity_action=str(MaturityAction.RENEW_PRINCIPAL_ONLY),
        opened_on="2025-02-15",
        recorded_on="2026-08-23",
    )

    result = service.generate_due(today="2026-08-23")

    assert int(result.details["generated"]) == 0
    assert service.store.list_pending_events() == []


def test_the_floor_does_not_swallow_events_after_the_record_date(
    service: DepositService,
) -> None:
    """陽性對照：下界只擋建檔之前的，之後的照常產生。

    沒有這一條的話，一個「什麼都不產生」的實作也能讓上一條通過。
    """
    _make_contract(
        service,
        interest_method=str(InterestMethod.MONTHLY_INTEREST),
        maturity_action=str(MaturityAction.RENEW_PRINCIPAL_ONLY),
        opened_on="2025-02-15",
        recorded_on="2025-11-01",
    )

    service.generate_due(today="2026-01-20")

    payouts = [
        event.due_date
        for event in service.store.list_pending_events()
        if event.event_type == DepositEventType.INTEREST_PAYOUT
    ]
    assert payouts == ["2025-11-15", "2025-12-15", "2026-01-15"], (
        "建檔日之後的每一期都要有，之前的一期都不要"
    )


def test_a_closed_contract_stops_producing_events(service: DepositService) -> None:
    """結束合約之後不該再長出待確認項目 —— 而它在畫面上預設是看不見的。

    `generate_due()` 走的是 `list_active_terms()`（期層級），少了合約那一側的條件，
    一份已結束的合約仍然會生出到期項目而使用者找不到它是誰生的。
    """
    contract_id = _make_contract(
        service,
        interest_method=str(InterestMethod.LUMP_SUM),
        maturity_action=str(MaturityAction.NONE),
    )
    service.generate_due(today="2027-02-15")
    event = service.store.list_pending_events()[0]
    assert service.confirm(event.event_id, actual_amount_minor=1_600).success

    assert service.close_contract(contract_id).success
    assert int(service.generate_due(today="2030-01-01").details["generated"]) == 0


# --- 到期那天的金額 -------------------------------------------------------------


def test_monthly_interest_does_not_pay_the_whole_term_again_at_maturity(
    service: DepositService,
) -> None:
    """存本取息每個月領息，到期建議利息必須是 **0**。

    改動之前 100,000 @ 1.60% 一年會產生 12 筆領息，**再加上**一筆金額等於整期總額
    的到期利息 —— 照建議值確認下去，帳上的利息剛好是實際的兩倍。
    """
    _make_contract(
        service,
        interest_method=str(InterestMethod.MONTHLY_INTEREST),
        maturity_action=str(MaturityAction.NONE),
    )
    service.generate_due(today="2027-02-15")

    events = service.store.list_pending_events()
    payouts = [e for e in events if e.event_type == DepositEventType.INTEREST_PAYOUT]
    maturity = next(e for e in events if e.event_type == DepositEventType.MATURITY)

    assert len(payouts) == 12, "十二期領息都要在，否則這條測試比的是別的東西"
    assert sum(e.suggested_amount_minor or 0 for e in payouts) > 0
    assert maturity.suggested_amount_minor == 0


def test_confirming_a_monthly_interest_maturity_records_the_interest_that_was_paid(
    service: DepositService,
) -> None:
    """到期金額是 0，但這一期**確實有利息** —— `actual_interest_minor` 要是領走的合計。

    直接把 0 寫進去的話，反推出來的實際年利率也會是 0，而那一期明明有利息。
    """
    contract_id = _make_contract(
        service,
        interest_method=str(InterestMethod.MONTHLY_INTEREST),
        maturity_action=str(MaturityAction.NONE),
    )
    service.generate_due(today="2027-02-15")
    events = service.store.list_pending_events()
    for payout in [e for e in events if e.event_type == DepositEventType.INTEREST_PAYOUT]:
        assert service.confirm(payout.event_id, actual_amount_minor=130).success
    maturity = next(e for e in events if e.event_type == DepositEventType.MATURITY)

    assert service.confirm(maturity.event_id, actual_amount_minor=0).success

    term = next(iter(service.store.list_terms(contract_id=contract_id)))
    assert term.actual_interest_minor == 130 * 12
    assert term.effective_rate_ppm, "有利息就該反推得出年利率，不該是 0 或 None"


def test_installment_savings_returns_the_accumulated_principal_not_zero(
    service: DepositService,
) -> None:
    """零存整付到期轉回的本金是**每月存入 × 期長**，不是 `principal_minor`（它是 0）。

    改動之前這裡是一筆 0 元的轉帳，而使用者的錢就這樣留在定存帳戶裡對不起來。
    """
    _make_contract(
        service,
        interest_method=str(InterestMethod.INSTALLMENT_SAVINGS),
        maturity_action=str(MaturityAction.NONE),
        principal="0",
        monthly_deposit="3000",
    )
    service.generate_due(today="2027-02-15")
    maturity = next(
        event
        for event in service.store.list_pending_events()
        if event.event_type == DepositEventType.MATURITY
    )

    postings = service.plan_postings(maturity, maturity.suggested_amount_minor or 0)
    transfer = next(item for item in postings if item.entry_type == "transfer")
    assert transfer.amount_minor == 3_000 * 12


def test_installment_savings_renews_with_the_accumulated_principal(
    service: DepositService,
) -> None:
    """續存的下一期本金也要是累積出來的那個數字，不是 0。"""
    contract_id = _make_contract(
        service,
        interest_method=str(InterestMethod.INSTALLMENT_SAVINGS),
        maturity_action=str(MaturityAction.RENEW_PRINCIPAL_ONLY),
        principal="0",
        monthly_deposit="3000",
    )
    service.generate_due(today="2027-02-15")
    maturity = next(
        event
        for event in service.store.list_pending_events()
        if event.event_type == DepositEventType.MATURITY
    )
    assert service.confirm(maturity.event_id, actual_amount_minor=306).success

    terms = service.store.list_terms(contract_id=contract_id)
    renewed = next(item for item in terms if item.sequence == 2)
    assert renewed.principal_minor == 3_000 * 12


# --- 略過 -----------------------------------------------------------------------


def test_a_maturity_cannot_be_skipped(service: DepositService) -> None:
    """**略過到期會讓那一期永遠卡住**，所以擋下來。

    `settle_event()` 只改事件狀態，而 `deposit_events` 有
    `UNIQUE (term_id, event_type, due_date)` ＋ `INSERT OR IGNORE` —— 略過掉的到期
    事件永遠不會再生出來，那一期就停在 `active`：不續存、不結清，之後任何一天再
    產生都是 0 件（2026-08-23 實測）。
    """
    contract_id = _make_contract(
        service,
        interest_method=str(InterestMethod.LUMP_SUM),
        maturity_action=str(MaturityAction.RENEW_PRINCIPAL_ONLY),
    )
    service.generate_due(today="2027-02-15")
    event = service.store.list_pending_events()[0]

    result = service.skip(event.event_id)

    assert not result.success
    assert result.error_code == "DEPOSIT_MATURITY_CANNOT_BE_SKIPPED"
    assert "0" in result.message and "確認" in result.message, result.message
    assert "DEPOSIT_" not in result.message, f"錯誤碼漏到畫面上了：{result.message}"
    # 那一列還在，而且那一期還是存續中 —— 使用者可以改用確認。
    assert len(service.store.list_pending_events()) == 1
    terms = service.store.list_terms(contract_id=contract_id)
    assert terms[0].status == DepositTermStatus.ACTIVE


def test_a_monthly_payout_can_still_be_skipped(service: DepositService) -> None:
    """陽性對照：擋的只有到期，每月領息照樣略過得掉。"""
    _make_contract(
        service,
        interest_method=str(InterestMethod.MONTHLY_INTEREST),
        maturity_action=str(MaturityAction.NONE),
    )
    service.generate_due(today="2026-06-20")
    payout = service.store.list_pending_events()[0]
    assert payout.event_type == DepositEventType.INTEREST_PAYOUT

    assert service.skip(payout.event_id).success


# --- 交易日期 -------------------------------------------------------------------


def _transaction_dates(service: DepositService) -> set[str]:
    with sqlite3.connect(service.paths.database_path) as connection:
        return {
            str(row[0])[:10]
            for row in connection.execute("SELECT occurred_at FROM transactions")
        }


def test_the_transaction_lands_on_the_due_date_not_the_day_you_pressed_confirm(
    service: DepositService,
) -> None:
    """到期項目**提前七天**出現，所以「按確認那天」不是錢動的那天。

    改動之前 `_write_postings()` 寫死 `today_taipei()`，照著提示馬上確認會讓交易
    早七天。這與 ADR-0011 拿來否決定期收支的缺陷是同一類（日期由程式決定、對話框
    沒有欄位可改），只是偏的方向相反。

    **斷言比的是事件的到期日，不是任何一個「今天」** —— 用今天比的話，把實作改回
    `today_taipei()` 這條測試照樣會過。
    """
    _make_contract(
        service,
        interest_method=str(InterestMethod.LUMP_SUM),
        maturity_action=str(MaturityAction.NONE),
    )
    service.generate_due(today="2027-02-08")
    event = service.store.list_pending_events()[0]
    assert event.due_date == "2027-02-15"

    assert service.confirm(event.event_id, actual_amount_minor=1_600).success

    assert _transaction_dates(service) == {"2027-02-15"}


def test_the_user_can_move_the_transaction_to_the_real_passbook_date(
    service: DepositService,
) -> None:
    """銀行晚一兩天入帳時，日期要跟得上存摺 —— 對話框有那一欄。"""
    _make_contract(
        service,
        interest_method=str(InterestMethod.LUMP_SUM),
        maturity_action=str(MaturityAction.NONE),
    )
    service.generate_due(today="2027-02-15")
    event = service.store.list_pending_events()[0]

    assert service.confirm(
        event.event_id, actual_amount_minor=1_600, occurred_on="2027-02-17"
    ).success

    assert _transaction_dates(service) == {"2027-02-17"}


def test_the_principal_is_not_moved_when_it_never_left_the_account(
    service: DepositService,
) -> None:
    """「利息轉入帳戶」選成定存帳戶本身時，到期不該記一筆自己轉給自己的轉帳。

    只有一個郵局帳戶的人就會這樣填。硬記一筆會撞上 `create_transfer()` 的
    `TRANSFER_SAME_ACCOUNT`，而使用者看到的是「轉出與轉入不能是同一個帳戶」——
    一句與他正在做的事無關的話。
    """
    deposit_id, _ = _accounts(service)
    result = service.create_contract(
        account_id=deposit_id,
        name="只有一個帳戶",
        interest_method=str(InterestMethod.LUMP_SUM),
        maturity_action=str(MaturityAction.NONE),
        interest_destination_account_id=deposit_id,
        term_months=12,
        opened_on="2026-02-15",
        principal="100000",
        annual_rate_ppm=RATE_1_60_PERCENT,
        recorded_on="2026-02-15",
    )
    assert result.success, result.message
    service.generate_due(today="2027-02-15")
    event = service.store.list_pending_events()[0]

    assert [item.entry_type for item in service.plan_postings(event, 1_600)] == ["income"]
    assert service.confirm(event.event_id, actual_amount_minor=1_600).success


# --- 存單上那一天 → 目前存續中那一期（ADR-0012 第二次修正）--------------------


def test_recording_a_passbook_date_creates_the_term_that_is_live_today(
    service: DepositService,
) -> None:
    """**這條是使用者實際會做的動作。**

    存單：112/11/15 存入、113/11/15 到期、勾「本金無限次數自動轉期續存」。
    他 2026-08-23 才把它記進帳本，而郵局早就自動續存過兩輪 —— 當下存續中的是
    114/11/15 那一期，**第 3 期**。

    建立出來的就該是那一期，而合約記得存單上那一天。
    """
    contract_id = _make_contract(
        service,
        interest_method=str(InterestMethod.LUMP_SUM),
        maturity_action=str(MaturityAction.RENEW_PRINCIPAL_ONLY),
        opened_on="2023-11-15",
        recorded_on="2026-08-23",
    )

    contract = service.store.get_contract(contract_id)
    assert contract.opened_on == "2023-11-15", "存單上那一天要留著"
    assert contract.recorded_on == "2026-08-23"

    terms = service.store.list_terms(contract_id=contract_id)
    assert len(terms) == 1, "中間那兩期不補紀錄 —— 當時的利率與實際利息都不在帳本裡"
    assert (terms[0].start_date, terms[0].maturity_date) == ("2026-02-15", "2027-02-15")
    assert terms[0].sequence == 3, "跳號是誠實的，補號不是"

    # 而且它什麼都不會多生：到期日還在未來。
    assert int(service.generate_due(today="2026-08-23").details["generated"]) == 0


def test_the_renewed_term_keeps_counting_from_the_rolled_sequence(
    service: DepositService,
) -> None:
    """從第 3 期記進來的，續存之後是第 4 期，不是第 2 期。"""
    contract_id = _make_contract(
        service,
        interest_method=str(InterestMethod.LUMP_SUM),
        maturity_action=str(MaturityAction.RENEW_PRINCIPAL_ONLY),
        opened_on="2023-11-15",
        recorded_on="2026-08-23",
    )
    service.generate_due(today="2027-02-15")
    event = service.store.list_pending_events()[0]
    assert service.confirm(event.event_id, actual_amount_minor=1_600).success

    sequences = sorted(term.sequence for term in service.store.list_terms(contract_id=contract_id))
    assert sequences == [3, 4]


def test_a_deposit_that_does_not_renew_is_recorded_as_the_term_on_the_passbook(
    service: DepositService,
) -> None:
    """不續存的沒有「目前這一期」—— 記進來的就是存單上那一期，期序 1。

    它已經結束了，所以也不會產生任何待確認項目（到期日早於建檔日）。
    """
    contract_id = _make_contract(
        service,
        interest_method=str(InterestMethod.LUMP_SUM),
        maturity_action=str(MaturityAction.NONE),
        opened_on="2023-11-15",
        recorded_on="2026-08-23",
    )

    terms = service.store.list_terms(contract_id=contract_id)
    assert (terms[0].start_date, terms[0].sequence) == ("2023-11-15", 1)
    assert int(service.generate_due(today="2026-08-23").details["generated"]) == 0
