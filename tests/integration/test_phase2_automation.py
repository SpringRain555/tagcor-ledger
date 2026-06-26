from __future__ import annotations

from datetime import date
from pathlib import Path

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.application.automation import AutomationService
from tagcor_ledger.domain.models import RecurringSchedule
from tagcor_ledger.infrastructure.automation_store import next_due_date
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


def test_templates_support_all_transaction_types_and_optional_amount(
    tmp_path: Path,
) -> None:
    paths = resolve_app_paths(tmp_path / "ledger")
    service = AutomationService(paths)
    LedgerStore(paths).create_account(name="銀行")
    bank_id = LedgerStore(paths).list_accounts()[1].account_id
    templates = [
        service.new_template(
            name="早餐",
            entry_type="expense",
            account_id="acct_cash",
            destination_account_id=None,
            category_id="cat_food_711",
            amount_minor=None,
            description="",
        ),
        service.new_template(
            name="薪水",
            entry_type="income",
            account_id=bank_id,
            destination_account_id=None,
            category_id="cat_food_711",
            amount_minor=50_000,
            description="",
        ),
        service.new_template(
            name="轉現金",
            entry_type="transfer",
            account_id=bank_id,
            destination_account_id="acct_cash",
            category_id=None,
            amount_minor=3_000,
            description="",
        ),
    ]
    for template in templates:
        assert service.save_template(template).success
    loaded = service.list_templates().details["templates"]
    assert {item["entry_type"] for item in loaded} == {
        "expense",
        "income",
        "transfer",
    }
    assert next(item for item in loaded if item["name"] == "早餐")["amount_minor"] is None


def test_recurrence_math_handles_month_end_leap_year_and_intervals() -> None:
    assert next_due_date(date(2025, 1, 31), "monthly", 1, 31) == date(2025, 2, 28)
    assert next_due_date(date(2025, 2, 28), "monthly", 1, 31) == date(2025, 3, 31)
    assert next_due_date(date(2024, 2, 29), "yearly", 1, 29) == date(2025, 2, 28)
    assert next_due_date(date(2027, 2, 28), "yearly", 1, 29) == date(2028, 2, 29)
    assert next_due_date(date(2026, 1, 1), "weekly", 2, 1) == date(2026, 1, 15)


def test_due_generation_is_idempotent_capped_and_preserves_snapshots(
    tmp_path: Path,
) -> None:
    paths = resolve_app_paths(tmp_path / "ledger")
    service = AutomationService(paths)
    schedule = service.new_schedule(
        name="每日餐費",
        entry_type="expense",
        account_id="acct_cash",
        destination_account_id=None,
        category_id="cat_food_711",
        amount_minor=100,
        description="原排程",
        frequency="daily",
        interval_count=1,
        start_date="2020-01-01",
        end_date=None,
    )
    assert service.save_schedule(schedule).success
    first = service.generate_due(through_date="2022-01-01")
    assert first.success
    assert first.details == {"generated": 366, "has_more": True}
    assert len(service.list_pending().details["occurrences"]) == 366

    loaded = service.list_schedules().details["schedules"][0]
    edited = RecurringSchedule(
        **{
            **loaded,
            "description": "新排程",
        }
    )
    assert service.save_schedule(edited).success
    pending = service.list_pending().details["occurrences"]
    assert pending[0]["description"] == "原排程"

    second = service.generate_due(through_date="2022-01-01")
    assert second.success
    assert len(service.list_pending().details["occurrences"]) > 366
    while second.details["has_more"]:
        second = service.generate_due(through_date="2022-01-01")
    count = len(service.list_pending().details["occurrences"])
    rerun = service.generate_due(through_date="2022-01-01")
    assert rerun.details["generated"] == 0
    assert len(service.list_pending().details["occurrences"]) == count


def test_pending_occurrences_can_be_updated_confirmed_skipped_and_batch_confirmed(
    tmp_path: Path,
) -> None:
    paths = resolve_app_paths(tmp_path / "ledger")
    service = AutomationService(paths)
    for name, due_date, amount in (
        ("確認", "2026-01-01", None),
        ("略過", "2026-01-02", None),
        ("批次", "2026-01-02", 500),
    ):
        schedule = service.new_schedule(
            name=name,
            entry_type="expense",
            account_id="acct_cash",
            destination_account_id=None,
            category_id="cat_food_711",
            amount_minor=amount,
            description="",
            frequency="yearly",
            interval_count=1,
            start_date=due_date,
            end_date=due_date,
        )
        assert service.save_schedule(schedule).success
    assert service.generate_due(through_date="2026-01-02").success
    pending = service.list_pending().details["occurrences"]
    confirm_item = next(item for item in pending if item["schedule_name"] == "確認")
    skip_item = next(item for item in pending if item["schedule_name"] == "略過")
    assert confirm_item["invalid_reason"] == "尚未填寫金額"

    assert service.update_occurrence(
        confirm_item["occurrence_id"],
        amount_minor=12345,
        account_id="acct_cash",
        destination_account_id=None,
        category_id="cat_food_711",
        description="修改備註",
    ).success
    assert service.confirm(confirm_item["occurrence_id"]).success
    assert service.skip(skip_item["occurrence_id"]).success
    batch = service.batch_confirm_valid()
    assert batch.details == {"confirmed": 1, "failed": 0}
    assert service.list_pending().details["occurrences"] == []

    store = LedgerStore(paths)
    transactions, _ = store.list_transactions(limit=10)
    updated = next(item for item in transactions if item.description == "修改備註")
    assert updated.money.amount_minor == 12345
