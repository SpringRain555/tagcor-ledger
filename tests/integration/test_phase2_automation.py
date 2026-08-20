from __future__ import annotations

from datetime import date
from pathlib import Path

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.application.automation import AutomationService
from tagcor_ledger.domain.models import RecurringSchedule
from tagcor_ledger.infrastructure.database import connect_database
from tagcor_ledger.infrastructure.stores.automation import next_due_date
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


def _confirm_one_occurrence(paths, *, entry_type: str = "expense") -> str:
    """建一個定期收支、產生一期、確認它，回傳那筆交易的 id。"""
    service = AutomationService(paths)
    schedule = service.new_schedule(
        name="房租",
        entry_type=entry_type,
        account_id="acct_cash",
        destination_account_id=None,
        category_id="cat_food_711",
        amount_minor=12_000,
        description="每月房租",
        frequency="yearly",
        interval_count=1,
        start_date="2026-01-01",
        end_date="2026-01-01",
    )
    assert service.save_schedule(schedule).success
    assert service.generate_due(through_date="2026-01-01").success
    occurrence = service.list_pending().details["occurrences"][0]
    result = service.confirm(occurrence["occurrence_id"])
    assert result.success, result.message
    return str(result.details["transaction_id"])


def _audit_rows(paths, transaction_id: str) -> list[dict[str, str]]:
    with connect_database(paths.database_path) as connection:
        rows = connection.execute(
            "SELECT action, entity_id, correlation_id FROM audit_events ORDER BY audit_id"
        ).fetchall()
    return [dict(row) for row in rows]


def test_confirming_an_occurrence_shares_one_correlation_id_with_its_transaction(
    tmp_path: Path,
) -> None:
    """一次操作 = 一個 `correlation_id`。

    `correlation_id` 存在的唯一目的，就是把「同一次操作在不同表留下的列」串起來。
    定期收支確認會寫三張表（`transactions`、`scheduled_occurrences`、`audit_events`），
    如果稽核列自己生一個新的 id，那一欄在這條路上就是白費的 —— 你拿著交易去查稽核，
    查不到；拿著稽核去查交易，也查不到。
    """
    paths = resolve_app_paths(tmp_path / "ledger")
    transaction_id = _confirm_one_occurrence(paths)

    store = LedgerStore(paths)
    transaction = store.get_transaction(transaction_id)
    rows = _audit_rows(paths, transaction_id)

    confirm_rows = [row for row in rows if row["action"] == "occurrence.confirm"]
    assert len(confirm_rows) == 1, rows
    assert confirm_rows[0]["correlation_id"] == transaction.correlation_id, (
        "occurrence.confirm 的稽核列與它建立的那筆交易帶著不同的 correlation_id —— "
        "那一欄就查不回去了"
    )


def test_confirming_an_occurrence_goes_through_the_same_transaction_writer(
    tmp_path: Path,
) -> None:
    """定期收支確認不得自己另寫一份「建立交易」。

    自己寫一份的代價不是重複，是**分岔**：schema 一改要改兩個地方，而只有一邊有
    測試盯著「一筆交易長什麼樣」。判準用稽核列 —— 走共用寫入路徑就一定會留下
    `transaction.create`，自己另寫一份就不會。
    """
    paths = resolve_app_paths(tmp_path / "ledger")
    transaction_id = _confirm_one_occurrence(paths)

    rows = _audit_rows(paths, transaction_id)
    created = [
        row
        for row in rows
        if row["action"] == "transaction.create" and row["entity_id"] == transaction_id
    ]
    assert created, (
        "定期收支確認出來的交易沒有 transaction.create 稽核列 —— "
        f"表示它沒有走 TransactionStore 的寫入路徑。實際稽核列：{rows}"
    )


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
