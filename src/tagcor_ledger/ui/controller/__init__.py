"""介面與 use case 之間的 controller。

頁面只認得這裡的方法，不直接碰 application 層，**更不寫 SQL**。

## 為什麼是繼承組裝，而不是一個檔案或一組委派

原本 `ui/controller.py` 是單一檔案，長到 700 行 —— 剛好貼著
`test_no_module_grows_back_into_a_monolith` 的上限，而上一版是靠壓縮註解才過關的。

拆法照 `LedgerStore` 的既有做法（理由寫在 `infrastructure/sqlite_store.py`）：
**用繼承組裝，拆檔就只是「這個 `def` 放在哪個檔案」**，方法本體與簽章一個字都不用改，
呼叫端也完全不用動 —— `from tagcor_ledger.ui.controller import LedgerController`
現在解析到這個 `__init__`。換成委派則要手寫六十幾個轉發方法，在一個「行為零改變」的
重構裡等於多開六十幾個出錯的機會。

## 這個檔案裡不放方法

`LedgerController` 的 class body 是空的，`__init__` 在 `ControllerBase`。
有一條守門測試（`test_architecture.py`）盯著這件事 —— 組裝檔一旦開始長方法，
下一步就是長回 700 行。

## section 之間的紀律

每個 section 都只繼承 `ControllerBase`，**彼此不呼叫對方**。唯一的例外是
`OverviewSection`，它明說自己是聚合層並繼承它聚合的那幾個；理由寫在 `overview.py`。
"""

from __future__ import annotations

from tagcor_ledger.ui.controller.data_paths import DataPathSection
from tagcor_ledger.ui.controller.maintenance import MaintenanceSection
from tagcor_ledger.ui.controller.overview import OverviewSection
from tagcor_ledger.ui.controller.wiring import ControllerBase

__all__ = ["ControllerBase", "LedgerController"]


class LedgerController(OverviewSection, MaintenanceSection, DataPathSection):
    """UI 唯一的入口。

    `OverviewSection` 已經把 ledger／templates／deposits／balance 四段帶進來了，
    所以這裡只要再加維護與資料路徑兩段。
    """
