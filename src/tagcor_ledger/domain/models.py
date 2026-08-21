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
class CategoryNode:
    """類別樹的一列：類別本身 ＋ 顯示需要的兩個衍生欄位。

    `parent_name` 與 `item_count` 不是 `categories` 表的欄位，是同一句查詢一起算出來的。
    分開查就是 1+N —— 舊的做法是先列出所有類別，再對每一個類別各查一次子項目。

    比照 `BalanceGap`：組合原本的 dataclass，不是把欄位攤平複製一份。
    """

    category: Category
    parent_name: str | None
    item_count: int


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
class CategoryTreeFilter:
    """類別樹的篩選與排序條件。**全部在 SQL 裡處理，不撈回 Python 再過濾。**

    `status` 是 `active` / `archived` / `all`；**預設 `all`**，因為名冊分頁是管理用的，
    看不到封存的東西就沒辦法恢復它。

    `sort_key` 只接受 `CATEGORY_SORT_KEYS` 裡的值 —— 它會變成 `ORDER BY` 的一部分，
    所以**絕對不能讓使用者輸入直接進去**。查不到就退回 `default`。
    """

    level: int | None = None
    parent_id: str | None = None
    search: str = ""
    status: str = "all"
    sort_key: str = "default"
    descending: bool = False


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
    """所有帳務資料的位置。

    `data_root` 是唯一的資料根目錄，`ledger_dir` 與 `backup_dir` 都必須在它底下，
    `exports` / `logs` / `tmp` 也由它推導。留空時退回 `ledger_dir.parent`，
    以相容於還沒有這個欄位的舊設定檔。
    """

    ledger_dir: Path
    backup_dir: Path
    data_root: Path | None = None


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
