"""Validation helpers for the Phase 1 CSV/JSON data contract."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Iterable, Mapping

from tagcor_ledger.domain.money import parse_decimal_string


class ValidationError(ValueError):
    """Raised when canonical data does not satisfy the data format spec."""


ID_RE = re.compile(r"^[a-z]+_[0-9a-z_]+$")
ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

TAG_STATUSES = {"active", "archived"}
TEMPLATE_STATUSES = {"active", "archived"}
TRANSACTION_STATUSES = {"active", "voided"}
ENTRY_TYPES = {"income", "expense", "transfer", "adjustment"}
SOURCES = {"manual", "template", "import", "migration"}
FOCUS_TARGETS = {"amount", "description", "submit"}
STARTUP_BACKUP_VALUES = {"never", "daily", "always"}

LEDGER_FIELDS = [
    "schema_version",
    "transaction_id",
    "revision",
    "status",
    "entry_type",
    "occurred_at",
    "recorded_at",
    "updated_at",
    "currency",
    "amount",
    "l1_id",
    "l2_id",
    "l3_id",
    "l4_id",
    "l1_name_snapshot",
    "l2_name_snapshot",
    "l3_name_snapshot",
    "l4_name_snapshot",
    "description",
    "source",
    "template_id",
    "correlation_id",
]


def require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{label} must be an object.")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValidationError(f"{label} must be a list.")
    return value


def require_keys(data: Mapping[str, Any], keys: Iterable[str], label: str) -> None:
    missing = [key for key in keys if key not in data]
    if missing:
        raise ValidationError(f"{label} missing required keys: {', '.join(missing)}")


def require_string(data: Mapping[str, Any], key: str, label: str, *, allow_empty: bool = False) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ValidationError(f"{label}.{key} must be a string.")
    if not allow_empty and value == "":
        raise ValidationError(f"{label}.{key} cannot be empty.")
    return value


def require_int(data: Mapping[str, Any], key: str, label: str) -> int:
    value = data.get(key)
    if not isinstance(value, int):
        raise ValidationError(f"{label}.{key} must be an integer.")
    return value


def validate_schema_version(data: Mapping[str, Any], label: str, expected: int = 1) -> None:
    if data.get("schema_version") != expected:
        raise ValidationError(f"{label}.schema_version must be {expected}.")


def validate_id(value: str, prefix: str, label: str) -> None:
    if not isinstance(value, str) or not value.startswith(f"{prefix}_") or not ID_RE.fullmatch(value):
        raise ValidationError(f"{label} must be a stable {prefix}_ ID.")


def validate_optional_id(value: Any, prefix: str, label: str) -> None:
    if value in (None, ""):
        return
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be blank or a string ID.")
    validate_id(value, prefix, label)


def validate_datetime(value: str, label: str) -> None:
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be an ISO 8601 datetime string.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"{label} must be ISO 8601.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError(f"{label} must include a timezone offset.")


def validate_enum(value: Any, allowed: set[str], label: str) -> None:
    if value not in allowed:
        raise ValidationError(f"{label} must be one of: {', '.join(sorted(allowed))}.")


def validate_settings_document(document: Mapping[str, Any]) -> None:
    data = require_mapping(document, "settings")
    validate_schema_version(data, "settings")
    require_keys(
        data,
        [
            "app_data_version",
            "data_dir",
            "config_dir",
            "ledger_dir",
            "backup_dir",
            "export_dir",
            "log_dir",
            "timezone",
            "default_currency",
            "startup_backup",
            "export_csv_encoding",
            "created_at",
            "updated_at",
        ],
        "settings",
    )
    require_string(data, "app_data_version", "settings")
    for key in ("data_dir", "config_dir", "ledger_dir", "backup_dir", "export_dir", "log_dir"):
        require_string(data, key, "settings")
    require_string(data, "timezone", "settings")
    currency = require_string(data, "default_currency", "settings")
    if not ISO_CURRENCY_RE.fullmatch(currency):
        raise ValidationError("settings.default_currency must be an ISO 4217 code.")
    validate_enum(data["startup_backup"], STARTUP_BACKUP_VALUES, "settings.startup_backup")
    require_string(data, "export_csv_encoding", "settings")
    validate_datetime(require_string(data, "created_at", "settings"), "settings.created_at")
    validate_datetime(require_string(data, "updated_at", "settings"), "settings.updated_at")


def validate_tags_document(document: Mapping[str, Any]) -> None:
    data = require_mapping(document, "tags_document")
    validate_schema_version(data, "tags_document")
    levels = require_list(data.get("levels"), "tags_document.levels")
    tags = require_list(data.get("tags"), "tags_document.tags")
    if [level.get("level") for level in levels if isinstance(level, Mapping)] != [1, 2, 3, 4]:
        raise ValidationError("tags_document.levels must define levels 1 through 4 in order.")

    tag_by_id: dict[str, Mapping[str, Any]] = {}
    active_names: set[tuple[str | None, str]] = set()
    for index, raw_tag in enumerate(tags):
        tag = require_mapping(raw_tag, f"tags[{index}]")
        require_keys(
            tag,
            [
                "tag_id",
                "parent_id",
                "level",
                "name",
                "status",
                "sort_order",
                "aliases",
                "created_at",
                "updated_at",
                "archived_at",
            ],
            f"tags[{index}]",
        )
        tag_id = require_string(tag, "tag_id", f"tags[{index}]")
        validate_id(tag_id, "tag", f"tags[{index}].tag_id")
        if tag_id in tag_by_id:
            raise ValidationError(f"Duplicate tag_id: {tag_id}")
        tag_by_id[tag_id] = tag
        parent_id = tag["parent_id"]
        if parent_id is not None:
            validate_id(parent_id, "tag", f"tags[{index}].parent_id")
        level = require_int(tag, "level", f"tags[{index}]")
        if level not in {1, 2, 3, 4}:
            raise ValidationError(f"tags[{index}].level must be 1-4.")
        name = require_string(tag, "name", f"tags[{index}]")
        validate_enum(tag["status"], TAG_STATUSES, f"tags[{index}].status")
        require_int(tag, "sort_order", f"tags[{index}]")
        aliases = require_list(tag["aliases"], f"tags[{index}].aliases")
        if not all(isinstance(alias, str) for alias in aliases):
            raise ValidationError(f"tags[{index}].aliases must contain only strings.")
        validate_datetime(require_string(tag, "created_at", f"tags[{index}]"), f"tags[{index}].created_at")
        validate_datetime(require_string(tag, "updated_at", f"tags[{index}]"), f"tags[{index}].updated_at")
        if tag["status"] == "archived":
            archived_at = require_string(tag, "archived_at", f"tags[{index}]")
            validate_datetime(archived_at, f"tags[{index}].archived_at")
        elif tag["archived_at"] is not None:
            raise ValidationError(f"tags[{index}].archived_at must be null for active tags.")
        if tag["status"] == "active":
            name_key = (parent_id, name)
            if name_key in active_names:
                raise ValidationError(f"Duplicate active tag name under parent: {name}")
            active_names.add(name_key)

    for tag_id, tag in tag_by_id.items():
        parent_id = tag["parent_id"]
        level = tag["level"]
        if level == 1 and parent_id is not None:
            raise ValidationError(f"{tag_id} is level 1 and cannot have a parent.")
        if level > 1:
            if parent_id is None:
                raise ValidationError(f"{tag_id} must have a parent.")
            parent = tag_by_id.get(parent_id)
            if parent is None:
                raise ValidationError(f"{tag_id} references missing parent {parent_id}.")
            if parent["level"] != level - 1:
                raise ValidationError(f"{tag_id} parent must be level {level - 1}.")


def validate_tag_path(tags_document: Mapping[str, Any], tag_ids: tuple[str, str, str, str]) -> None:
    validate_tags_document(tags_document)
    tags = {tag["tag_id"]: tag for tag in tags_document["tags"]}
    previous_id: str | None = None
    for expected_level, tag_id in enumerate(tag_ids, start=1):
        tag = tags.get(tag_id)
        if tag is None:
            raise ValidationError(f"Tag path references missing tag: {tag_id}")
        if tag["status"] != "active":
            raise ValidationError(f"Tag path references archived tag: {tag_id}")
        if tag["level"] != expected_level:
            raise ValidationError(f"{tag_id} must be level {expected_level}.")
        if tag["parent_id"] != previous_id:
            raise ValidationError(f"{tag_id} is not a child of {previous_id}.")
        previous_id = tag_id


def validate_templates_document(document: Mapping[str, Any], tags_document: Mapping[str, Any]) -> None:
    data = require_mapping(document, "templates_document")
    validate_schema_version(data, "templates_document")
    templates = require_list(data.get("templates"), "templates_document.templates")
    template_ids: set[str] = set()
    for index, raw_template in enumerate(templates):
        template = require_mapping(raw_template, f"templates[{index}]")
        require_keys(
            template,
            [
                "template_id",
                "name",
                "status",
                "l1_id",
                "l2_id",
                "l3_id",
                "l4_id",
                "default_amount",
                "default_description",
                "focus_target",
                "sort_order",
                "created_at",
                "updated_at",
                "archived_at",
            ],
            f"templates[{index}]",
        )
        template_id = require_string(template, "template_id", f"templates[{index}]")
        validate_id(template_id, "tpl", f"templates[{index}].template_id")
        if template_id in template_ids:
            raise ValidationError(f"Duplicate template_id: {template_id}")
        template_ids.add(template_id)
        require_string(template, "name", f"templates[{index}]")
        validate_enum(template["status"], TEMPLATE_STATUSES, f"templates[{index}].status")
        validate_tag_path(
            tags_document,
            (
                require_string(template, "l1_id", f"templates[{index}]"),
                require_string(template, "l2_id", f"templates[{index}]"),
                require_string(template, "l3_id", f"templates[{index}]"),
                require_string(template, "l4_id", f"templates[{index}]"),
            ),
        )
        parse_decimal_string(require_string(template, "default_amount", f"templates[{index}]"), allow_zero=True)
        require_string(template, "default_description", f"templates[{index}]", allow_empty=True)
        validate_enum(template["focus_target"], FOCUS_TARGETS, f"templates[{index}].focus_target")
        require_int(template, "sort_order", f"templates[{index}]")
        validate_datetime(require_string(template, "created_at", f"templates[{index}]"), f"templates[{index}].created_at")
        validate_datetime(require_string(template, "updated_at", f"templates[{index}]"), f"templates[{index}].updated_at")
        if template["status"] == "archived":
            archived_at = require_string(template, "archived_at", f"templates[{index}]")
            validate_datetime(archived_at, f"templates[{index}].archived_at")
        elif template["archived_at"] is not None:
            raise ValidationError(f"templates[{index}].archived_at must be null for active templates.")


def validate_ledger_row(row: Mapping[str, Any]) -> None:
    data = require_mapping(row, "ledger_row")
    require_keys(data, LEDGER_FIELDS, "ledger_row")
    if str(data["schema_version"]) != "1":
        raise ValidationError("ledger_row.schema_version must be 1.")
    validate_id(require_string(data, "transaction_id", "ledger_row"), "txn", "ledger_row.transaction_id")
    revision = int(require_string(data, "revision", "ledger_row") if isinstance(data["revision"], str) else data["revision"])
    if revision < 1:
        raise ValidationError("ledger_row.revision must be >= 1.")
    validate_enum(data["status"], TRANSACTION_STATUSES, "ledger_row.status")
    validate_enum(data["entry_type"], ENTRY_TYPES, "ledger_row.entry_type")
    for key in ("occurred_at", "recorded_at", "updated_at"):
        validate_datetime(require_string(data, key, "ledger_row"), f"ledger_row.{key}")
    currency = require_string(data, "currency", "ledger_row")
    if not ISO_CURRENCY_RE.fullmatch(currency):
        raise ValidationError("ledger_row.currency must be an ISO 4217 code.")
    parse_decimal_string(require_string(data, "amount", "ledger_row"))
    for key in ("l1_id", "l2_id", "l3_id", "l4_id"):
        validate_id(require_string(data, key, "ledger_row"), "tag", f"ledger_row.{key}")
    for key in ("l1_name_snapshot", "l2_name_snapshot", "l3_name_snapshot", "l4_name_snapshot"):
        require_string(data, key, "ledger_row")
    require_string(data, "description", "ledger_row", allow_empty=True)
    validate_enum(data["source"], SOURCES, "ledger_row.source")
    validate_optional_id(data["template_id"], "tpl", "ledger_row.template_id")
    validate_id(require_string(data, "correlation_id", "ledger_row"), "corr", "ledger_row.correlation_id")
