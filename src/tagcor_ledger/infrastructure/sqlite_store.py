"""SQLite-backed repositories for ledger application services.

`LedgerStore` 是 application 層唯一該認得的 store。實作依聚合切在
`tagcor_ledger.infrastructure.stores` 底下，這裡只負責組起來。

**為什麼是繼承而不是委派？** 這六個 store 共用同一份 `AppPaths`、同一套「每次呼叫
自己開連線」的模型，對外也一直是單一物件。用繼承組裝時，拆檔就只是「這個 `def` 放
在哪個檔案」，方法本體與簽章一個字都不用改；換成委派則要手寫三十幾個轉發方法，在一
個「行為零改變」的重構裡等於多開三十幾個出錯的機會。

**繼承的另一個好處在 `AutomationStore` 收編時才看出來**：它要在自己的 transaction 內
呼叫 `_write_transaction()`，而那是 `StoreBase` 的方法 —— 同一棵繼承樹上直接就拿得到，
不必為了共用一段寫入邏輯再發明一個協作物件。
"""

from __future__ import annotations

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.infrastructure.database import connect_database, initialize_database
from tagcor_ledger.infrastructure.stores.accounts import AccountStore
from tagcor_ledger.infrastructure.stores.automation import AutomationStore
from tagcor_ledger.infrastructure.stores.balance import BalanceStore
from tagcor_ledger.infrastructure.stores.base import NotFoundError, StoreError
from tagcor_ledger.infrastructure.stores.categories import CategoryStore
from tagcor_ledger.infrastructure.stores.deposits import DepositStore
from tagcor_ledger.infrastructure.stores.transactions import TransactionStore

__all__ = ["LedgerStore", "NotFoundError", "StoreError"]


class LedgerStore(
    AccountStore,
    CategoryStore,
    TransactionStore,
    BalanceStore,
    DepositStore,
    AutomationStore,
):
    def __init__(self, paths: AppPaths) -> None:
        super().__init__(paths)
        initialize_database(paths)

    def integrity_check(self) -> str:
        with connect_database(self.paths.database_path) as connection:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        return str(row[0]) if row is not None else "unknown"
