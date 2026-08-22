"""走過那幾條「有寫、但沒有任何測試碰過」的防禦分支。

2026-08-22 用行追蹤掃出來的缺口。這些分支分成兩種，兩種都值得測，但理由不同：

**一、UI 走不到，但 store 走得到。** `CURRENCY_MISMATCH` 就是這種 —— 介面沒有地方
可以建非 TWD 的帳戶，但 `create_account(currency=...)` 是 store 的公開參數。
「目前的 UI 不會這樣呼叫」不等於「這條路不存在」。

**二、UI 那一層已經擋過了，但 store 自己那一道沒人驗。** `TRANSFER_SAME_ACCOUNT`
就是這種。兩道檢查是刻意的（UI 那道給使用者好訊息，store 那道保證資料庫不會拿到
壞資料），但只測上面那道的話，下面那道被刪掉不會有任何東西變紅 ——
`lessons.md` 2026-08-21 那條「把 `DELETE` 拿掉，整包測試照樣全綠」講的就是這件事。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.application.settings import ApplicationSettings, SettingsService
from tagcor_ledger.domain.money import Money
from tagcor_ledger.infrastructure.database import connect_database
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


def _store(tmp_path: Path) -> LedgerStore:
    return LedgerStore(resolve_app_paths(tmp_path / "ledger-data"))


# --------------------------------------------------------------- stores/base.py


def test_writing_a_twd_transaction_to_a_foreign_currency_account_is_refused(
    tmp_path: Path,
) -> None:
    """`CURRENCY_MISMATCH`：帳戶幣別與金額幣別不同就不准寫。

    UI 沒有建立外幣帳戶的入口，但 `create_account(currency=...)` 有。
    """
    store = _store(tmp_path)
    account = store.create_account(name="美金帳戶", currency="USD")

    with pytest.raises(ValueError, match="CURRENCY_MISMATCH"):
        store.create_transaction(
            transaction_id="txn_currency",
            entry_type="expense",
            occurred_at="2026-08-22T10:00:00+08:00",
            money=Money(amount_minor=100, currency="TWD"),
            account_id=account.account_id,
            category_id="cat_food_711",
            description="",
            source="manual",
            correlation_id="corr_currency",
        )


def test_writing_a_transaction_to_an_archived_category_is_refused(tmp_path: Path) -> None:
    """`CATEGORY_NOT_ACTIVE`：封存的項目不能拿來記帳。"""
    store = _store(tmp_path)
    store.archive_category("cat_food_711")

    with pytest.raises(ValueError, match="CATEGORY_NOT_ACTIVE"):
        store.create_transaction(
            transaction_id="txn_archived",
            entry_type="expense",
            occurred_at="2026-08-22T10:00:00+08:00",
            money=Money(amount_minor=100, currency="TWD"),
            account_id="acct_cash",
            category_id="cat_food_711",
            description="",
            source="manual",
            correlation_id="corr_archived",
        )


def test_the_store_refuses_a_transfer_to_the_same_account(tmp_path: Path) -> None:
    """`TRANSFER_SAME_ACCOUNT`：**store 這一道**也要擋，不是只有 UI。

    介面上轉出與轉入是兩個下拉選單，選一樣的會先被擋掉。但那道擋在 UI，
    刪掉它 store 這一道要接住 —— 而在這條測試之前，沒有東西驗過 store 那道。
    """
    store = _store(tmp_path)

    with pytest.raises(ValueError, match="TRANSFER_SAME_ACCOUNT"):
        store.create_transfer(
            transaction_id="txn_same",
            occurred_at="2026-08-22T10:00:00+08:00",
            money=Money(amount_minor=100, currency="TWD"),
            source_account_id="acct_cash",
            destination_account_id="acct_cash",
            description="",
            correlation_id="corr_same",
        )


def test_refreshing_the_search_index_for_a_missing_transaction_does_nothing(
    tmp_path: Path,
) -> None:
    """`_refresh_fts()` 對不存在的交易安靜返回，不丟例外也不寫索引。

    正常流程走不到（它只在剛寫完一筆交易之後被呼叫），所以直接呼叫它。
    **這條測的是那個 early return 真的存在** —— 拿掉它就會在
    `rows["description"]` 上噴 `TypeError`。
    """
    paths = resolve_app_paths(tmp_path / "ledger-data")
    store = LedgerStore(paths)

    with connect_database(paths.database_path) as connection:
        store._refresh_fts(connection, "txn_does_not_exist")
        remaining = connection.execute(
            "SELECT COUNT(*) AS n FROM transaction_fts WHERE transaction_id = ?",
            ("txn_does_not_exist",),
        ).fetchone()
    assert int(remaining["n"]) == 0


# ------------------------------------------------------- application/settings.py


def _settings(tmp_path: Path) -> SettingsService:
    paths = resolve_app_paths(tmp_path / "ledger-data")
    LedgerStore(paths)  # 建資料庫與預設帳戶
    return SettingsService(paths)


def test_an_unknown_entry_type_is_refused(tmp_path: Path) -> None:
    result = _settings(tmp_path).update(
        ApplicationSettings(
            default_account_id="acct_cash",
            default_entry_type="adjustment",
            transactions_page_size=50,
            balance_snapshot_reminder=True,
        )
    )
    assert not result.success
    assert result.error_code == "SETTINGS_ENTRY_TYPE_INVALID"


@pytest.mark.parametrize("size", [0, 1, 30, 200, -50])
def test_only_three_page_sizes_are_accepted(tmp_path: Path, size: int) -> None:
    """20／50／100 之外一律拒絕。

    **`order_by()` 那條白名單擋的是欄位，這條擋的是筆數** —— 兩者都是
    「畫面送什麼進來都不能直接相信」的同一條紀律。
    """
    result = _settings(tmp_path).update(
        ApplicationSettings(
            default_account_id="acct_cash",
            default_entry_type="expense",
            transactions_page_size=size,
            balance_snapshot_reminder=True,
        )
    )
    assert not result.success
    assert result.error_code == "SETTINGS_PAGE_SIZE_INVALID"


@pytest.mark.parametrize("state", ["missing", "archived"])
def test_the_default_account_must_exist_and_be_active(tmp_path: Path, state: str) -> None:
    """`DEFAULT_ACCOUNT_NOT_ACTIVE` 有兩條路：帳戶不存在、帳戶已封存。

    兩條都要走過 —— 只測其中一條的話，`account is None or ...` 那個 `or`
    有一半沒有人碰過。
    """
    paths = resolve_app_paths(tmp_path / "ledger-data")
    store = LedgerStore(paths)
    if state == "archived":
        account = store.create_account(name="舊帳戶")
        store.archive_account(account.account_id)
        account_id = account.account_id
    else:
        account_id = "acct_never_existed"

    result = SettingsService(paths).update(
        ApplicationSettings(
            default_account_id=account_id,
            default_entry_type="expense",
            transactions_page_size=50,
            balance_snapshot_reminder=True,
        )
    )
    assert not result.success
    assert result.error_code == "DEFAULT_ACCOUNT_NOT_ACTIVE"
    assert "封存" in result.message, "訊息要講人話，不是印英文碼"


def test_a_valid_settings_update_is_saved(tmp_path: Path) -> None:
    """對照組：上面四條都是拒絕，這條確認正常的那條路真的會寫進去。

    少了它，把 `update()` 改成無條件 `Result.fail` 也會全綠。
    """
    service = _settings(tmp_path)
    result = service.update(
        ApplicationSettings(
            default_account_id="acct_cash",
            default_entry_type="income",
            transactions_page_size=100,
            balance_snapshot_reminder=False,
        )
    )
    assert result.success, result.message

    saved = service.get()
    assert saved.default_entry_type == "income"
    assert saved.transactions_page_size == 100
    assert saved.balance_snapshot_reminder is False
