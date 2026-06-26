"""Canonical domain models used by application services and repositories."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

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
    description: str
    correlation_id: str
    replaces_transaction_id: str | None = None


@dataclass(frozen=True, slots=True)
class TransactionFilter:
    search: str = ""
    date_from: str | None = None
    date_to: str | None = None
    account_id: str | None = None
    category_id: str | None = None
    status: str = "active"


@dataclass(frozen=True, slots=True)
class ApplicationSettings:
    default_account_id: str
    default_entry_type: str
    transactions_page_size: int
    balance_snapshot_reminder: bool = True
    timezone: str = "Asia/Taipei"
    default_currency: str = "TWD"


@dataclass(frozen=True, slots=True)
class TransactionTemplate:
    template_id: str
    name: str
    status: str
    entry_type: str
    account_id: str
    destination_account_id: str | None
    category_id: str | None
    amount_minor: int | None
    currency: str
    description: str
    sort_order: int


@dataclass(frozen=True, slots=True)
class RecurringSchedule:
    schedule_id: str
    name: str
    status: str
    entry_type: str
    account_id: str
    destination_account_id: str | None
    category_id: str | None
    amount_minor: int | None
    currency: str
    description: str
    frequency: str
    interval_count: int
    start_date: str
    next_due_date: str
    end_date: str | None


@dataclass(frozen=True, slots=True)
class ScheduledOccurrence:
    occurrence_id: str
    schedule_id: str
    schedule_name: str
    due_date: str
    status: str
    entry_type: str
    account_id: str
    destination_account_id: str | None
    category_id: str | None
    amount_minor: int | None
    currency: str
    description: str
    invalid_reason: str | None


@dataclass(frozen=True, slots=True)
class SystemPathSettings:
    ledger_dir: Path
    backup_dir: Path


@dataclass(frozen=True, slots=True)
class BalanceSnapshot:
    snapshot_id: str
    account_id: str
    account_name: str
    observed_at: str
    actual_balance_minor: int
    currency: str
    status: str
    note: str
    created_at: str
    updated_at: str
    correlation_id: str


@dataclass(frozen=True, slots=True)
class BalanceGap:
    snapshot: BalanceSnapshot
    previous_snapshot_id: str | None
    previous_observed_at: str | None
    previous_actual_balance_minor: int | None
    period_start: str | None
    period_end: str
    posting_sum_minor: int
    expected_balance_minor: int
    difference_minor: int


@dataclass(frozen=True, slots=True)
class CreateBalanceSnapshotRequest:
    account_id: str
    observed_at: str
    actual_balance: str
    note: str = ""
    currency: str = "TWD"


@dataclass(frozen=True, slots=True)
class BalanceSnapshotFilter:
    account_id: str | None = None
    status: str = "active"
