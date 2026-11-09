"""稅務 application service、設定與參考資料日期的整合測試。"""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import sqlite3

import pytest

from tagcor_ledger.app.paths import AppPaths, resolve_app_paths
from tagcor_ledger.application.failures import ERROR_MESSAGES
from tagcor_ledger.application.reference import ReferenceLibrary
from tagcor_ledger.application.settings import SettingsService
from tagcor_ledger.application.tax import TaxService
from tagcor_ledger.application.tax.loader import load_tax_dataset
from tagcor_ledger.domain.money import Money
from tagcor_ledger.domain.tax.dataset_validate import validate_tax_dataset
from tagcor_ledger.domain.tax.freshness import DatasetLoadState
from tagcor_ledger.domain.tax.kinds import (
    DeductionChoice,
    FilingStatus,
    Flow,
    IncomeKind,
    ReminderMark,
    TaxKind,
)
from tagcor_ledger.domain.tax.records import TaxYearInputs, TaxYearOverride
from tagcor_ledger.domain.tax.reminders import ReminderState, ReminderSwitch
from tagcor_ledger.infrastructure.database import connect_database, database_transaction
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


SAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "tax" / "sample.json"


@pytest.fixture
def tax_app(tmp_path: Path) -> tuple[AppPaths, LedgerStore, TaxService]:
    paths = resolve_app_paths(tmp_path / "ledger")
    store = LedgerStore(paths)
    service = TaxService(
        paths,
        store,
        dataset_path=SAMPLE,
        reference=ReferenceLibrary(tmp_path / "missing-reference.sqlite3"),
    )
    return paths, store, service


def _transaction(
    store: LedgerStore,
    *,
    transaction_id: str,
    entry_type: str,
    category_id: str,
    amount: int,
    occurred_on: str,
) -> str:
    record = store.create_transaction(
        transaction_id=transaction_id,
        entry_type=entry_type,
        occurred_at=f"{occurred_on}T12:00:00+08:00",
        money=Money(amount, "TWD"),
        account_id="acct_cash",
        category_id=category_id,
        description=transaction_id,
        source="manual",
        correlation_id=f"corr_{transaction_id}",
    )
    return record.transaction_id


def _inputs(year: int, *, official: int | None = None) -> TaxYearInputs:
    return TaxYearInputs(
        income_year=year,
        filing=FilingStatus.SINGLE,
        deduction=DeductionChoice.STANDARD,
        other_special_deductions=False,
        dependents_have_income=False,
        filer_70_plus=False,
        dependents=0,
        dependents_70_plus=0,
        official_tax_minor=official,
        official_balance_minor=11 if official is not None else None,
    )


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_tax_dataset_loader_states_and_json_error_location(tmp_path: Path) -> None:
    missing = load_tax_dataset(tmp_path / "absent.json")
    assert missing.state is DatasetLoadState.MISSING
    unreadable = load_tax_dataset(tmp_path)
    assert unreadable.state is DatasetLoadState.INVALID
    assert unreadable.problems == ("稅務資料讀不開。",)

    bom = tmp_path / "bom.json"
    bom.write_bytes(b"\xef\xbb\xbf{}")
    assert load_tax_dataset(bom).problems == ("稅務資料含有 UTF-8 BOM。",)

    broken = tmp_path / "broken.json"
    broken.write_text('{\n  "bad": ]\n}', encoding="utf-8")
    invalid_json = load_tax_dataset(broken)
    assert invalid_json.state is DatasetLoadState.INVALID
    assert "第 2 行第 10 欄" in invalid_json.problems[0]

    raw = _load_json(SAMPLE)
    raw["schema_version"] = 2
    invalid_data = tmp_path / "invalid.json"
    invalid_data.write_text(json.dumps(raw), encoding="utf-8")
    expected = tuple(validate_tax_dataset(raw))
    loaded = load_tax_dataset(invalid_data)
    assert loaded.state is DatasetLoadState.INVALID
    assert loaded.problems == expected

    valid = load_tax_dataset(SAMPLE)
    assert valid.state is DatasetLoadState.OK
    assert valid.dataset is not None
