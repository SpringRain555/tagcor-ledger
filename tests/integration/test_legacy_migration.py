import csv
from pathlib import Path
import sqlite3

import pytest

from tagcor_ledger.app.paths import ensure_directories, resolve_app_paths
from tagcor_ledger.domain.validation import LEDGER_FIELDS
from tagcor_ledger.infrastructure.csv_ledger import CsvLedgerRepository
from tagcor_ledger.infrastructure.json_config import JsonConfigRepository
from tagcor_ledger.infrastructure.repositories import default_tags, initialize_data_store


def test_legacy_csv_migration_is_backed_up_and_idempotent(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger-data")
    ensure_directories(paths)
    JsonConfigRepository(paths.config_dir / "tags.json").write(
        default_tags("2026-05-08T08:30:00+08:00")
    )
    CsvLedgerRepository(paths.ledger_dir / "ledger_2026.csv").write_rows([_legacy_row()])

    initialize_data_store(paths)
    initialize_data_store(paths)

    with sqlite3.connect(paths.database_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM transactions").fetchone()
    backups = list(paths.backup_dir.glob("legacy-import-*"))
    assert count == (1,)
    assert len(backups) == 1
    assert (backups[0] / "backup_manifest.json").is_file()
    assert (paths.log_dir / "legacy_migration_report.json").is_file()


def test_legacy_migration_failure_rolls_back_all_rows(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger-data")
    ensure_directories(paths)
    valid = _legacy_row()
    invalid = {**_legacy_row(), "transaction_id": "txn_invalid", "amount": "bad"}
    ledger_path = paths.ledger_dir / "ledger_2026.csv"
    with ledger_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDS)
        writer.writeheader()
        writer.writerows([valid, invalid])

    with pytest.raises(ValueError):
        initialize_data_store(paths)

    with sqlite3.connect(paths.database_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM transactions").fetchone()
    assert count == (0,)


def _legacy_row() -> dict[str, str]:
    return {
        "schema_version": "1",
        "transaction_id": "txn_5c3d0d1a0d3f4e66b0c8b2abf9d5431a",
        "revision": "1",
        "status": "active",
        "entry_type": "expense",
        "occurred_at": "2026-05-08T08:30:00+08:00",
        "recorded_at": "2026-05-08T08:31:00+08:00",
        "updated_at": "2026-05-08T08:31:00+08:00",
        "currency": "TWD",
        "amount": "85",
        "l1_id": "tag_expense",
        "l2_id": "tag_cash",
        "l3_id": "tag_food",
        "l4_id": "tag_711",
        "l1_name_snapshot": "支出",
        "l2_name_snapshot": "現金",
        "l3_name_snapshot": "伙食",
        "l4_name_snapshot": "7-11",
        "description": "早餐",
        "source": "manual",
        "template_id": "",
        "correlation_id": "corr_5f03a3dd2b8740198365bd7e4ab6d2d3",
    }
