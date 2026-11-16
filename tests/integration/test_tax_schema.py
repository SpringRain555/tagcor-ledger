"""schema v14 的新表、欄位、索引與資料庫約束。"""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.application.deposits import DepositService
from tagcor_ledger.infrastructure.database import connect_database, initialize_database
from tagcor_ledger.infrastructure.migrations import LATEST_SCHEMA_VERSION
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


TAX_TABLES = (
    "tax_category_mappings",
    "tax_reminder_marks",
    "tax_year_inputs",
    "tax_year_overrides",
)


def _make_deposit_event(store: LedgerStore) -> str:
    service = DepositService(store.paths, store)
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
    term_id = store.list_terms(contract_id=contract_id)[0].term_id
    event_id = "devt_tax_v13_existing"
    with connect_database(store.paths.database_path) as connection:
        connection.execute(
            """
            INSERT INTO deposit_events(
                event_id, term_id, event_type, due_date, status, suggested_amount_minor,
                actual_amount_minor, transaction_id, note, created_at, updated_at
            ) VALUES (?, ?, 'interest_payout', '2026-02-01', 'pending', 5, NULL, NULL, '', ?, ?)
            """,
            (event_id, term_id, "2026-01-01T00:00:00+08:00", "2026-01-01T00:00:00+08:00"),
        )
    return event_id


def test_fresh_database_gets_the_tax_schema_and_reruns_safely(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "data")
    initialize_database(paths)
    initialize_database(paths)

    with connect_database(paths.database_path) as connection:
        version = connection.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
        versions = connection.execute("SELECT COUNT(*) AS count FROM schema_migrations").fetchone()
        tables = {
            str(row["name"])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        event_columns = {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(deposit_events)")
        }
        index = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' "
            "AND name = 'idx_deposit_events_transaction'"
        ).fetchone()
    assert int(version["version"]) == LATEST_SCHEMA_VERSION
    assert int(versions["count"]) == LATEST_SCHEMA_VERSION
    assert set(TAX_TABLES) <= tables
    assert {"withheld_tax_minor", "nhi_premium_minor"} <= event_columns
    assert index is not None


def test_v13_database_upgrade_keeps_existing_event_amounts_null(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "data")
    store = LedgerStore(paths)
    event_id = _make_deposit_event(store)

    # 把剛建立的測試帳本退回 v13 schema，保留一列舊定存事件。
    with connect_database(paths.database_path) as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version >= 14")
        connection.execute("DROP INDEX idx_deposit_events_transaction")
        for table in TAX_TABLES:
            connection.execute(f"DROP TABLE {table}")
        connection.execute("ALTER TABLE deposit_events DROP COLUMN withheld_tax_minor")
        connection.execute("ALTER TABLE deposit_events DROP COLUMN nhi_premium_minor")

    initialize_database(paths)

    with connect_database(paths.database_path) as connection:
        event = connection.execute(
            """
            SELECT withheld_tax_minor, nhi_premium_minor
            FROM deposit_events WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()
        version = connection.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
    assert int(version["version"]) == LATEST_SCHEMA_VERSION
    assert event["withheld_tax_minor"] is None
    assert event["nhi_premium_minor"] is None


def test_v14_check_constraints_reject_invalid_tax_rows(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "data")
    LedgerStore(paths)

    invalid_inserts = (
        (
            """
            INSERT INTO tax_category_mappings(category_id, flow, tax_kind, updated_at)
            VALUES ('cat_food', 'income', 'house_tax', '2026-01-01')
            """,
        ),
        (
            """
            INSERT INTO tax_category_mappings(category_id, flow, tax_kind, updated_at)
            VALUES ('cat_food', 'expense', 'salary', '2026-01-01')
            """,
        ),
        (
            """
            INSERT INTO tax_year_inputs(
                income_year, filing, deduction, other_special_deductions,
                dependents_have_income, filer_70_plus, dependents, dependents_70_plus,
                official_tax_minor, official_balance_minor, updated_at
            ) VALUES (2026, 'single', 'standard', 0, 0, 0, 1, 2, NULL, NULL, '2026-01-01')
            """,
        ),
        (
            """
            INSERT INTO tax_year_overrides(
                income_year, income_kind, gross_minor, withheld_minor, updated_at
            ) VALUES (2026, 'salary', NULL, NULL, '2026-01-01')
            """,
        ),
    )
    for (statement,) in invalid_inserts:
        with pytest.raises(sqlite3.IntegrityError):
            with connect_database(paths.database_path) as connection:
                connection.execute(statement)

