"""Canonical data models used by validators and repositories."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TagPath:
    l1_id: str
    l2_id: str
    l3_id: str
    l4_id: str

    def as_tuple(self) -> tuple[str, str, str, str]:
        return (self.l1_id, self.l2_id, self.l3_id, self.l4_id)


@dataclass(frozen=True)
class TagNameSnapshot:
    l1_name: str
    l2_name: str
    l3_name: str
    l4_name: str

    def as_tuple(self) -> tuple[str, str, str, str]:
        return (self.l1_name, self.l2_name, self.l3_name, self.l4_name)
