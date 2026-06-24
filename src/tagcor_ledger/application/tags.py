"""Tag catalog helpers for use cases and UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from tagcor_ledger.domain.models import TagNameSnapshot, TagPath
from tagcor_ledger.domain.validation import ValidationError, validate_tag_path, validate_tags_document


@dataclass(frozen=True)
class TagOption:
    tag_id: str
    name: str
    level: int
    parent_id: str | None


class TagCatalog:
    def __init__(self, document: Mapping[str, Any]) -> None:
        validate_tags_document(document)
        self.document = document
        self._tags = {tag["tag_id"]: tag for tag in document["tags"]}

    def validate_path(self, path: TagPath) -> None:
        validate_tag_path(self.document, path.as_tuple())

    def snapshot_for_path(self, path: TagPath) -> TagNameSnapshot:
        self.validate_path(path)
        return TagNameSnapshot(
            l1_name=self._tag_name(path.l1_id),
            l2_name=self._tag_name(path.l2_id),
            l3_name=self._tag_name(path.l3_id),
            l4_name=self._tag_name(path.l4_id),
        )

    def children_of(self, parent_id: str | None, level: int) -> list[TagOption]:
        options = [
            TagOption(
                tag_id=tag["tag_id"],
                name=tag["name"],
                level=tag["level"],
                parent_id=tag["parent_id"],
            )
            for tag in self.document["tags"]
            if tag["status"] == "active" and tag["parent_id"] == parent_id and tag["level"] == level
        ]
        return sorted(options, key=lambda option: (self._sort_order(option.tag_id), option.name))

    def default_path(self) -> TagPath:
        l1_options = self.children_of(None, 1)
        if not l1_options:
            raise ValidationError("No active L1 tag found.")
        l1 = l1_options[0]
        l2 = self._first_child(l1.tag_id, 2)
        l3 = self._first_child(l2.tag_id, 3)
        l4 = self._first_child(l3.tag_id, 4)
        return TagPath(l1.tag_id, l2.tag_id, l3.tag_id, l4.tag_id)

    def _first_child(self, parent_id: str, level: int) -> TagOption:
        options = self.children_of(parent_id, level)
        if not options:
            raise ValidationError(f"No active level {level} tag found under {parent_id}.")
        return options[0]

    def _tag_name(self, tag_id: str) -> str:
        tag = self._tags.get(tag_id)
        if tag is None:
            raise ValidationError(f"Missing tag: {tag_id}")
        return str(tag["name"])

    def _sort_order(self, tag_id: str) -> int:
        tag = self._tags.get(tag_id)
        if tag is None:
            return 0
        return int(tag["sort_order"])
