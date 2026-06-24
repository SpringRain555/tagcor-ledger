"""Canonical domain models used by application services and repositories."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tagcor_ledger.domain.money import Money


class EntryType(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"
    ADJUSTMENT = "adjustment"


class RecordStatus(StrEnum):
    ACTIVE = "active"
    VOIDED = "voided"
    ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class Account:
    account_id: str
    name: str
    account_type: str
    currency: str
    opening_balance_minor: int
    status: str
    sort_order: int


@dataclass(frozen=True, slots=True)
class Category:
    category_id: str
    name: str
    parent_id: str | None
    level: int
    status: str
    sort_order: int


@dataclass(frozen=True, slots=True)
class TransactionRecord:
    transaction_id: str
    revision: int
    status: str
    entry_type: str
    occurred_at: str
    recorded_at: str
    updated_at: str
    money: Money
    account_id: str
    account_name: str
    destination_account_id: str | None
    destination_account_name: str | None
    category_id: str | None
    category_name: str | None
    subcategory_id: str | None
    subcategory_name: str | None
    payee_name: str
    description: str
    correlation_id: str


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
