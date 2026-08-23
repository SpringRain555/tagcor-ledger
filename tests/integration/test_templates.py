"""模板的 use case：三種流向、可留空的金額、空主鍵要被擋下來。

**這個檔案以前叫 `test_phase2_automation.py`**，還測著定期收支的產生、確認、略過與
批次確認。v0.23.0 移除定期收支之後那些測試連同功能一起走了
（[ADR-0011](../../docs/decisions/ADR-0011-drop-recurring-schedules.md)），
只有兩條被搬走而不是刪掉：

- **「確認出來的交易要走共用寫入路徑」** → `test_deposits.py`。那條守的是
  「一筆交易長什麼樣只有一個地方說了算」，而定存確認同樣會建立交易。
- **「一次操作一個 correlation_id」** → **沒有搬，因為那個不變量對定存不成立**。
  定存的一次確認可能寫出兩筆交易（本金轉帳 ＋ 利息收入），而
  `transactions.correlation_id` 是 UNIQUE，所以那邊刻意每一筆各自產生一個
  （見 `application/deposits/postings.py`）。搬過去會是一條斷言錯誤規則的測試。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.application.templates import TemplateService
from tagcor_ledger.infrastructure.database import connect_database
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


def _row_count(paths, table: str) -> int:
    with connect_database(paths.database_path) as connection:
        row = connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
    return int(row["n"])


def test_templates_support_all_transaction_types_and_optional_amount(
    tmp_path: Path,
) -> None:
    paths = resolve_app_paths(tmp_path / "ledger")
    service = TemplateService(paths)
    LedgerStore(paths).create_account(name="銀行")
    bank_id = LedgerStore(paths).list_accounts()[1].account_id
    templates = [
        service.new_template(
            name="早餐",
            entry_type="expense",
            account_id="acct_cash",
            destination_account_id=None,
            category_id="cat_food_711",
            amount_minor=None,
            description="",
        ),
        service.new_template(
            name="薪水",
            entry_type="income",
            account_id=bank_id,
            destination_account_id=None,
            category_id="cat_food_711",
            amount_minor=50_000,
            description="",
        ),
        service.new_template(
            name="轉現金",
            entry_type="transfer",
            account_id=bank_id,
            destination_account_id="acct_cash",
            category_id=None,
            amount_minor=3_000,
            description="",
        ),
    ]
    for template in templates:
        assert service.save_template(template).success
    loaded = service.list_templates().details["templates"]
    assert {item["entry_type"] for item in loaded} == {
        "expense",
        "income",
        "transfer",
    }
    assert next(item for item in loaded if item["name"] == "早餐")["amount_minor"] is None


def test_a_template_without_an_identifier_is_refused_and_writes_nothing(
    tmp_path: Path,
) -> None:
    """空主鍵不是「存不進去」，是**會安靜地存進去**，所以要明確擋。

    `save_template()` 是 `ON CONFLICT(template_id) DO UPDATE` 的 UPSERT，而空字串是
    一個合法的主鍵值 —— `template_id=""` 不會撞任何約束，會寫出一列主鍵是空字串的
    模板；再存一次空字串就 UPDATE 到同一列上。2026-08 寫測試 helper 時就是這樣讓
    三個模板塌成一列的，而且當下看起來像「模板沒建成功」，完全指不到真正的原因。

    **這條測試同時斷言「回失敗」與「資料表沒有多出任何一列」。** 只斷言前者不夠 ——
    UPSERT 先寫進去、之後才回失敗的實作照樣會綠。
    """
    paths = resolve_app_paths(tmp_path / "ledger")
    service = TemplateService(paths)

    template = replace(
        service.new_template(
            name="早餐",
            entry_type="expense",
            account_id="acct_cash",
            destination_account_id=None,
            category_id="cat_food_711",
            amount_minor=None,
            description="",
        ),
        template_id="   ",
    )

    result = service.save_template(template)

    assert not result.success
    assert result.error_code == "TEMPLATE_ID_REQUIRED", result.message
    assert _row_count(paths, "transaction_templates") == 0
