import csv
import json
from pathlib import Path

from tagcor_ledger.domain.validation import (
    validate_ledger_row,
    validate_settings_document,
    validate_tags_document,
    validate_templates_document,
)


EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def test_example_json_documents_are_valid() -> None:
    settings = json.loads((EXAMPLES / "settings.example.json").read_text(encoding="utf-8"))
    tags = json.loads((EXAMPLES / "tags.example.json").read_text(encoding="utf-8"))
    templates = json.loads((EXAMPLES / "templates.example.json").read_text(encoding="utf-8"))

    validate_settings_document(settings)
    validate_tags_document(tags)
    validate_templates_document(templates, tags)


def test_example_ledger_row_is_valid() -> None:
    with (EXAMPLES / "ledger_2026.example.csv").open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 1
    validate_ledger_row(rows[0])
