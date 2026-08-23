"""守門：寫入層丟出來的 `NotFoundError` 不准炸到使用者臉上。

## 為什麼需要這一組

`NotFoundError` 繼承的是 `RuntimeError`，**不是 `ValueError`**
（`infrastructure/stores/base.py`）。於是 `except (ValueError, sqlite3.Error)` 接不到它。

2026-08-22 全面盤點 `application/` 的 69 個 except handler 時發現，其中 15 個
handler 包著一個「會丟 `NotFoundError` 的 store 方法」，卻沒有把它列進去。目前沒有
出事，靠的是巧合：

- `templates.py` 那幾個 —— `stores/templates.py` 有一部分用
  `ValueError("TEMPLATE_NOT_FOUND")`、一部分用 `NotFoundError`，所以那一層
  **一定要用 `STORE_FAILURES` 常數**，自己拼 tuple 遲早漏掉一種。
- `balance.py` 那幾個 —— `_balance_gap_for_snapshot()` 真的會丟
  `NotFoundError("ACCOUNT_NOT_FOUND")`，只是 `delete_account()` 擋著不讓帳戶在
  還有盤點時被刪掉，所以那個防禦性檢查目前碰不到。**它是防禦性檢查，不是死碼** ——
  真的觸發時使用者該看到中文，不是全域錯誤對話框。

所以這裡不去論證「今天會不會炸」，而是直接**把 store 方法換成會丟 `NotFoundError`
的假貨**，斷言使用者拿到的是 `Result.fail` 加一句中文。這樣的斷言分辨得出
「有接住」與「沒接住」—— 沒接住的話例外會直接穿過測試。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tagcor_ledger.app.paths import AppPaths, resolve_app_paths
from tagcor_ledger.application.balance import BalanceSnapshotService
from tagcor_ledger.application.deposits import DepositService
from tagcor_ledger.application.failures import ERROR_MESSAGES
from tagcor_ledger.application.result import Result
from tagcor_ledger.application.templates import TemplateService
from tagcor_ledger.application.transaction_service import (
    AddTransaction,
    AddTransactionRequest,
    AddTransfer,
    AddTransferRequest,
    ListTransactions,
    TransactionQuery,
)
from tagcor_ledger.domain.models import CreateBalanceSnapshotRequest
from tagcor_ledger.infrastructure.sqlite_store import NotFoundError


@dataclass(frozen=True)
class Case:
    """一個 use case ＋ 它底下那個「假裝找不到資料」的 store 方法。"""

    label: str
    build: Callable[[AppPaths], Any]
    store_method: str
    call: Callable[[Any], Result]
    code: str = "ACCOUNT_NOT_FOUND"


def _template(service: TemplateService) -> Any:
    return service.new_template(
        name="早餐",
        entry_type="expense",
        account_id="acct_cash",
        destination_account_id=None,
        category_id="cat_food_711",
        amount_minor=6_000,
        description="",
    )


CASES: list[Case] = [
    # ---- TemplateService：五個單層 handler，全部走 STORE_FAILURES ----
    Case(
        "templates.save_template",
        TemplateService,
        "save_template",
        lambda s: s.save_template(_template(s)),
    ),
    Case(
        "templates.archive_template",
        TemplateService,
        "archive_template",
        lambda s: s.archive_template("tpl_x"),
    ),
    Case(
        "templates.restore_template",
        TemplateService,
        "restore_template",
        lambda s: s.restore_template("tpl_x"),
    ),
    Case(
        "templates.delete_template",
        TemplateService,
        "delete_template",
        lambda s: s.delete_template("tpl_x"),
    ),
    Case(
        "templates.set_template_order",
        TemplateService,
        "set_template_order",
        lambda s: s.set_template_order(["tpl_x"]),
    ),
    # ---- BalanceSnapshotService：`_balance_gap_for_snapshot()` 真的會丟 ----
    Case(
        "balance.create",
        BalanceSnapshotService,
        "create_balance_snapshot",
        lambda s: s.create(
            CreateBalanceSnapshotRequest(
                account_id="acct_cash",
                observed_at="2026-08-22T10:00:00+08:00",
                actual_balance="100",
            )
        ),
    ),
    Case(
        "balance.list",
        BalanceSnapshotService,
        "list_balance_gaps",
        lambda s: s.list(),
    ),
    Case(
        "balance.latest_gap",
        BalanceSnapshotService,
        "latest_balance_gap",
        lambda s: s.latest_gap("acct_cash"),
    ),
    Case(
        "balance.list_gap_transactions",
        BalanceSnapshotService,
        "list_transactions_for_balance_gap",
        lambda s: s.list_gap_transactions(
            account_id="acct_cash",
            period_start=None,
            period_end="2026-08-22",
        ),
    ),
    # ---- 交易：兩層寫入路徑的第一層漏了 NotFoundError ----
    Case(
        "transaction.add",
        AddTransaction,
        "create_transaction",
        lambda s: s.execute(
            AddTransactionRequest(
                occurred_at="2026-08-22T10:00:00+08:00",
                entry_type="expense",
                amount="100",
            )
        ),
    ),
    Case(
        "transaction.transfer",
        AddTransfer,
        "create_transfer",
        lambda s: s.execute(
            AddTransferRequest(
                occurred_at="2026-08-22T10:00:00+08:00",
                amount="100",
                source_account_id="acct_cash",
                destination_account_id="acct_post",
            )
        ),
    ),
    Case(
        "transaction.list",
        ListTransactions,
        "list_transactions",
        lambda s: s.execute(TransactionQuery()),
    ),
    # ---- 定存：接住了，但把兩個碼壓成同一句話 ----
    Case(
        "deposit.skip",
        DepositService,
        "settle_event",
        lambda s: s.skip("evt_x"),
        code="DEPOSIT_EVENT_NOT_FOUND",
    ),
]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.label)
def test_a_store_not_found_becomes_a_chinese_failure(case: Case, tmp_path: Path) -> None:
    """把 store 方法換成會丟 `NotFoundError` 的假貨，使用者要拿到中文的 `Result.fail`。

    **沒接住的話這條測試會 error 而不是 fail** —— 例外直接穿過 `case.call()`。
    那正是使用者看到全域錯誤對話框的那條路。
    """
    paths = resolve_app_paths(tmp_path / "ledger-data")
    service = case.build(paths)

    def raiser(*args: object, **kwargs: object) -> None:
        raise NotFoundError(case.code)

    setattr(service.store, case.store_method, raiser)

    result = case.call(service)

    assert not result.success, f"{case.label} 應該失敗"
    assert result.error_code == case.code, (
        f"{case.label} 回的碼是 {result.error_code}，不是 store 丟的 {case.code} —— "
        "碼被塌掉了，畫面上那句話講的就不是真正發生的事"
    )
    assert result.message == ERROR_MESSAGES[case.code]
    assert case.code not in result.message, "英文碼不准出現在畫面訊息裡"


def test_the_sabotage_actually_reaches_the_store() -> None:
    """陽性對照：確認每一個 `store_method` 真的是那個 store 上的方法。

    打錯字的話 `setattr` 會安靜地掛一個沒人呼叫的屬性上去，
    上面那一批就會全部變成「呼叫成功」而不是「接住了例外」。
    """
    from tagcor_ledger.infrastructure.sqlite_store import LedgerStore

    missing = sorted(
        {case.store_method for case in CASES if not hasattr(LedgerStore, case.store_method)}
    )
    assert not missing, f"LedgerStore 上沒有這些方法，測試表寫錯了：{missing}"
