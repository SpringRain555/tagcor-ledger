import json
from pathlib import Path
import sqlite3

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.domain.validation import LEDGER_FIELDS
from tagcor_ledger.infrastructure.audit import AuditLogWriter, make_audit_event
from tagcor_ledger.infrastructure.csv_ledger import CsvLedgerRepository
from tagcor_ledger.infrastructure.json_config import JsonConfigRepository
from tagcor_ledger.infrastructure.manifest import generate_manifest, write_manifest
from tagcor_ledger.infrastructure.repositories import (
    default_settings,
    default_tags,
    default_templates,
    initialize_data_store,
)


def test_initialize_data_store_writes_canonical_database(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger-data")

    written = initialize_data_store(paths)

    assert written["database"] == paths.database_path
    assert paths.database_path.is_file()
    with sqlite3.connect(paths.database_path) as connection:
        version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        account = connection.execute(
            "SELECT name FROM accounts WHERE account_id = 'acct_cash'"
        ).fetchone()
    assert version == (1,)
    assert account == ("現金",)


def test_json_repository_round_trip(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger-data")
    document = default_settings(paths, "2026-05-08T08:30:00+08:00")
    repository = JsonConfigRepository(paths.config_dir / "settings.json")

    repository.write(document)

    assert repository.read()["schema_version"] == 1


def test_csv_ledger_repository_round_trip(tmp_path: Path) -> None:
    row = {
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
    repository = CsvLedgerRepository(tmp_path / "ledger_2026.csv")

    repository.append_row(row)
    rows = repository.read_rows()

    assert list(rows[0].keys()) == LEDGER_FIELDS
    assert rows[0]["amount"] == "85"


def test_audit_writer_writes_json_line(tmp_path: Path) -> None:
    writer = AuditLogWriter(tmp_path / "audit.log")
    event = make_audit_event(
        correlation_id="corr_5f03a3dd2b8740198365bd7e4ab6d2d3",
        action="transaction.create",
        entity_type="transaction",
        entity_id="txn_5c3d0d1a0d3f4e66b0c8b2abf9d5431a",
        details={"ledger_file": "data/ledger_2026.csv"},
    )

    writer.write_event(event)

    line = (tmp_path / "audit.log").read_text(encoding="utf-8").strip()
    assert json.loads(line)["action"] == "transaction.create"


def test_manifest_generation(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger-data")
    paths.config_dir.mkdir(parents=True)
    settings_path = paths.config_dir / "settings.json"
    tags_path = paths.config_dir / "tags.json"
    templates_path = paths.config_dir / "templates.json"
    JsonConfigRepository(settings_path).write(
        default_settings(paths, "2026-05-08T08:30:00+08:00")
    )
    JsonConfigRepository(tags_path).write(default_tags("2026-05-08T08:30:00+08:00"))
    JsonConfigRepository(templates_path).write(default_templates("2026-05-08T08:30:00+08:00"))

    manifest = generate_manifest(paths.data_dir, [settings_path, tags_path, templates_path])
    write_manifest(paths.config_dir / "data_manifest.json", manifest)

    assert (paths.config_dir / "data_manifest.json").is_file()
    assert len(manifest["files"]) == 3
