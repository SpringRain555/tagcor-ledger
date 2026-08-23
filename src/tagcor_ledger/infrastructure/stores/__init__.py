"""依聚合切開的 SQLite store。

對外請用 `tagcor_ledger.infrastructure.sqlite_store.LedgerStore`，它把這裡的 store
組合成單一公開介面。這個套件本身不是穩定 API，切法日後可能再調整。

**這份清單要跟 `sqlite_store.LedgerStore` 的基底一致。** 它曾經漏掉
`AutomationStore`（2026-08 收進 `stores/` 時沒補），docstring 也跟著停在「四個」——
一份沒有人使用的 re-export 清單不會有任何測試提醒你它過期了。
**2026-08-22 補上了那個測試**（`test_architecture.py` 的
`test_the_store_package_reexports_exactly_what_ledger_store_composes`），
所以這次拆檔時漏掉哪一個會直接紅。

**`ScheduleStore` 與 `OccurrenceStore` 在 v0.23.0 隨定期收支一起移除**，
理由見 [ADR-0011](../../../../docs/decisions/ADR-0011-drop-recurring-schedules.md)。
"""

from __future__ import annotations

from tagcor_ledger.infrastructure.stores.accounts import AccountStore
from tagcor_ledger.infrastructure.stores.balance import BalanceStore
from tagcor_ledger.infrastructure.stores.base import NotFoundError, StoreBase, StoreError
from tagcor_ledger.infrastructure.stores.categories import CategoryStore
from tagcor_ledger.infrastructure.stores.deposit_contracts import DepositContractStore
from tagcor_ledger.infrastructure.stores.deposit_events import DepositEventStore
from tagcor_ledger.infrastructure.stores.deposit_terms import DepositTermStore
from tagcor_ledger.infrastructure.stores.templates import TemplateStore
from tagcor_ledger.infrastructure.stores.transactions import TransactionStore

__all__ = [
    "AccountStore",
    "BalanceStore",
    "CategoryStore",
    "DepositContractStore",
    "DepositEventStore",
    "DepositTermStore",
    "NotFoundError",
    "StoreBase",
    "StoreError",
    "TemplateStore",
    "TransactionStore",
]
