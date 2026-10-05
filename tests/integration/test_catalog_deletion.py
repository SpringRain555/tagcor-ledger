"""名冊刪不掉的時候，要說出**是被什麼擋住**。

`ACCOUNT_IN_USE`／`CATEGORY_IN_USE` 以前一碼三義：被交易、盤點或模板擋住，訊息都說
「已經有交易紀錄」—— 那個帳戶可能一筆交易也沒有（`lessons.md` 2026-08-21「一個錯誤碼代表
三件事，訊息就一定寫不好」）。被定存合約引用的帳戶更糟：引用檢查漏了那張表，刪除直接撞上
外鍵，使用者看到的是「帳戶無法刪除。請匯出診斷資訊回報。」—— 一件正常的事被講成 bug。

每一條都**只放一種引用**，所以訊息講的一定是那一種；最後一條確認都拿掉之後刪得掉。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.ui.controller import LedgerController


@pytest.fixture
def controller(tmp_path: Path) -> LedgerController:
    return LedgerController(resolve_app_paths(tmp_path / "data"))


def _account(controller: LedgerController, name: str) -> str:
    created = controller.create_account(name, "0")
    assert created.success, created.message
    return str(created.details["account_id"])


def _deposit(controller: LedgerController, account_id: str, interest_to: str) -> None:
    created = controller.create_deposit_contract(
        account_id=account_id,
        name="郵局定存",
        interest_method="monthly_interest",
        maturity_action="renew_principal_only",
        interest_destination_account_id=interest_to,
        term_months=12,
        opened_on="2026-09-01",
        principal="100000",
        annual_rate_ppm=16_000,
        recorded_on="2026-09-01",
    )
    assert created.success, created.message


def _template(controller: LedgerController, account_id: str, category_id: str) -> str:
    template = controller.new_template(
        name="午餐",
        entry_type="expense",
        account_id=account_id,
        destination_account_id=None,
        category_id=category_id,
        amount_minor=None,
        description="",
    )
    assert controller.save_template(template).success
    return str(template.template_id)


def test_an_account_held_by_a_deposit_contract_says_so(controller: LedgerController) -> None:
    """以前：檢查漏了 `deposit_contracts`，撞上外鍵 →「請匯出診斷資訊回報」。"""
    account_id = _account(controller, "定存專戶")
    _deposit(controller, account_id, interest_to=account_id)

    result = controller.delete_account(account_id)

    assert not result.success
    assert result.error_code == "ACCOUNT_IN_DEPOSITS", result.error_code
    assert "定存" in result.message
    assert "回報" not in result.message, "這不是 bug，是正常的引用"


def test_an_account_used_only_as_the_interest_destination_says_so(
    controller: LedgerController,
) -> None:
    """利息轉入的帳戶也是被合約指著的 —— `interest_destination_account_id` 一樣要查。"""
    principal_id = _account(controller, "定存專戶")
    payout_id = _account(controller, "領息帳戶")
    _deposit(controller, principal_id, interest_to=payout_id)

    result = controller.delete_account(payout_id)

    assert result.error_code == "ACCOUNT_IN_DEPOSITS", result.error_code


def test_an_account_with_only_a_balance_snapshot_says_snapshot(
    controller: LedgerController,
) -> None:
    account_id = _account(controller, "只盤點過")
    assert controller.create_balance_snapshot(
        account_id=account_id,
        observed_at="2026-09-01T09:00:00+08:00",
        actual_balance="0",
        note="",
    ).success

    result = controller.delete_account(account_id)

    assert result.error_code == "ACCOUNT_HAS_SNAPSHOTS", result.error_code
    assert "盤點" in result.message
    assert "交易紀錄" not in result.message, "以前的錯：沒有交易也說「已經有交易紀錄」"


def test_an_account_in_an_archived_template_says_template(controller: LedgerController) -> None:
    """封存的模板看不見，但還指著帳戶 —— 訊息要講得出是模板，而且封存的也算。"""
    account_id = _account(controller, "零用金")
    template_id = _template(controller, account_id, "cat_food_711")
    assert controller.archive_template(template_id).success

    result = controller.delete_account(account_id)

    assert result.error_code == "ACCOUNT_IN_TEMPLATES", result.error_code
    assert "模板" in result.message and "封存" in result.message


def test_an_account_with_a_transaction_says_transaction(controller: LedgerController) -> None:
    account_id = _account(controller, "現金二號")
    assert controller.submit(
        occurred_at="2026-09-01T12:00:00+08:00",
        entry_type="expense",
        amount="85",
        account_id=account_id,
        destination_account_id=None,
        category_id="cat_food_711",
        description="",
    ).success

    result = controller.delete_account(account_id)

    assert result.error_code == "ACCOUNT_HAS_TRANSACTIONS", result.error_code
    assert "交易" in result.message


def test_a_category_in_a_template_only_says_template(controller: LedgerController) -> None:
    created = controller.create_category("外食")
    assert created.success
    parent_id = str(created.details["category_id"])
    item = controller.create_category("便當", parent_id)
    assert item.success
    item_id = str(item.details["category_id"])
    _template(controller, str(controller.account_options()[0]["account_id"]), item_id)

    result = controller.delete_category(item_id)

    assert result.error_code == "CATEGORY_IN_TEMPLATES", result.error_code
    assert "模板" in result.message
    assert "交易紀錄" not in result.message


def test_a_category_with_a_transaction_says_transaction(controller: LedgerController) -> None:
    assert controller.submit(
        occurred_at="2026-09-01T12:00:00+08:00",
        entry_type="expense",
        amount="85",
        account_id=str(controller.account_options()[0]["account_id"]),
        destination_account_id=None,
        category_id="cat_food_711",
        description="",
    ).success

    result = controller.delete_category("cat_food_711")

    assert result.error_code == "CATEGORY_HAS_TRANSACTIONS", result.error_code


def test_an_account_nobody_points_at_can_be_deleted(controller: LedgerController) -> None:
    """陽性對照：上面那些都不是「帳戶一律刪不掉」—— 沒被用過的照樣刪得掉。"""
    account_id = _account(controller, "開錯的帳戶")
    assert controller.delete_account(account_id).success
