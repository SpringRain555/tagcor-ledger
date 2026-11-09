"""稅務對應、所得與繳款事實查詢。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from tagcor_ledger.app.paths import AppPaths, resolve_app_paths
from tagcor_ledger.application.deposits import DepositService
from tagcor_ledger.domain.money import Money
from tagcor_ledger.domain.tax.kinds import Flow, IncomeKind, TaxKind
from tagcor_ledger.infrastructure.database import connect_database
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore, NotFoundError


@pytest.fixture
def ledger(tmp_path: Path) -> tuple[AppPaths, LedgerStore]:
    paths = resolve_app_paths(tmp_path / "data")
    return paths, LedgerStore(paths)


def _transaction(
    store: LedgerStore,
    *,
    transaction_id: str,
    entry_type: str,
    category_id: str,
    amount: int,
    occurred_at: str,
) -> str:
    store.create_transaction(
        transaction_id=transaction_id,
        entry_type=entry_type,
        occurred_at=occurred_at,
        money=Money(amount, "TWD"),
        account_id="acct_cash",
        category_id=category_id,
        description=transaction_id,
        source="manual",
        correlation_id=f"corr_{transaction_id}",
    )
    return transaction_id


def _insert_deposit_event(
    paths: AppPaths,
    *,
    event_id: str,
    term_id: str,
    transaction_id: str,
    due_date: str,
    status: str,
    withheld: int | None,
    premium: int | None,
) -> None:
    with connect_database(paths.database_path) as connection:
        connection.execute(
            """
            INSERT INTO deposit_events(
                event_id, term_id, event_type, due_date, status, actual_amount_minor,
                transaction_id, note, created_at, updated_at, withheld_tax_minor, nhi_premium_minor
            ) VALUES (?, ?, 'interest_payout', ?, ?, 100, ?, '', ?, ?, ?, ?)
            """,
            (
                event_id,
                term_id,
                due_date,
                status,
                transaction_id,
                "2026-01-01T00:00:00+08:00",
                "2026-01-01T00:00:00+08:00",
                withheld,
                premium,
            ),
        )


def _deposit_term(store: LedgerStore, paths: AppPaths) -> str:
    service = DepositService(paths, store)
    result = service.create_contract(
        account_id="acct_cash",
        name="測試定存",
        interest_method="lump_sum",
        maturity_action="none",
        interest_destination_account_id="acct_cash",
        term_months=12,
        opened_on="2026-01-01",
        principal="1000",
        annual_rate_ppm=16_000,
        recorded_on="2026-01-01",
    )
    assert result.success, result.message
    contract_id = str(result.details["contract_id"])
    return store.list_terms(contract_id=contract_id)[0].term_id


def test_tax_mapping_set_update_clear_and_validation_are_audited_without_amounts(
    ledger: tuple[AppPaths, LedgerStore],
) -> None:
    paths, store = ledger
    category = store.create_category(name="薪資")
    store.set_tax_mapping(
        category_id=category.category_id,
        flow=Flow.INCOME,
        tax_kind=IncomeKind.SALARY.value,
    )
    store.set_tax_mapping(
        category_id=category.category_id,
        flow=Flow.INCOME,
        tax_kind=IncomeKind.PRIZE.value,
    )
    assert store.list_tax_mappings()[0].tax_kind == IncomeKind.PRIZE.value

    with pytest.raises(ValueError, match="TAX_MAPPING_KIND_INVALID"):
        store.set_tax_mapping(
            category_id=category.category_id,
            flow=Flow.INCOME,
            tax_kind=TaxKind.HOUSE_TAX.value,
        )
    with pytest.raises(ValueError, match="TAX_MAPPING_KIND_INVALID"):
        store.set_tax_mapping(
            category_id=category.category_id,
            flow=Flow.EXPENSE,
            tax_kind=IncomeKind.SALARY.value,
        )
    with pytest.raises(NotFoundError, match="CATEGORY_NOT_FOUND"):
        store.set_tax_mapping(category_id="missing", flow=Flow.INCOME, tax_kind=None)
    assert len(store.list_tax_mappings()) == 1

    store.set_tax_mapping(category_id=category.category_id, flow=Flow.INCOME, tax_kind=None)
    assert store.list_tax_mappings() == []
    with connect_database(paths.database_path) as connection:
        audits = connection.execute(
            """
            SELECT action, details_json FROM audit_events
            WHERE action IN ('tax_mapping.set', 'tax_mapping.clear')
            ORDER BY rowid
            """
        ).fetchall()
    assert [str(row["action"]) for row in audits] == [
        "tax_mapping.set",
        "tax_mapping.set",
        "tax_mapping.clear",
    ]
    details = [json.loads(str(row["details_json"])) for row in audits]
    assert details[-1] == {"flow": "income", "tax_kind": None}
    assert all("amount" not in key for entry in details for key in entry)


def test_category_delete_cascades_mapping_but_transactions_still_block_delete(
    ledger: tuple[AppPaths, LedgerStore],
) -> None:
    paths, store = ledger
    disposable = store.create_category(name="可刪項目", parent_id="cat_food")
    store.set_tax_mapping(
        category_id=disposable.category_id,
        flow=Flow.EXPENSE,
        tax_kind=TaxKind.HOUSE_TAX.value,
    )
    store.delete_category(disposable.category_id)
    assert all(row.category_id != disposable.category_id for row in store.list_tax_mappings())

    referenced = store.create_category(name="有交易", parent_id="cat_food")
    store.set_tax_mapping(
        category_id=referenced.category_id,
        flow=Flow.EXPENSE,
        tax_kind=TaxKind.HOUSE_TAX.value,
    )
    _transaction(
        store,
        transaction_id="txn_tax_delete_guard",
        entry_type="expense",
        category_id=referenced.category_id,
        amount=500,
        occurred_at="2026-04-01T12:00:00+08:00",
    )
    with pytest.raises(ValueError, match="CATEGORY_HAS_TRANSACTIONS"):
        store.delete_category(referenced.category_id)
    with connect_database(paths.database_path) as connection:
        mapping = connection.execute(
            "SELECT 1 FROM tax_category_mappings WHERE category_id = ?", (referenced.category_id,)
        ).fetchone()
    assert mapping is not None


def test_income_totals_apply_item_override_year_boundary_and_confirmed_deposit_events(
    ledger: tuple[AppPaths, LedgerStore],
) -> None:
    paths, store = ledger
    interest = store.create_category(name="利息收入")
    taxable_item = store.create_category(name="定存利息", parent_id=interest.category_id)
    unclassified = store.create_category(name="未歸類")
    archived = store.create_category(name="封存收入")
    store.set_tax_mapping(
        category_id=interest.category_id,
        flow=Flow.INCOME,
        tax_kind=IncomeKind.INTEREST_TAXABLE.value,
    )
    store.set_tax_mapping(
        category_id=taxable_item.category_id,
        flow=Flow.INCOME,
        tax_kind=IncomeKind.INTEREST_EXEMPT.value,
    )
    store.set_tax_mapping(
        category_id=archived.category_id,
        flow=Flow.INCOME,
        tax_kind=IncomeKind.SALARY.value,
    )

    taxable_id = _transaction(
        store,
        transaction_id="txn_taxable_interest",
        entry_type="income",
        category_id=interest.category_id,
        amount=31,
        occurred_at="2026-12-31T23:59:00+08:00",
    )
    exempt_id = _transaction(
        store,
        transaction_id="txn_exempt_interest",
        entry_type="income",
        category_id=taxable_item.category_id,
        amount=200,
        occurred_at="2026-12-31T23:59:00+08:00",
    )
    _transaction(
        store,
        transaction_id="txn_next_year_interest",
        entry_type="income",
        category_id=taxable_item.category_id,
        amount=300,
        occurred_at="2027-01-01T00:00:00+08:00",
    )
    _transaction(
        store,
        transaction_id="txn_unmapped_income",
        entry_type="income",
        category_id=unclassified.category_id,
        amount=70,
        occurred_at="2026-05-10T09:00:00+08:00",
    )
    _transaction(
        store,
        transaction_id="txn_archived_income",
        entry_type="income",
        category_id=archived.category_id,
        amount=50,
        occurred_at="2026-06-01T09:00:00+08:00",
    )
    _transaction(
        store,
        transaction_id="txn_expense_not_income",
        entry_type="expense",
        category_id=taxable_item.category_id,
        amount=900,
        occurred_at="2026-06-01T09:00:00+08:00",
    )
    other_account = store.create_account(name="另一帳戶")
    store.create_transfer(
        transaction_id="txn_transfer_not_income",
        occurred_at="2026-06-01T09:00:00+08:00",
        money=Money(1_000, "TWD"),
        source_account_id="acct_cash",
        destination_account_id=other_account.account_id,
        description="轉帳",
        correlation_id="corr_tax_transfer",
    )
    store.archive_category(archived.category_id)

    term_id = _deposit_term(store, paths)
    _insert_deposit_event(
        paths,
        event_id="devt_tax_confirmed_taxable",
        term_id=term_id,
        transaction_id=taxable_id,
        due_date="2026-12-10",
        status="confirmed",
        withheld=3,
        premium=7,
    )
    _insert_deposit_event(
        paths,
        event_id="devt_tax_confirmed_exempt",
        term_id=term_id,
        transaction_id=exempt_id,
        due_date="2026-12-11",
        status="confirmed",
        withheld=5,
        premium=11,
    )
    _insert_deposit_event(
        paths,
        event_id="devt_tax_pending_exempt",
        term_id=term_id,
        transaction_id=exempt_id,
        due_date="2026-12-12",
        status="pending",
        withheld=900,
        premium=900,
    )

    totals = store.income_totals(2026)
    assert totals.total(IncomeKind.INTEREST_TAXABLE).count == 1
    assert totals.total(IncomeKind.INTEREST_TAXABLE).net_minor == 31
    assert totals.total(IncomeKind.INTEREST_TAXABLE).withheld_tax_minor == 3
    assert totals.total(IncomeKind.INTEREST_TAXABLE).nhi_premium_minor == 7
    assert totals.total(IncomeKind.INTEREST_EXEMPT).count == 1
    assert totals.total(IncomeKind.INTEREST_EXEMPT).net_minor == 200
    assert totals.total(IncomeKind.INTEREST_EXEMPT).withheld_tax_minor == 5
    assert totals.total(IncomeKind.INTEREST_EXEMPT).nhi_premium_minor == 11
    assert totals.total(IncomeKind.SALARY).net_minor == 50
    assert totals.unmapped.count == 1
    assert totals.unmapped.net_minor == 70


def test_payment_fact_uses_item_override_and_inclusive_date_range(
    ledger: tuple[AppPaths, LedgerStore],
) -> None:
    _paths, store = ledger
    property_tax = store.create_category(name="房屋稅")
    inherited = store.create_category(name="年繳", parent_id=property_tax.category_id)
    override = store.create_category(name="其他稅", parent_id=property_tax.category_id)
    store.set_tax_mapping(
        category_id=property_tax.category_id,
        flow=Flow.EXPENSE,
        tax_kind=TaxKind.HOUSE_TAX.value,
    )
    store.set_tax_mapping(
        category_id=override.category_id,
        flow=Flow.EXPENSE,
        tax_kind=TaxKind.FUEL_FEE.value,
    )
    for transaction_id, category_id, amount, occurred_at in (
        ("txn_house_tax_1", property_tax.category_id, 100, "2026-05-01T00:00:00+08:00"),
        ("txn_house_tax_2", inherited.category_id, 250, "2026-05-31T23:59:00+08:00"),
        ("txn_house_tax_outside", inherited.category_id, 500, "2026-06-01T00:00:00+08:00"),
        ("txn_fuel_fee", override.category_id, 700, "2026-05-15T12:00:00+08:00"),
    ):
        _transaction(
            store,
            transaction_id=transaction_id,
            entry_type="expense",
            category_id=category_id,
            amount=amount,
            occurred_at=occurred_at,
        )
    _transaction(
        store,
        transaction_id="txn_house_tax_income",
        entry_type="income",
        category_id=property_tax.category_id,
        amount=900,
        occurred_at="2026-05-20T12:00:00+08:00",
    )

    fact = store.payment_fact(TaxKind.HOUSE_TAX, start=date(2026, 5, 1), end=date(2026, 5, 31))
    assert fact.count == 2
    assert fact.total_minor == 350
    assert fact.last_on == "2026-05-31"


def test_mapping_rows_sort_unmapped_first_and_include_archived_history(
    ledger: tuple[AppPaths, LedgerStore],
) -> None:
    _paths, store = ledger
    mapped_parent = store.create_category(name="薪資類別")
    inherited_item = store.create_category(name="固定薪資", parent_id=mapped_parent.category_id)
    archived_income = store.create_category(name="歷史薪資", parent_id=mapped_parent.category_id)
    archived_empty = store.create_category(name="已封存但無收入", parent_id=mapped_parent.category_id)
    unmapped_parent = store.create_category(name="無對應類別")
    unmapped_item = store.create_category(name="未知收入", parent_id=unmapped_parent.category_id)
    store.set_tax_mapping(
        category_id=mapped_parent.category_id,
        flow=Flow.INCOME,
        tax_kind=IncomeKind.SALARY.value,
    )
    _transaction(
        store,
        transaction_id="txn_mapping_inherited",
        entry_type="income",
        category_id=inherited_item.category_id,
        amount=100,
        occurred_at="2026-02-01T09:00:00+08:00",
    )
    _transaction(
        store,
        transaction_id="txn_mapping_archived",
        entry_type="income",
        category_id=archived_income.category_id,
        amount=75,
        occurred_at="2026-03-01T09:00:00+08:00",
    )
    _transaction(
        store,
        transaction_id="txn_mapping_unmapped",
        entry_type="income",
        category_id=unmapped_item.category_id,
        amount=50,
        occurred_at="2026-04-01T09:00:00+08:00",
    )
    store.archive_category(archived_income.category_id)
    store.archive_category(archived_empty.category_id)

    rows = store.list_tax_mapping_rows(2026)
    assert rows[0].category_id == unmapped_item.category_id
    assert rows[0].unmapped
    by_id = {row.category_id: row for row in rows}
    parent_row = by_id[mapped_parent.category_id]
    assert parent_row.own_year_count == 0
    assert parent_row.year_count == 2
    assert parent_row.year_minor == 175
    assert by_id[inherited_item.category_id].effective_income_kind is IncomeKind.SALARY
    assert by_id[archived_income.category_id].archived
    assert archived_empty.category_id not in by_id


def test_mapping_rows_include_parent_mappings_for_override_detection(
    ledger: tuple[AppPaths, LedgerStore],
) -> None:
    _paths, store = ledger
    mapped_parent = store.create_category(name="上層有對應")
    mapped_child = store.create_category(name="自己的對應", parent_id=mapped_parent.category_id)
    bare_parent = store.create_category(name="上層沒有對應")
    bare_child = store.create_category(name="沒有覆蓋", parent_id=bare_parent.category_id)
    store.set_tax_mapping(
        category_id=mapped_parent.category_id,
        flow=Flow.INCOME,
        tax_kind=IncomeKind.SALARY.value,
    )
    store.set_tax_mapping(
        category_id=mapped_parent.category_id,
        flow=Flow.EXPENSE,
        tax_kind=TaxKind.HOUSE_TAX.value,
    )
    store.set_tax_mapping(
        category_id=mapped_child.category_id,
        flow=Flow.INCOME,
        tax_kind=IncomeKind.INTEREST_TAXABLE.value,
    )

    rows = {row.category_id: row for row in store.list_tax_mapping_rows(2026)}

    assert rows[mapped_child.category_id].parent_income_kind is IncomeKind.SALARY
    assert rows[mapped_child.category_id].parent_expense_kind is TaxKind.HOUSE_TAX
    assert rows[bare_child.category_id].parent_income_kind is None
    assert rows[bare_child.category_id].parent_expense_kind is None
    assert rows[mapped_parent.category_id].parent_income_kind is None
    assert rows[mapped_parent.category_id].parent_expense_kind is None


def test_moving_item_keeps_own_mapping_and_changes_inherited_mapping(
    ledger: tuple[AppPaths, LedgerStore],
) -> None:
    _paths, store = ledger
    old_parent = store.create_category(name="舊類別")
    new_parent = store.create_category(name="新類別")
    own_item = store.create_category(name="自己的歸類", parent_id=old_parent.category_id)
    inherited_item = store.create_category(name="沿用歸類", parent_id=old_parent.category_id)
    store.set_tax_mapping(
        category_id=old_parent.category_id,
        flow=Flow.INCOME,
        tax_kind=IncomeKind.SALARY.value,
    )
    store.set_tax_mapping(
        category_id=new_parent.category_id,
        flow=Flow.INCOME,
        tax_kind=IncomeKind.PRIZE.value,
    )
    store.set_tax_mapping(
        category_id=own_item.category_id,
        flow=Flow.INCOME,
        tax_kind=IncomeKind.INTEREST_EXEMPT.value,
    )
    _transaction(
        store,
        transaction_id="txn_own_mapping",
        entry_type="income",
        category_id=own_item.category_id,
        amount=30,
        occurred_at="2026-06-01T09:00:00+08:00",
    )
    _transaction(
        store,
        transaction_id="txn_inherited_mapping",
        entry_type="income",
        category_id=inherited_item.category_id,
        amount=40,
        occurred_at="2026-06-02T09:00:00+08:00",
    )

    store.move_category(own_item.category_id, parent_id=new_parent.category_id)
    store.move_category(inherited_item.category_id, parent_id=new_parent.category_id)

    totals = store.income_totals(2026)
    assert totals.total(IncomeKind.INTEREST_EXEMPT).net_minor == 30
    assert totals.total(IncomeKind.PRIZE).net_minor == 40
    assert totals.total(IncomeKind.SALARY).count == 0
