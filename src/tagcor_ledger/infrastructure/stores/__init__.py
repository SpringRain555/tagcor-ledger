"""依聚合切開的 SQLite store。

對外請用 `tagcor_ledger.infrastructure.sqlite_store.LedgerStore`，它把這裡的四個
store 組合成單一公開介面。這個套件本身不是穩定 API，切法日後可能再調整。
"""

from __future__ import annotations

from tagcor_ledger.infrastructure.stores.accounts import AccountStore
from tagcor_ledger.infrastructure.stores.balance import BalanceStore
from tagcor_ledger.infrastructure.stores.base import NotFoundError, StoreBase, StoreError
from tagcor_ledger.infrastructure.stores.categories import CategoryStore
from tagcor_ledger.infrastructure.stores.transactions import TransactionStore

__all__ = [
    "AccountStore",
    "BalanceStore",
    "CategoryStore",
    "NotFoundError",
    "StoreBase",
    "StoreError",
    "TransactionStore",
]
