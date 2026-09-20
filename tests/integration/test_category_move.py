"""項目更改所屬類別：A 類別的 a → B 類別的 a，歷史交易與模板跟著走。

交易記的是**項目**（`category_allocations.category_id`），類別是查詢時從 `parent_id`
算出來的 —— 所以搬項目不用碰任何一筆交易，但 FTS 索引把上層名稱也塞進去了，那個要重建。
這裡驗的就是「不用碰」與「要重建」兩件事各自有沒有做對。
"""

from __future__ import annotations

from pathlib import Path
import sqlite3

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.application.catalogs import CategoryService
from tagcor_ledger.application.failures import ERROR_MESSAGES
from tagcor_ledger.domain.models import TransactionFilter, TransactionTemplate
from tagcor_ledger.domain.money import Money
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


def _service(tmp_path: Path) -> CategoryService:
    return CategoryService(resolve_app_paths(tmp_path / "ledger-data"))


def _record(store: LedgerStore, item_id: str, description: str) -> str:
    transaction_id = f"txn_{description}"
    store.create_transaction(
        transaction_id=transaction_id,
        entry_type="expense",
        occurred_at="2026-08-19T10:00:00+08:00",
        money=Money(85, "TWD"),
        account_id="acct_cash",
        category_id=item_id,
        description=description,
        source="test",
        correlation_id="corr_test",
    )
    return transaction_id


def _search(store: LedgerStore, text: str) -> list[str]:
    records, _cursor = store.list_transactions(
        transaction_filter=TransactionFilter(search=text)
    )
    return [record.transaction_id for record in records]


def test_moving_an_item_moves_its_history_and_the_search_index(tmp_path: Path) -> None:
    """搬完之後：交易的類別是新的、用新類別篩得到、搜新類別名找得到、搜舊類別名找不到。

    種子資料是「伙食 / 7-11」。把 7-11 搬到「交通」底下。
    """
    service = _service(tmp_path)
    store = service.store
    transport = store.create_category(name="交通").category_id
    transaction_id = _record(store, "cat_food_711", "午餐")
    assert _search(store, "伙食") == [transaction_id], "搬之前用舊類別名要搜得到"

    result = service.move("cat_food_711", parent_id=transport)
    assert result.success, result.message

    moved = store.get_transaction(transaction_id)
    assert moved.category_id == transport
    assert moved.category_name == "交通"
    assert moved.subcategory_id == "cat_food_711"
    assert moved.subcategory_name == "7-11"

    by_parent, _cursor = store.list_transactions(
        transaction_filter=TransactionFilter(category_id=transport)
    )
    assert [record.transaction_id for record in by_parent] == [transaction_id]
    assert _search(store, "交通") == [transaction_id], "FTS 索引要重建成新類別名"
    assert _search(store, "伙食") == [], "舊類別名不該再搜得到這一筆"


def test_a_template_follows_the_item(tmp_path: Path) -> None:
    service = _service(tmp_path)
    store = service.store
    transport = store.create_category(name="交通").category_id
    store.save_template(
        TransactionTemplate(
            template_id="tpl_lunch",
            name="午餐",
            status="active",
            entry_type="expense",
            account_id="acct_cash",
            destination_account_id=None,
            category_id="cat_food_711",
            amount_minor=85,
            currency="TWD",
            description="",
            sort_order=100,
        )
    )
    assert service.move("cat_food_711", parent_id=transport).success

    row = next(row for row in store.list_templates() if row.template.template_id == "tpl_lunch")
    assert row.category_name == "交通"
    assert row.subcategory_name == "7-11"


def test_the_moved_item_lands_at_the_end_of_its_new_category(tmp_path: Path) -> None:
    """`sort_order` 落在新類別的最後（該組最大值 +10），不管它在舊類別排第幾。"""
    service = _service(tmp_path)
    store = service.store
    transport = store.create_category(name="交通").category_id
    mrt = store.create_category(name="捷運", parent_id=transport).category_id
    gas = store.create_category(name="加油", parent_id=transport).category_id
    store.set_category_order([gas, mrt], parent_id=transport, level=2)

    assert service.move("cat_food_711", parent_id=transport).success
    ordered = [item.category_id for item in store.list_categories(parent_id=transport)]
    assert ordered == [gas, mrt, "cat_food_711"]
    sort_orders = {
        item.category_id: item.sort_order for item in store.list_categories(parent_id=transport)
    }
    assert sort_orders["cat_food_711"] == max(sort_orders[gas], sort_orders[mrt]) + 10
    assert store.list_categories(parent_id="cat_food") == [], "舊類別底下不該還有它"


def test_moving_writes_an_audit_row_with_both_parents(tmp_path: Path) -> None:
    service = _service(tmp_path)
    transport = service.store.create_category(name="交通").category_id
    assert service.move("cat_food_711", parent_id=transport).success

    with sqlite3.connect(service.store.paths.database_path) as connection:
        row = connection.execute(
            "SELECT details_json FROM audit_events WHERE action = 'category.move'"
        ).fetchone()
    assert row is not None, "搬移要留稽核列"
    assert "cat_food" in row[0] and transport in row[0]


def test_a_name_clash_in_the_target_category_is_refused_and_blames_the_other_one(
    tmp_path: Path,
) -> None:
    """目標類別底下已經有同名的使用中項目：擋下來，而且訊息要指向**另外那一個**。"""
    service = _service(tmp_path)
    store = service.store
    transport = store.create_category(name="交通").category_id
    store.create_category(name="7-11", parent_id=transport)
    before = store.list_categories(parent_id="cat_food")

    result = service.move("cat_food_711", parent_id=transport)
    assert not result.success
    assert result.error_code == "CATEGORY_ACTIVE_NAME_CONFLICT"
    assert "新的所屬類別" in result.message, result.message
    assert "CATEGORY" not in result.message, "英文碼漏到畫面上了"
    assert store.list_categories(parent_id="cat_food") == before, "被擋下來就什麼都不該變"


def test_every_other_refusal_has_its_own_code(tmp_path: Path) -> None:
    """同一個類別、搬類別本身、目標已封存、目標不是第一層、項目已封存 —— 各自一個碼。"""
    service = _service(tmp_path)
    store = service.store
    transport = store.create_category(name="交通").category_id
    mrt = store.create_category(name="捷運", parent_id=transport).category_id
    archived_parent = store.create_category(name="舊類別").category_id
    store.archive_category(archived_parent)
    archived_item = store.create_category(name="舊項目", parent_id="cat_food").category_id
    store.archive_category(archived_item)

    cases = {
        "CATEGORY_PARENT_UNCHANGED": ("cat_food_711", "cat_food"),
        "CATEGORY_NOT_AN_ITEM": ("cat_food", transport),
        "CATEGORY_PARENT_INVALID": ("cat_food_711", archived_parent),
        "CATEGORY_NOT_FOUND": (archived_item, transport),
    }
    for expected, (item_id, target) in cases.items():
        result = service.move(item_id, parent_id=target)
        assert not result.success, expected
        assert result.error_code == expected, (expected, result.error_code)
        assert result.message == ERROR_MESSAGES[expected]
        assert expected not in result.message

    # 目標是第二層（項目底下不能再掛項目）—— 同 `CATEGORY_PARENT_INVALID`。
    result = service.move("cat_food_711", parent_id=mrt)
    assert result.error_code == "CATEGORY_PARENT_INVALID"
