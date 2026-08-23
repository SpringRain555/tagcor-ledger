"""定存的利率類型、反推年利率，以及修改／刪除。

`test_filling_in_the_rate_later_is_possible` 對應 go-live runbook 裡那句「查到牌告利率
再回來補」—— **在加上修改功能之前，那句話是做不到的**，runbook 寫了一個不存在的操作。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.application.deposits import DepositService
from tagcor_ledger.domain.deposits import (
    InterestMethod,
    MaturityAction,
    derive_annual_rate_ppm,
    suggest_interest_minor,
)
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


RATE_1_60_PERCENT = 16_000


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
    maturity_action: str = str(MaturityAction.NONE),
    rate: int | None = RATE_1_60_PERCENT,
    rate_type: str = "fixed",
) -> str:
    deposit_id, savings_id = _accounts(service)
    result = service.create_contract(
        account_id=deposit_id,
        name="郵局定存",
        interest_method=str(InterestMethod.LUMP_SUM),
        maturity_action=maturity_action,
        interest_destination_account_id=savings_id,
        term_months=12,
        opened_on="2026-02-15",
        principal="100000",
        annual_rate_ppm=rate,
        rate_type=rate_type,
        # 建檔日 = 起存日。`recorded_on` 是產生待確認項目的下界（ADR-0012），
        # 留成預設的今天會讓這個檔案的假日期在真實時鐘走過去之後開始漏測。
        recorded_on="2026-02-15",
    )
    assert result.success, result.message
    return str(result.details["contract_id"])


# --- 利率類型 ---------------------------------------------------------------


def test_floating_rate_never_stores_a_guessed_number(service: DepositService) -> None:
    """機動利率**不預先填數字**。存的當下填的值，到期時多半已經不是那個值了。"""
    contract_id = _make_contract(service, rate_type="floating", rate=RATE_1_60_PERCENT)
    term = service.store.list_terms(contract_id=contract_id)[0]
    assert term.annual_rate_ppm is None, "機動利率不該存下一個會過期的數字"
    assert service.store.get_contract(contract_id).rate_type == "floating"


def test_fixed_rate_keeps_what_was_entered(service: DepositService) -> None:
    contract_id = _make_contract(service, rate_type="fixed")
    term = service.store.list_terms(contract_id=contract_id)[0]
    assert term.annual_rate_ppm == RATE_1_60_PERCENT


# --- 從實際利息反推 ---------------------------------------------------------


def test_confirming_derives_the_effective_rate(service: DepositService) -> None:
    """實際利息才是事實，年利率由它反推。機動利率時這是唯一有意義的利率紀錄。"""
    contract_id = _make_contract(service, rate=None, rate_type="floating")
    service.generate_due(today="2027-02-15")
    event = service.store.list_pending_events()[0]

    assert service.confirm(event.event_id, actual_amount_minor=1_612).success

    term = service.store.list_terms(contract_id=contract_id)[0]
    assert term.actual_interest_minor == 1_612
    assert term.effective_rate_ppm is not None
    # 10 萬本金、一年按月複利拿到 1,612 元，約當年利率 1.6%。
    assert 15_900 <= term.effective_rate_ppm <= 16_100


@pytest.mark.parametrize("interest_method", list(InterestMethod))
def test_derivation_round_trips_with_the_forward_calculation(
    interest_method: InterestMethod,
) -> None:
    """反推是正推的反函數 —— 共用同一套進位規則，不會各說各話。"""
    installment = interest_method is InterestMethod.INSTALLMENT_SAVINGS
    monthly = 3_000 if installment else None
    principal = 0 if installment else 100_000

    interest = suggest_interest_minor(
        interest_method=str(interest_method),
        principal_minor=principal,
        annual_rate_ppm=RATE_1_60_PERCENT,
        term_months=12,
        monthly_deposit_minor=monthly,
    )
    assert interest is not None and interest > 0

    derived = derive_annual_rate_ppm(
        interest_method=str(interest_method),
        principal_minor=principal,
        interest_minor=interest,
        term_months=12,
        monthly_deposit_minor=monthly,
    )
    assert derived is not None
    # 利息進位到元會損失精度，容許小幅偏差。
    assert abs(derived - RATE_1_60_PERCENT) < 500


def test_absurd_interest_yields_no_rate() -> None:
    """利息大到超過 100% 年利率，多半是打錯字而不是好運。"""
    assert (
        derive_annual_rate_ppm(
            interest_method=str(InterestMethod.LUMP_SUM),
            principal_minor=100,
            interest_minor=999_999_999,
            term_months=12,
        )
        is None
    )


def test_zero_interest_derives_zero() -> None:
    assert (
        derive_annual_rate_ppm(
            interest_method=str(InterestMethod.LUMP_SUM),
            principal_minor=100_000,
            interest_minor=0,
            term_months=12,
        )
        == 0
    )


# --- 修改每一期 -------------------------------------------------------------


def test_filling_in_the_rate_later_is_possible(service: DepositService) -> None:
    """runbook 叫使用者先留空利率。沒有這條路徑，那句話就是做不到的。"""
    contract_id = _make_contract(service, rate=None)
    term = service.store.list_terms(contract_id=contract_id)[0]
    assert term.annual_rate_ppm is None

    result = service.update_term(
        term.term_id,
        start_date=term.start_date,
        maturity_date=term.maturity_date,
        principal="100000",
        annual_rate_ppm=RATE_1_60_PERCENT,
    )
    assert result.success, result.message
    assert service.store.get_term(term.term_id).annual_rate_ppm == RATE_1_60_PERCENT


def test_changing_the_rate_refreshes_pending_suggestions(service: DepositService) -> None:
    """利率改了，已經排在待確認裡的建議金額就過期了，必須重算而不是留著舊的。"""
    contract_id = _make_contract(service, rate=None)
    service.generate_due(today="2027-02-15")
    assert service.store.list_pending_events()[0].suggested_amount_minor is None

    term = service.store.list_terms(contract_id=contract_id)[0]
    service.update_term(
        term.term_id,
        start_date=term.start_date,
        maturity_date=term.maturity_date,
        principal="100000",
        annual_rate_ppm=RATE_1_60_PERCENT,
    )

    events = service.store.list_pending_events()
    assert len(events) == 1, "重算不該留下重複的待確認項目"
    assert events[0].suggested_amount_minor == 1_612


def test_a_missing_term_does_not_claim_to_be_uneditable(service: DepositService) -> None:
    """期根本不存在時，不要說「只有存續中的期可以修改」。

    以前 `update_term` 有一個 `except NotFoundError:` 無條件回
    `DEPOSIT_TERM_NOT_EDITABLE` —— 但 store 的 `NotFoundError` 有兩種
    （`DEPOSIT_TERM_NOT_EDITABLE` 與 `DEPOSIT_TERM_NOT_FOUND`），於是「找不到」
    被講成「不能改」。使用者會去找一個不存在的期的狀態，而那個期根本不在畫面上。
    """
    _make_contract(service)
    result = service.update_term(
        "term_does_not_exist",
        start_date="2026-02-15",
        maturity_date="2027-02-15",
        principal="100000",
        annual_rate_ppm=None,
    )
    assert not result.success
    assert result.error_code == "DEPOSIT_TERM_NOT_FOUND"
    assert "存續中" not in result.message
    assert "重新整理" in result.message


def test_settled_terms_cannot_be_edited(service: DepositService) -> None:
    _make_contract(service)
    service.generate_due(today="2027-02-15")
    event = service.store.list_pending_events()[0]
    service.confirm(event.event_id, actual_amount_minor=1_600)

    term = service.store.get_term(event.term_id)
    result = service.update_term(
        term.term_id,
        start_date=term.start_date,
        maturity_date=term.maturity_date,
        principal="999",
        annual_rate_ppm=None,
    )
    assert not result.success
    assert result.error_code == "DEPOSIT_TERM_NOT_EDITABLE"
    assert service.store.get_term(term.term_id).principal_minor == 100_000


# --- 修改與刪除合約 ---------------------------------------------------------


def test_contract_edit_only_touches_the_allowed_fields(service: DepositService) -> None:
    """只能改名稱、到期及轉存方式、利息轉入帳戶。"""
    contract_id = _make_contract(service)
    _deposit_id, savings_id = _accounts(service)

    result = service.update_contract(
        contract_id,
        name="郵局定存（改名）",
        maturity_action=str(MaturityAction.RENEW_PRINCIPAL_ONLY),
        interest_destination_account_id=savings_id,
    )
    assert result.success, result.message

    contract = service.store.get_contract(contract_id)
    assert contract.name == "郵局定存（改名）"
    assert contract.maturity_action == MaturityAction.RENEW_PRINCIPAL_ONLY
    # 計息方式與期長不在可改範圍內 —— 它們決定了已產生事件的形狀。
    assert contract.interest_method == InterestMethod.LUMP_SUM
    assert contract.term_months == 12


def test_editing_to_renew_and_interest_allows_empty_destination(
    service: DepositService,
) -> None:
    contract_id = _make_contract(service)
    result = service.update_contract(
        contract_id,
        name="郵局定存",
        maturity_action=str(MaturityAction.RENEW_PRINCIPAL_AND_INTEREST),
        interest_destination_account_id=None,
    )
    assert result.success, result.message


def test_editing_without_destination_is_rejected(service: DepositService) -> None:
    contract_id = _make_contract(service)
    result = service.update_contract(
        contract_id,
        name="郵局定存",
        maturity_action=str(MaturityAction.NONE),
        interest_destination_account_id=None,
    )
    assert not result.success
    assert result.error_code == "DEPOSIT_INTEREST_DESTINATION_REQUIRED"


def test_unused_contract_can_be_deleted(service: DepositService) -> None:
    contract_id = _make_contract(service)
    service.generate_due(today="2027-02-15")
    assert service.store.list_pending_events()

    assert service.delete_contract(contract_id).success
    assert service.store.list_contracts() == []
    assert service.store.list_terms() == []
    assert service.store.list_pending_events() == [], "刪合約要連待確認一起清掉"


def test_contract_with_bookings_cannot_be_deleted(service: DepositService) -> None:
    """已經入帳過就不能刪 —— 刪了帳本裡的交易會失去來歷。"""
    contract_id = _make_contract(service)
    service.generate_due(today="2027-02-15")
    event = service.store.list_pending_events()[0]
    service.confirm(event.event_id, actual_amount_minor=1_600)

    result = service.delete_contract(contract_id)
    assert not result.success
    assert result.error_code == "DEPOSIT_CONTRACT_IN_USE"
    assert "結束合約" in result.message
    assert len(service.store.list_contracts()) == 1


# --- v6 → v7 升級 -----------------------------------------------------------


def test_a_v6_database_upgrades_to_v7(tmp_path: Path) -> None:
    """使用者的資料庫已經跑過 v6 了，新欄位必須靠 v7 才補得上去。

    這也是為什麼 v6 不能就地修改 —— migration 記錄下來就不會再跑第二次。
    """
    import sqlite3

    from tagcor_ledger.infrastructure.database import initialize_database
    from tagcor_ledger.infrastructure.migrations import LATEST_SCHEMA_VERSION

    paths = resolve_app_paths(tmp_path / "data")
    initialize_database(paths)

    # 假裝這是一個只跑到 v6 的舊資料庫。
    with sqlite3.connect(paths.database_path) as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 7")
        connection.execute("ALTER TABLE deposit_contracts DROP COLUMN rate_type")
        connection.execute("ALTER TABLE deposit_terms DROP COLUMN effective_rate_ppm")
        connection.commit()

    initialize_database(paths)

    with sqlite3.connect(paths.database_path) as connection:
        version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        contract_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(deposit_contracts)")
        }
        term_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(deposit_terms)")
        }
    assert version == LATEST_SCHEMA_VERSION
    assert "rate_type" in contract_columns
    assert "effective_rate_ppm" in term_columns


# --- 結束合約與中途解約（v0.24.0）-------------------------------------------


def test_closing_a_contract_takes_it_off_the_list_but_keeps_the_history(
    service: DepositService,
) -> None:
    """**這條是「訊息指向一件做不到的事」的收尾。**

    `DEPOSIT_CONTRACT_IN_USE` 與刪除確認框從 v0.9.0 就寫著「請改用結束合約」，而
    `close_contract()` 只存在於 store 裡 —— application、controller、UI 三層都沒有接它。
    使用者照著訊息去找那顆按鈕，找不到。
    """
    contract_id = _make_contract(service)
    service.generate_due(today="2027-02-15")
    event = service.store.list_pending_events()[0]
    assert service.confirm(event.event_id, actual_amount_minor=1_600).success

    result = service.close_contract(contract_id)

    assert result.success, result.message
    assert service.store.list_contracts() == [], "結束之後預設清單上不該還有它"
    kept = service.store.list_contracts(include_closed=True)
    assert [item.contract_id for item in kept] == [contract_id], "紀錄本身要留著"
    assert kept[0].status == "closed"
    assert service.store.list_terms(contract_id=contract_id), "每一期的紀錄也要留著"


def test_a_contract_with_a_live_term_cannot_be_closed(service: DepositService) -> None:
    """還有錢在裡面就不准關 —— 那筆本金會從清單上消失而帳上不動。"""
    contract_id = _make_contract(service)

    result = service.close_contract(contract_id)

    assert not result.success
    assert result.error_code == "DEPOSIT_CONTRACT_HAS_ACTIVE_TERM"
    assert "中途解約" in result.message, result.message
    assert "DEPOSIT_" not in result.message, f"錯誤碼漏到畫面上了：{result.message}"


def test_terminating_a_term_moves_the_money_and_ends_the_contract(
    service: DepositService,
) -> None:
    """中途解約：本金與利息回到指定帳戶，這一期已解約，合約一起結束。

    **這是定存頁唯一會產生交易的動作。** 到期一律走待確認 —— 但提前解約沒有到期
    事件可以確認（那一期根本還沒到期），所以那條路只能從定存頁走。
    """
    contract_id = _make_contract(service)
    deposit_id, savings_id = _accounts(service)
    term = service.store.list_terms(contract_id=contract_id)[0]

    result = service.terminate_term(
        term.term_id,
        occurred_on="2026-08-20",
        principal_minor=100_000,
        interest_minor=420,
    )

    assert result.success, result.message
    assert service.store.get_term(term.term_id).status == "terminated"
    assert service.store.get_term(term.term_id).actual_interest_minor == 420
    assert service.store.get_contract(contract_id).status == "closed"

    with sqlite3.connect(service.paths.database_path) as connection:
        rows = [
            (str(row[0])[:10], str(row[1]), int(row[2]))
            for row in connection.execute(
                """
                SELECT t.occurred_at, t.description, p.amount_minor
                FROM transactions t
                JOIN account_postings p ON p.transaction_id = t.transaction_id
                WHERE p.account_id = ?
                """,
                (savings_id,),
            )
        ]
    assert ("2026-08-20", "郵局定存 解約本金", 100_000) in rows, rows
    assert ("2026-08-20", "郵局定存 解約利息", 420) in rows, rows
    assert deposit_id  # 本金那一筆是從定存帳戶轉出去的，上面已經在對面看到了


def test_terminating_without_interest_writes_only_the_principal(
    service: DepositService,
) -> None:
    """存不到一個月就解約可能是真的沒有利息。**0 元的收入不該被記成一筆交易。**"""
    contract_id = _make_contract(service)
    term = service.store.list_terms(contract_id=contract_id)[0]

    assert service.terminate_term(
        term.term_id, occurred_on="2026-03-01", principal_minor=100_000, interest_minor=0
    ).success

    with sqlite3.connect(service.paths.database_path) as connection:
        descriptions = [
            str(row[0]) for row in connection.execute("SELECT description FROM transactions")
        ]
    assert descriptions == ["郵局定存 解約本金"], descriptions


def test_a_term_that_is_no_longer_active_cannot_be_terminated(
    service: DepositService,
) -> None:
    """已結清／已續約／已解約的期都不能再解約一次。"""
    contract_id = _make_contract(service)
    term = service.store.list_terms(contract_id=contract_id)[0]
    assert service.terminate_term(
        term.term_id, occurred_on="2026-03-01", principal_minor=100_000, interest_minor=0
    ).success

    result = service.terminate_term(
        term.term_id, occurred_on="2026-04-01", principal_minor=100_000, interest_minor=0
    )

    assert not result.success
    assert result.error_code == "DEPOSIT_TERM_NOT_ACTIVE"
    assert "DEPOSIT_" not in result.message, f"錯誤碼漏到畫面上了：{result.message}"


def test_terminating_refuses_negative_amounts(service: DepositService) -> None:
    contract_id = _make_contract(service)
    term = service.store.list_terms(contract_id=contract_id)[0]

    result = service.terminate_term(
        term.term_id, occurred_on="2026-03-01", principal_minor=-1, interest_minor=0
    )

    assert not result.success
    assert result.error_code == "DEPOSIT_AMOUNT_INVALID"


# --- v8 → v9 升級 -----------------------------------------------------------


def test_a_v8_database_upgrades_to_v9_and_backfills_the_record_date(tmp_path: Path) -> None:
    """`recorded_on` 是新的一欄，既有合約用 `created_at` 的日期部分回填。

    回填得對很重要：留空的話那份合約的下界會是空字串（比任何日期都小），
    等於**沒有下界** —— 使用者升級之後第一次開程式就會被灌一堆歷史項目。
    """
    import sqlite3

    from tagcor_ledger.infrastructure.database import initialize_database
    from tagcor_ledger.infrastructure.migrations import LATEST_SCHEMA_VERSION

    paths = resolve_app_paths(tmp_path / "data")
    initialize_database(paths)
    store = LedgerStore(paths)
    store.create_account(name="郵局活儲")
    store.create_account(name="郵局定存")
    accounts = {item.name: item.account_id for item in store.list_accounts()}
    contract = store.create_contract(
        account_id=accounts["郵局定存"],
        name="郵局定存",
        interest_method=str(InterestMethod.LUMP_SUM),
        maturity_action=str(MaturityAction.NONE),
        interest_destination_account_id=accounts["郵局活儲"],
        term_months=12,
    )

    # 假裝這是一個只跑到 v8 的舊資料庫：沒有 recorded_on，只有 created_at。
    with sqlite3.connect(paths.database_path) as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 9")
        connection.execute("ALTER TABLE deposit_contracts DROP COLUMN recorded_on")
        connection.execute(
            "UPDATE deposit_contracts SET created_at = '2024-03-09T10:00:00+08:00'"
        )
        connection.commit()

    initialize_database(paths)

    with sqlite3.connect(paths.database_path) as connection:
        version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    assert version == LATEST_SCHEMA_VERSION
    assert LedgerStore(paths).get_contract(contract.contract_id).recorded_on == "2024-03-09"


def test_the_contract_list_knows_which_account_it_is(service: DepositService) -> None:
    """定存頁的「帳戶」欄要有東西。

    **它從 v0.9.0 空到 v0.23.0。** `_contract_view()` 沒有 `account_name` 這個 key，
    而 `deposit_contract_values()` 寫的是 `item.get("account_name", "")` —— 那個預設值
    把「漏了一個欄位」變成了合法輸出，於是一整欄的空白一路活著沒有人發現，
    直到 2026-08-23 看實機截圖。

    現在名字由 store 的 LEFT JOIN 帶進來（比照 `DepositEvent.contract_name`），
    而 formatter 改用下標 —— 再漏就是 `KeyError`，不是一欄空白。
    """
    contract_id = _make_contract(service)

    listed = service.store.list_contracts()
    assert [item.account_name for item in listed] == ["郵局定存"]
    assert service.store.get_contract(contract_id).account_name == "郵局定存"

    view = service.list_contracts().details["contracts"][0]
    assert view["account_name"] == "郵局定存"


def test_a_v9_database_upgrades_to_v10_and_backfills_the_passbook_date(tmp_path: Path) -> None:
    """`opened_on` 是新的一欄，既有合約用**第一期的起存日**回填。

    那是當時唯一存在的事實 —— 在這一欄出現之前填進去的就是一期，沒有滾期這回事。
    """
    from tagcor_ledger.infrastructure.database import initialize_database
    from tagcor_ledger.infrastructure.migrations import LATEST_SCHEMA_VERSION

    paths = resolve_app_paths(tmp_path / "data")
    initialize_database(paths)
    store = LedgerStore(paths)
    store.create_account(name="郵局活儲")
    store.create_account(name="郵局定存")
    accounts = {item.name: item.account_id for item in store.list_accounts()}
    contract = store.create_contract(
        account_id=accounts["郵局定存"],
        name="郵局定存",
        interest_method=str(InterestMethod.LUMP_SUM),
        maturity_action=str(MaturityAction.NONE),
        interest_destination_account_id=accounts["郵局活儲"],
        term_months=12,
        opened_on="2026-02-15",
    )
    store.create_term(
        contract_id=contract.contract_id,
        sequence=1,
        start_date="2026-02-15",
        maturity_date="2027-02-15",
        principal_minor=100_000,
        annual_rate_ppm=RATE_1_60_PERCENT,
    )

    # 假裝這是一個只跑到 v9 的舊資料庫：沒有 opened_on，只有第一期的起存日。
    with sqlite3.connect(paths.database_path) as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 10")
        connection.execute("ALTER TABLE deposit_contracts DROP COLUMN opened_on")
        connection.commit()

    initialize_database(paths)

    with sqlite3.connect(paths.database_path) as connection:
        version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    assert version == LATEST_SCHEMA_VERSION
    assert LedgerStore(paths).get_contract(contract.contract_id).opened_on == "2026-02-15"
