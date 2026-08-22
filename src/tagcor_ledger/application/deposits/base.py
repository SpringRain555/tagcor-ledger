"""`DepositService` 各 section 的共同基底，以及它們之間傳遞的 `DepositPosting`。

放這裡是為了讓每個 section 都 import 得到 `self.store` 與 `self.paths` 的型別 ——
mypy `--strict` 對裸 mixin 看不到這兩個屬性。比照 `ui/controller/wiring.py`。
"""

from __future__ import annotations

from dataclasses import dataclass

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore

# 到期前幾天產生待確認項目。給「不自動轉存」留反應時間 —— 那種情況要本人去郵局處理。
MATURITY_LEAD_DAYS = 7


@dataclass(frozen=True, slots=True)
class DepositPosting:
    """確認一件定存事件會產生的一筆交易。"""

    entry_type: str
    amount_minor: int
    account_id: str
    destination_account_id: str | None
    description: str


class DepositServiceBase:
    def __init__(self, paths: AppPaths, store: LedgerStore | None = None) -> None:
        self.paths = paths
        self.store = store or LedgerStore(paths)
