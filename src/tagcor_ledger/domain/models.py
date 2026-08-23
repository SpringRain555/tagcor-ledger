"""application 層與 store 共用的領域模型正本。"""

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
class SortLevel:
    """多層排序的一層：依哪個欄位、升冪還是降冪。

    `field` **只是一個 key**，不是 SQL 片段。它會拿去查各個 store 自己的白名單
    （`CATEGORY_SORT_FIELDS` 等）換成固定的運算式 —— 查不到就整層跳過。
    這是唯一把字串放進 `ORDER BY` 的路徑，所以那份白名單必須是封閉的。
    """

    field: str
    descending: bool = False


SortSpec = tuple[SortLevel, ...]
"""一份排序規格：由上而下的層級。空的代表「用那份清單自己的預設順序」。

**為什麼空的不等於「不排序」**：SQL 沒有指定 `ORDER BY` 時的列順序是不保證的，
畫面每次重整都可能不一樣。空規格一律退回該 store 寫死的預設。
"""


@dataclass(frozen=True, slots=True)
class CategoryTreeFilter:
    """類別樹的篩選與排序條件。**全部在 SQL 裡處理，不撈回 Python 再過濾。**

    `status` 是 `active` / `archived` / `all`；**預設 `all`**，因為名冊分頁是管理用的，
    看不到封存的東西就沒辦法恢復它。

    `sort` 空的時候用 store 的預設順序（項目跟在自己的類別後面）。
    """

    level: int | None = None
    parent_id: str | None = None
    search: str = ""
    status: str = "all"
    sort: SortSpec = ()


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
class TemplateRow:
    """模板清單的一列：模板本身 ＋ 顯示需要的四個名字。

    **組合原本的 dataclass，不是把欄位攤平複製一份** —— 比照 `CategoryNode`
    與 `BalanceGap`。`TransactionTemplate` 同時是**寫入**用的型別
    （`new_template()` 產、`save_template()` 收），把顯示用的名字加到它身上，
    就等於要求每一個建立模板的地方都先去查四個名字。

    四個名字由同一句查詢 join 出來，不是 1+N。`category_name` 是第一層、
    `subcategory_name` 是第二層 —— 與 `TransactionRecord` 同一套拼法，
    所以 `template_values()` 與 `transaction_values()` 能用同一個組字串的寫法。
    """

    template: TransactionTemplate
    account_name: str
    destination_account_name: str | None
    category_name: str | None
    subcategory_name: str | None


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
