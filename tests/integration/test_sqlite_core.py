from pathlib import Path
import sqlite3

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.application.catalogs import AccountService, CategoryService
from tagcor_ledger.application.transaction_service import (
    AddTransaction,
    AddTransactionRequest,
    AddTransfer,
    AddTransferRequest,
    ListTransactions,
    TransactionQuery,
    UpdateTransaction,
    UpdateTransactionRequest,
    VoidTransaction,
)
from tagcor_ledger.domain.models import TransactionFilter
from tagcor_ledger.domain.money import Money
from tagcor_ledger.infrastructure.database import connect_database
from tagcor_ledger.infrastructure.maintenance import MaintenanceService
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore
from tagcor_ledger.ui.formatting import result_message


def test_transfer_is_balanced_and_atomic(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger-data")
    store = LedgerStore(paths)
    second = AccountService(paths, store).create(name="銀行", opening_balance="1000")
    destination_id = second.details["account_id"]

    result = AddTransfer(paths, store).execute(
        AddTransferRequest(
            occurred_at="2026-06-24T10:00:00+08:00",
            amount="300",
            source_account_id=destination_id,
            destination_account_id="acct_cash",
        )
    )

    assert result.success is True
    with sqlite3.connect(paths.database_path) as connection:
        postings = connection.execute(
            "SELECT amount_minor FROM account_postings ORDER BY sequence"
        ).fetchall()
    assert postings == [(-300,), (300,)]
    assert sum(row[0] for row in postings) == 0
    assert store.account_balance_minor(destination_id) == 700
    assert store.account_balance_minor("acct_cash") == 300

    assert AccountService(paths, store).rename(destination_id, "主要銀行").success
    assert store.list_accounts()[1].name == "主要銀行"


def test_creating_an_account_with_a_taken_name_says_which_name_and_leaks_no_sql(
    tmp_path: Path,
) -> None:
    """同名帳戶的錯誤訊息要說得出**是哪個名字**，而且不能把 SQL 丟到畫面上。

    使用者實際看到的是：
    「帳戶無法建立，請確認名稱沒有重複且金額格式正確。
      （UNIQUE constraint failed: accounts.name）」

    三個問題：SQLite 的內部訊息漏到畫面上、把兩個不同的成因（重名／金額格式）
    綁在同一句話裡所以沒有一個是可行動的、而且沒說是哪個名字重複。
    """
    paths = resolve_app_paths(tmp_path / "ledger")
    service = AccountService(paths)

    assert service.create(name="郵局定存", opening_balance="100000").success

    again = service.create(name="郵局定存", opening_balance="0")
    assert not again.success
    assert again.error_code == "ACCOUNT_ACTIVE_NAME_CONFLICT"

    text = result_message(again)
    assert "郵局定存" in text, f"訊息沒說是哪個名字重複：{text}"
    for leak in ("UNIQUE", "constraint", "sqlite3", "accounts.name", "IntegrityError"):
        assert leak not in text, f"畫面上的訊息漏出了實作細節「{leak}」：{text}"

    # 前後空白會被 strip 掉，所以「郵局定存 」也是同一個名字。
    padded = service.create(name="郵局定存 ", opening_balance="0")
    assert not padded.success
    assert padded.error_code == "ACCOUNT_ACTIVE_NAME_CONFLICT"

    # 名稱欄位是 COLLATE NOCASE，英文大小寫不同仍算同一個。
    assert service.create(name="Post", opening_balance="0").success
    assert service.create(name="POST", opening_balance="0").error_code == (
        "ACCOUNT_ACTIVE_NAME_CONFLICT"
    )


def test_a_bad_opening_balance_is_a_different_error_from_a_taken_name(
    tmp_path: Path,
) -> None:
    """金額格式與名稱重複是兩件事，錯誤碼不能共用 —— 共用就沒辦法告訴使用者要改哪個。"""
    paths = resolve_app_paths(tmp_path / "ledger")
    service = AccountService(paths)

    bad = service.create(name="新帳戶", opening_balance="一百塊")
    assert not bad.success
    assert bad.error_code == "ACCOUNT_OPENING_BALANCE_INVALID"
    assert "新帳戶" not in result_message(bad), "金額有問題時不該把矛頭指向名稱"

    blank = service.create(name="   ", opening_balance="0")
    assert not blank.success
    assert blank.error_code == "ACCOUNT_NAME_REQUIRED"


def test_editing_a_transaction_leaves_no_stale_row_in_the_search_index(
    tmp_path: Path,
) -> None:
    """改備註之後，**舊的字搜不到、新的字搜得到，而且只有一列**。

    FTS 是另一張表，不會因為 `transactions.description` 改了就自己跟著改 —— 要靠
    `_refresh_fts()` 先 `DELETE` 再 `INSERT`。少了那個 `DELETE`，舊索引留在原地，
    症狀是「改過的交易用舊關鍵字還搜得到」，而且每改一次就多長一列。

    這條測試是 2026-08-21 收編 `automation_store` 時補的：當時發現兩份
    `_refresh_fts` 只有一份會 `DELETE`，而**把 `DELETE` 拿掉整包測試照樣全綠** ——
    也就是說這個行為從來沒有被測過。
    """
    paths = resolve_app_paths(tmp_path / "ledger")
    store = LedgerStore(paths)
    created = store.create_transaction(
        transaction_id="txn_fts",
        entry_type="expense",
        occurred_at="2026-06-24T12:00:00+08:00",
        money=Money(120),
        account_id="acct_cash",
        category_id="cat_food_711",
        description="舊備註",
        source="manual",
        correlation_id="corr_fts_1",
    )

    found, _ = store.list_transactions(limit=10, transaction_filter=TransactionFilter(search="舊備註"))
    assert [item.transaction_id for item in found] == ["txn_fts"]

    store.update_transaction(
        transaction_id="txn_fts",
        expected_revision=created.revision,
        occurred_at="2026-06-24T12:00:00+08:00",
        money=Money(120),
        account_id="acct_cash",
        category_id="cat_food_711",
        description="新備註",
        correlation_id="corr_fts_2",
    )

    stale, _ = store.list_transactions(
        limit=10, transaction_filter=TransactionFilter(search="舊備註")
    )
    assert stale == [], "改過備註之後，舊關鍵字還搜得到 —— FTS 留下了過期的索引列"

    fresh, _ = store.list_transactions(
        limit=10, transaction_filter=TransactionFilter(search="新備註")
    )
    assert [item.transaction_id for item in fresh] == ["txn_fts"]

    with connect_database(paths.database_path) as connection:
        rows = connection.execute(
            "SELECT COUNT(*) AS n FROM transaction_fts WHERE transaction_id = ?",
            ("txn_fts",),
        ).fetchone()
    assert int(rows["n"]) == 1, "一筆交易在 FTS 裡只能有一列，改幾次都一樣"


def test_keyset_pagination_search_and_void(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger-data")
    store = LedgerStore(paths)
    add = AddTransaction(paths, store)
    for index in range(3):
        result = add.execute(
            AddTransactionRequest(
                occurred_at=f"2026-06-2{index + 1}T10:00:00+08:00",
                entry_type="expense",
                amount=str(index + 1),
                description=f"便利商店第 {index + 1} 筆",
            )
        )
        assert result.success

    first = ListTransactions(paths, store).execute(
        TransactionQuery(
            limit=2,
            transaction_filter=TransactionFilter(search="便利商店"),
        )
    )
    assert len(first.details["transactions"]) == 2
    assert first.details["next_cursor"] is not None
    cursor = first.details["next_cursor"]
    second = ListTransactions(paths, store).execute(
        TransactionQuery(
            limit=2,
            cursor_occurred_at=cursor["occurred_at"],
            cursor_transaction_id=cursor["transaction_id"],
            transaction_filter=TransactionFilter(search="便利商店"),
        )
    )
    assert len(second.details["transactions"]) == 1

    transaction_id = first.details["transactions"][0]["transaction_id"]
    assert VoidTransaction(paths, store).execute(transaction_id).success
    assert len(ListTransactions(paths, store).execute().details["transactions"]) == 2


def test_backup_and_csv_export(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger-data")
    AddTransaction(paths).execute(
        AddTransactionRequest(
            occurred_at="2026-06-24T10:00:00+08:00",
            entry_type="expense",
            amount="85",
            description="早餐",
        )
    )
    service = MaintenanceService(paths)

    backup = service.create_backup()
    exported = service.export_transactions_csv()

    assert (backup / "ledger.sqlite3").is_file()
    assert (backup / "backup_manifest.json").is_file()
    assert exported.read_text(encoding="utf-8-sig").startswith("交易時間,流向,帳戶")


def test_update_uses_revision_and_restore_reverts_later_data(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger-data")
    store = LedgerStore(paths)
    created = AddTransaction(paths, store).execute(
        AddTransactionRequest(
            occurred_at="2026-06-24T10:00:00+08:00",
            entry_type="expense",
            amount="85",
            description="原備註",
        )
    )
    transaction = created.details["transaction"]
    updated = UpdateTransaction(paths, store).execute(
        UpdateTransactionRequest(
            transaction_id=transaction["transaction_id"],
            expected_revision=1,
            occurred_at="2026-06-24T11:00:00+08:00",
            amount="100",
            account_id="acct_cash",
            category_id="cat_food_711",
            description="新備註",
        )
    )
    assert updated.success
    assert updated.details["transaction"]["revision"] == 2
    assert store.account_balance_minor("acct_cash") == -100

    maintenance = MaintenanceService(paths)
    backup = maintenance.create_backup()
    AddTransaction(paths, store).execute(
        AddTransactionRequest(
            occurred_at="2026-06-24T12:00:00+08:00",
            entry_type="expense",
            amount="50",
        )
    )
    assert store.account_balance_minor("acct_cash") == -150

    maintenance.restore_backup(backup)

    assert LedgerStore(paths).account_balance_minor("acct_cash") == -100

def test_account_balances_match_the_single_account_query(tmp_path: Path) -> None:
    """一次算完全部的那句，結果必須跟一個一個算完全相同。

    兩句 SQL 是同一段邏輯抄兩份（差別只有 `WHERE`），所以**只改一邊**是最容易犯的錯：
    畫面上的餘額會跟餘額盤點的預期值對不起來，而那種不一致看起來像帳記錯了。

    情境刻意涵蓋三種會讓兩句分歧的東西：期初餘額、轉帳（同一筆兩個 posting）、
    作廢（不該算進去）。
    """
    paths = resolve_app_paths(tmp_path / "ledger-data")
    store = LedgerStore(paths)
    bank = AccountService(paths, store).create(name="銀行", opening_balance="1000")
    bank_id = str(bank.details["account_id"])
    idle = AccountService(paths, store).create(name="沒有任何交易", opening_balance="7")
    idle_id = str(idle.details["account_id"])

    AddTransfer(paths, store).execute(
        AddTransferRequest(
            occurred_at="2026-06-24T10:00:00+08:00",
            amount="300",
            source_account_id=bank_id,
            destination_account_id="acct_cash",
        )
    )
    voided = AddTransaction(paths, store).execute(
        AddTransactionRequest(
            occurred_at="2026-06-24T11:00:00+08:00",
            entry_type="expense",
            amount="500",
            account_id=bank_id,
            category_id="cat_food_711",
        )
    )
    VoidTransaction(paths, store).execute(str(voided.details["transaction"]["transaction_id"]))

    balances = store.account_balances()
    accounts = store.list_accounts(include_archived=True)
    assert {account.account_id for account in accounts} == set(balances)
    for account in accounts:
        assert balances[account.account_id] == store.account_balance_minor(account.account_id), (
            account.name
        )

    # 陽性對照：這三個值真的不一樣，否則上面那圈等於在比一堆 0。
    assert balances[bank_id] == 700
    assert balances["acct_cash"] == 300
    assert balances[idle_id] == 7


def test_listing_accounts_opens_a_constant_number_of_connections(tmp_path: Path) -> None:
    """帳戶再多，列一次帳戶開的連線數不變。

    以前是每個帳戶各算一次餘額，而 `connect_database` 每次呼叫都開一條新連線 ＋
    四個 PRAGMA —— 列 8 個帳戶就是 9 條。這條測試量的是**連線數隨帳戶數的斜率**，
    不是絕對值，所以之後多加一句查詢也不會誤報。
    """
    paths = resolve_app_paths(tmp_path / "ledger-data")
    store = LedgerStore(paths)
    service = AccountService(paths, store)

    def connections() -> int:
        opened = 0
        original = sqlite3.connect

        def counted(*args: object, **kwargs: object) -> sqlite3.Connection:
            nonlocal opened
            opened += 1
            return original(*args, **kwargs)  # type: ignore[arg-type]

        sqlite3.connect = counted  # type: ignore[assignment]
        try:
            service.list(include_archived=True)
        finally:
            sqlite3.connect = original  # type: ignore[assignment]
        return opened

    baseline = connections()
    assert baseline > 0, "沒有攔截到任何連線，量測方式壞了"

    for index in range(7):
        assert service.create(name=f"帳戶 {index}", opening_balance="0").success
    assert len(store.list_accounts()) == 8

    assert connections() == baseline


def test_listing_the_category_tree_opens_a_constant_number_of_connections(
    tmp_path: Path,
) -> None:
    """類別再多，列一次類別樹開的連線數不變。

    舊的 UI 是先列出所有類別，再對**每一個類別**各查一次子項目 —— 每一次都開一條
    新連線。這條測試量的是斜率，不是絕對值。

    **不加進 `test_query_plans.py`。** 那裡守的是「會長大的表有沒有被掃」，而
    `categories` 的筆數等於你分了幾類，跟記了幾年無關；而且這句是自我 join，
    計畫報的一定是別名（`node` / `parent`），照表名判斷的守門本來就認不出來。
    """
    paths = resolve_app_paths(tmp_path / "ledger-data")
    store = LedgerStore(paths)
    service = CategoryService(paths, store)

    def connections() -> int:
        opened = 0
        original = sqlite3.connect

        def counted(*args: object, **kwargs: object) -> sqlite3.Connection:
            nonlocal opened
            opened += 1
            return original(*args, **kwargs)  # type: ignore[arg-type]

        sqlite3.connect = counted  # type: ignore[assignment]
        try:
            service.list_tree(include_archived=True)
        finally:
            sqlite3.connect = original  # type: ignore[assignment]
        return opened

    baseline = connections()
    assert baseline > 0, "沒有攔截到任何連線，量測方式壞了"

    for index in range(6):
        parent = service.create(name=f"類別 {index}")
        assert parent.success
        for child in range(3):
            assert service.create(
                name=f"項目 {index}-{child}",
                parent_id=str(parent.details["category_id"]),
            ).success

    nodes = service.list_tree(include_archived=True).details["categories"]
    assert len(nodes) == 26, "測試資料沒建起來，這條測試等於沒作用"
    assert connections() == baseline


def test_the_category_tree_carries_the_parent_name_and_item_count(tmp_path: Path) -> None:
    """`parent_name` 與 `item_count` 必須是同一句查出來的，而且值要對。

    「伙食」有子項目，所以它**必須有自己的一列** —— 舊的 UI 就是漏了這一列，
    導致類別改不了名。
    """
    paths = resolve_app_paths(tmp_path / "ledger-data")
    store = LedgerStore(paths)
    service = CategoryService(paths, store)
    assert service.create(name="早餐店", parent_id="cat_food").success
    assert service.create(name="交通").success

    nodes = {
        str(node["category_id"]): node
        for node in service.list_tree(include_archived=True).details["categories"]
    }
    assert nodes["cat_food"]["level"] == 1
    assert nodes["cat_food"]["parent_name"] is None
    assert nodes["cat_food"]["item_count"] == 2
    assert nodes["cat_food_711"]["level"] == 2
    assert nodes["cat_food_711"]["parent_name"] == "伙食"
    assert nodes["cat_food_711"]["item_count"] == 0
    # 沒有子項目的類別也在，而且數字是 0 不是漏掉。
    transport = next(node for node in nodes.values() if node["name"] == "交通")
    assert transport["item_count"] == 0
