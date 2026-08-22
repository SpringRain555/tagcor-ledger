"""依聚合切開的 SQLite store。

對外請用 `tagcor_ledger.infrastructure.sqlite_store.LedgerStore`，它把這裡的**六個**
store 組合成單一公開介面。這個套件本身不是穩定 API，切法日後可能再調整。

**這份清單要跟 `sqlite_store.LedgerStore` 的基底一致。** 它曾經漏掉
`AutomationStore`（2026-08 收進 `stores/` 時沒補），docstring 也跟著停在「四個」——
一份沒有人使用的 re-export 清單不會有任何測試提醒你它過期了。
"""

from __future__ import annotations

from tagcor_ledger.infrastructure.stores.accounts import AccountStore
from tagcor_ledger.infrastructure.stores.automation import AutomationStore
from tagcor_ledger.infrastructure.stores.balance import BalanceStore
from tagcor_ledger.infrastructure.stores.base import NotFoundError, StoreBase, StoreError
from tagcor_ledger.infrastructure.stores.categories import CategoryStore
from tagcor_ledger.infrastructure.stores.deposits import DepositStore
from tagcor_ledger.infrastructure.stores.transactions import TransactionStore

__all__ = [
    "AccountStore",
    "AutomationStore",
    "BalanceStore",
    "CategoryStore",
    "DepositStore",
    "NotFoundError",
    "StoreBase",
    "StoreError",
    "TransactionStore",
]