def test_dataset_cache_reloads_only_when_stat_signature_changes(
    tax_app: tuple[AppPaths, LedgerStore, TaxService],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from tagcor_ledger.application.tax import base

    _, _, service = tax_app
    original = base.load_tax_dataset
    calls = 0

    def counted(path: Path):
        nonlocal calls
        calls += 1
        return original(path)

    monkeypatch.setattr(base, "load_tax_dataset", counted)
    assert service.dataset_load().state is DatasetLoadState.OK
    assert service.dataset_load().state is DatasetLoadState.OK
    assert calls == 1

    source = SAMPLE.read_text(encoding="utf-8")
    changed = tmp_path / "sample.json"
    changed.write_text(source, encoding="utf-8")
    service.dataset_path = changed
    assert service.dataset_load().state is DatasetLoadState.OK
    assert service.dataset_load().state is DatasetLoadState.OK
    assert calls == 2
    changed.write_text(source + "\n", encoding="utf-8")
    assert service.dataset_load().state is DatasetLoadState.OK
    assert calls == 3


def test_reminder_switch_defaults_save_and_invalid_values(
    tax_app: tuple[AppPaths, LedgerStore, TaxService],
) -> None:
    paths, _, service = tax_app
    settings = SettingsService(paths)
    defaults = settings.get_tax_reminder_switches()
    assert defaults == {
        TaxKind.INCOME_TAX: ReminderSwitch.ON,
        TaxKind.HOUSE_TAX: ReminderSwitch.UNSET,
        TaxKind.LAND_VALUE_TAX: ReminderSwitch.UNSET,
        TaxKind.VEHICLE_LICENSE_TAX: ReminderSwitch.UNSET,
        TaxKind.FUEL_FEE: ReminderSwitch.UNSET,
    }

    assert service.save_reminder_switch(TaxKind.HOUSE_TAX, ReminderSwitch.ON).success
    assert service.save_reminder_switch(TaxKind.INCOME_TAX, ReminderSwitch.OFF).success
    assert service.reminder_switches()[TaxKind.HOUSE_TAX] is ReminderSwitch.ON
    assert service.reminder_switches()[TaxKind.INCOME_TAX] is ReminderSwitch.OFF

    with database_transaction(paths.database_path) as connection:
        connection.execute(
            "UPDATE settings SET value = 'unexpected' WHERE key = 'tax_reminder.house_tax'"
        )
    assert settings.get_tax_reminder_switches()[TaxKind.HOUSE_TAX] is ReminderSwitch.UNSET

    unset = service.save_reminder_switch(TaxKind.HOUSE_TAX, ReminderSwitch.UNSET)
    assert not unset.success
    assert unset.error_code == "TAX_REMINDER_SWITCH_INVALID"
    assert unset.message == ERROR_MESSAGES["TAX_REMINDER_SWITCH_INVALID"]
    unknown = settings.save_tax_reminder_switch("unknown", ReminderSwitch.ON)  # type: ignore[arg-type]
    assert not unknown.success
    assert unknown.error_code == "TAX_KIND_UNKNOWN"
    assert unknown.message == ERROR_MESSAGES["TAX_KIND_UNKNOWN"]


def test_reminder_views_follow_payment_marks_and_last_year_facts(
    tax_app: tuple[AppPaths, LedgerStore, TaxService],
) -> None:
    _, store, service = tax_app
    income_category = store.create_category(name="稅費")
    income_item = store.create_category(name="綜所稅", parent_id=income_category.category_id)
    service.set_mapping(
        category_id=income_item.category_id,
        flow=Flow.EXPENSE,
        tax_kind=TaxKind.INCOME_TAX.value,
    )
    house_category = store.create_category(name="房屋稅")
    service.set_mapping(
        category_id=house_category.category_id,
        flow=Flow.EXPENSE,
        tax_kind=TaxKind.HOUSE_TAX.value,
    )
    service.save_reminder_switch(TaxKind.HOUSE_TAX, ReminderSwitch.ON)

    def view(kind: TaxKind, today: date):
        return next(item for item in service.reminder_views(today=today) if item.kind is kind)

    assert view(TaxKind.INCOME_TAX, date(2026, 5, 10)).state is ReminderState.OPEN
    transaction_id = _transaction(
        store,
        transaction_id="txn_income_tax_payment",
        entry_type="expense",
        category_id=income_item.category_id,
        amount=100_000,
        occurred_on="2026-05-12",
    )
    assert view(TaxKind.INCOME_TAX, date(2026, 5, 15)).state is ReminderState.PAID
    store.delete_transaction(transaction_id, "corr_delete_income_tax_payment")
    assert view(TaxKind.INCOME_TAX, date(2026, 5, 15)).state is ReminderState.OPEN

    assert service.set_reminder_mark(
        TaxKind.INCOME_TAX, 2026, ReminderMark.HANDLED
    ).success
    assert view(TaxKind.INCOME_TAX, date(2026, 5, 15)).state is ReminderState.HANDLED
    assert service.set_reminder_mark(TaxKind.INCOME_TAX, 2026, None).success
    assert view(TaxKind.INCOME_TAX, date(2026, 5, 15)).state is ReminderState.OPEN

    _transaction(
        store,
        transaction_id="txn_house_tax_last_year",
        entry_type="expense",
        category_id=house_category.category_id,
        amount=5_000,
        occurred_on="2025-05-20",
    )
    house = view(TaxKind.HOUSE_TAX, date(2026, 5, 10))
    assert house.last_year_paid is not None
    assert house.last_year_paid.count == 1


def test_reminders_are_silent_when_dataset_is_unavailable(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger")
    store = LedgerStore(paths)
    service = TaxService(paths, store, dataset_path=tmp_path / "missing.json")
    assert service.reminder_views(today=date(2026, 5, 10)) == ()


def test_estimate_refuses_unavailable_dataset_and_unmapped_income(
    tmp_path: Path,
) -> None:
    paths = resolve_app_paths(tmp_path / "ledger")
    store = LedgerStore(paths)
    unavailable = TaxService(paths, store, dataset_path=tmp_path / "missing.json")
    assert "dataset_unavailable" in {reason.value for reason in unavailable.estimate(2025).refused}

    service = TaxService(paths, store, dataset_path=SAMPLE)
    category = store.create_category(name="未歸類收入")
    _transaction(
        store,
        transaction_id="txn_unmapped_income",
        entry_type="income",
        category_id=category.category_id,
        amount=100,
        occurred_on="2025-01-01",
    )
    assert "unmapped_income" in {reason.value for reason in service.estimate(2025).refused}


def test_estimate_uses_ledger_interest_withheld_tax_and_manual_slip(
    tax_app: tuple[AppPaths, LedgerStore, TaxService],
) -> None:
    paths, store, service = tax_app
    salary = store.create_category(name="薪資")
    service.set_mapping(
        category_id=salary.category_id, flow=Flow.INCOME, tax_kind=IncomeKind.SALARY.value
    )
    for month in range(1, 13):
        _transaction(
            store,
            transaction_id=f"txn_salary_{month}",
            entry_type="income",
            category_id=salary.category_id,
            amount=100_000,
            occurred_on=f"2025-{month:02d}-15",
        )
    assert service.save_tax_year_override(
        TaxYearOverride(2025, IncomeKind.SALARY, 1_200_000, 30_000)
    ).success
    assert service.save_tax_year_inputs(_inputs(2025)).success

    deposits = __import__("tagcor_ledger.application.deposits", fromlist=["DepositService"])
    deposit_service = deposits.DepositService(paths, store)
    created = deposit_service.create_contract(
        account_id="acct_cash",
        name="測試存本取息",
        interest_method="monthly_interest",
        maturity_action="none",
        interest_destination_account_id="acct_cash",
        term_months=12,
        opened_on="2025-01-01",
        principal="3000000",
        annual_rate_ppm=120_000,
        recorded_on="2025-01-01",
    )
    assert created.success, created.message
    assert deposit_service.generate_due(today="2025-02-01").success
    event = store.list_pending_events()[0]
    confirmed = deposit_service.confirm(
        event.event_id, actual_amount_minor=26_367, occurred_on="2025-02-01"
    )
    assert confirmed.success, confirmed.message
    interest_category = next(item for item in store.list_categories() if item.name == "利息收入")
    interest_item = store.list_categories(parent_id=interest_category.category_id)[0]
    service.set_mapping(
        category_id=interest_item.category_id,
        flow=Flow.INCOME,
        tax_kind=IncomeKind.INTEREST_TAXABLE.value,
    )
    transaction_id = str(confirmed.details["transaction_id"])
    with connect_database(paths.database_path) as connection:
        connection.execute(
            """UPDATE deposit_events
               SET withheld_tax_minor = 3000, nhi_premium_minor = 633
               WHERE transaction_id = ?""",
            (transaction_id,),
        )

    estimate = service.estimate(2025)
    assert not estimate.refused
    by_key = {line.step.value: line.amount_minor for line in estimate.lines}
    assert by_key["interest"] == 30_000
    assert by_key["gross_income"] == 930_000
    assert by_key["savings_deduction"] == 30_000
    assert by_key["basic_living"] == 170_000
    assert by_key["net_income"] == 430_000
    assert estimate.tax_minor == 21_500
    assert estimate.withheld_minor == 33_000
    assert estimate.balance_minor == -11_500


def test_filing_prefills_last_year_without_carrying_official_results(
    tax_app: tuple[AppPaths, LedgerStore, TaxService],
) -> None:
    _, store, service = tax_app
    prior = _inputs(2025, official=12_345)
    assert service.save_tax_year_inputs(prior).success
    prefilled = service.prefilled_inputs(2026)
    assert prefilled is not None
    assert prefilled.income_year == 2026
    assert prefilled.official_tax_minor is None
    assert prefilled.official_balance_minor is None
    assert store.get_tax_year_inputs(2026) is None
    current = _inputs(2026, official=543)
    assert service.save_tax_year_inputs(current).success
    assert service.prefilled_inputs(2026) == current


def test_filing_write_results_cover_success_and_known_store_failures(
    tax_app: tuple[AppPaths, LedgerStore, TaxService],
) -> None:
    _, _, service = tax_app
    assert service.save_tax_year_inputs(_inputs(2025)).success
    invalid_inputs = service.save_tax_year_inputs(
        TaxYearInputs(
            income_year=2026,
            filing=FilingStatus.SINGLE,
            deduction=DeductionChoice.STANDARD,
            other_special_deductions=False,
            dependents_have_income=False,
            filer_70_plus=False,
            dependents=-1,
            dependents_70_plus=0,
            official_tax_minor=None,
            official_balance_minor=None,
        )
    )
    assert not invalid_inputs.success
    assert invalid_inputs.message == ERROR_MESSAGES["TAX_INPUTS_INVALID"]

    valid_override = TaxYearOverride(2025, IncomeKind.SALARY, 1_000, 50)
    assert service.save_tax_year_override(valid_override).success
    invalid_override = service.save_tax_year_override(
        TaxYearOverride(2025, IncomeKind.OTHER_INCOME, 1_000, 50)
    )
    assert not invalid_override.success
    assert invalid_override.message == ERROR_MESSAGES["TAX_OVERRIDE_KIND_INVALID"]

    store = service.store
    category = store.create_category(name="分類測試")
    assert service.set_mapping(
        category_id=category.category_id,
        flow=Flow.INCOME,
        tax_kind=IncomeKind.SALARY.value,
    ).success
    invalid_mapping = service.set_mapping(
        category_id=category.category_id,
        flow=Flow.INCOME,
        tax_kind=TaxKind.HOUSE_TAX.value,
    )
    assert not invalid_mapping.success
    assert invalid_mapping.message == ERROR_MESSAGES["TAX_MAPPING_KIND_INVALID"]


def test_default_income_year_requires_both_parameter_sequences(
    tmp_path: Path,
) -> None:
    raw = _load_json(SAMPLE)
    path = tmp_path / "dataset.json"
    paths = resolve_app_paths(tmp_path / "ledger")
    service = TaxService(paths, dataset_path=path)
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert service.default_income_year(today=date(2026, 11, 9)) == 2026

    raw["basic_living_expense"].pop("2026")
    path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    assert service.default_income_year(today=date(2026, 11, 9)) == 2025

    missing = TaxService(paths, dataset_path=tmp_path / "missing.json")
    assert missing.default_income_year(today=date(2026, 11, 9)) == 2025


def test_data_status_and_interest_deductions_use_usable_dataset(
    tax_app: tuple[AppPaths, LedgerStore, TaxService], tmp_path: Path
) -> None:
    _, _, service = tax_app
    status = service.data_status(today=date(2026, 5, 10))
    assert status.dataset is not None
    assert status.sources == status.dataset.sources
    assert status.problems == ()
    deductions = service.interest_deductions(30_000, on=date(2025, 2, 1))
    assert deductions is not None
    assert deductions.withheld_tax_minor == 3_000
    assert deductions.nhi_premium_minor == 633

    paths = resolve_app_paths(tmp_path / "missing-ledger")
    unavailable = TaxService(paths, dataset_path=tmp_path / "missing.json")
    assert unavailable.interest_deductions(30_000, on=date(2025, 2, 1)) is None


def test_reference_library_oldest_review_date_and_stale_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "reference.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE reference_entries (reviewed_at TEXT NOT NULL)")
        connection.executemany(
            "INSERT INTO reference_entries(reviewed_at) VALUES (?)",
            [("2026-01-02",), ("2025-12-31",)],
        )
    assert ReferenceLibrary(database).oldest_reviewed_at() == date(2025, 12, 31)
    assert ReferenceLibrary(tmp_path / "missing.sqlite3").oldest_reviewed_at() is None

    monkeypatch.setattr(
        "tagcor_ledger.application.reference.today_taipei", lambda: date(2026, 11, 9)
    )
    from tagcor_ledger.application.reference import is_stale

    assert is_stale("2026-05-01")
    assert not is_stale("2026-06-01")


def test_reference_library_returns_none_for_empty_or_invalid_dates(tmp_path: Path) -> None:
    database = tmp_path / "reference.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE reference_entries (reviewed_at TEXT NOT NULL)")
    library = ReferenceLibrary(database)
    assert library.oldest_reviewed_at() is None
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO reference_entries(reviewed_at) VALUES ('not-a-date')")
    assert library.oldest_reviewed_at() is None
