"""自訂順序：帳戶、類別／項目、模板三種聚合共用同一套「整組重編」的寫法。

`sort_order` 從 schema v1 就存在、`ORDER BY` 一直在用它，但直到 v0.17 才有人寫它。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.domain.models import CategoryTreeFilter, TransactionTemplate
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


def _store(tmp_path: Path) -> LedgerStore:
    return LedgerStore(resolve_app_paths(tmp_path / "ledger-data"))


def _names(store: LedgerStore, *, level: int, parent_id: str | None = None) -> list[str]:
    """畫面上會看到的順序（`default` = 自訂順序）。"""
    nodes = store.list_category_tree(
        tree_filter=CategoryTreeFilter(level=level, parent_id=parent_id)
    )
    return [node.category.name for node in nodes]


def _ids(store: LedgerStore, *, level: int, parent_id: str | None = None) -> list[str]:
    nodes = store.list_category_tree(
        tree_filter=CategoryTreeFilter(level=level, parent_id=parent_id)
    )
    return [node.category.category_id for node in nodes]


def _make(store: LedgerStore, names: list[str], parent_id: str | None = None) -> dict[str, str]:
    return {
        name: store.create_category(name=name, parent_id=parent_id).category_id
        for name in names
    }


# --- 類別／項目 ---------------------------------------------------------------


def test_new_categories_all_tie_on_sort_order_so_they_fall_back_to_name(
    tmp_path: Path,
) -> None:
    """**這是排序之前的基準行為，記在這裡。**

    `create_category()` 把 `sort_order` 寫死成 100，所以整組平手，實際順序是靠
    `ORDER BY sort_order, name COLLATE NOCASE` 後面那個名稱 tiebreaker 撐著。
    """
    store = _store(tmp_path)
    _make(store, ["丙類", "甲類", "乙類"])
    assert _names(store, level=1)[-3:] == sorted(["丙類", "甲類", "乙類"], key=str.casefold)


def test_the_stored_order_is_exactly_what_you_送進去(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _make(store, ["甲類", "乙類", "丙類"])
    wanted = list(reversed(_ids(store, level=1)))

    store.set_category_order(wanted, parent_id=None, level=1)

    assert _ids(store, level=1) == wanted


def test_the_order_survives_a_reload(tmp_path: Path) -> None:
    """順序要真的寫進資料庫，不是只活在這一個 store 物件裡。"""
    store = _store(tmp_path)
    _make(store, ["甲類", "乙類", "丙類"])
    wanted = list(reversed(_ids(store, level=1)))
    store.set_category_order(wanted, parent_id=None, level=1)

    assert _ids(_store(tmp_path), level=1) == wanted


def test_items_are_ordered_inside_their_own_category(tmp_path: Path) -> None:
    store = _store(tmp_path)
    parents = _make(store, ["甲類", "乙類"])
    _make(store, ["早", "中", "晚"], parent_id=parents["甲類"])
    _make(store, ["外一", "外二"], parent_id=parents["乙類"])

    mine = _ids(store, level=2, parent_id=parents["甲類"])
    others_before = _names(store, level=2, parent_id=parents["乙類"])
    store.set_category_order(list(reversed(mine)), parent_id=parents["甲類"], level=2)

    assert _ids(store, level=2, parent_id=parents["甲類"]) == list(reversed(mine))
    assert _names(store, level=2, parent_id=parents["乙類"]) == others_before, (
        "只排了甲類，乙類底下不該被動到"
    )


def test_a_group_that_is_missing_one_id_is_refused(tmp_path: Path) -> None:
    """少送一個就是清單過期 —— 存下去會把那一筆的位置弄丟。"""
    store = _store(tmp_path)
    _make(store, ["甲類", "乙類", "丙類"])
    everyone = _ids(store, level=1)

    with pytest.raises(ValueError, match="REORDER_LIST_STALE"):
        store.set_category_order(everyone[:-1], parent_id=None, level=1)


def test_an_id_from_another_group_is_refused(tmp_path: Path) -> None:
    """跨組是「換類別」不是「調順序」，這裡擋掉。"""
    store = _store(tmp_path)
    parents = _make(store, ["甲類", "乙類"])
    mine = _ids(store, level=2, parent_id=parents["甲類"])
    intruder = _make(store, ["外人"], parent_id=parents["乙類"])["外人"]

    with pytest.raises(ValueError, match="REORDER_LIST_STALE"):
        store.set_category_order(
            [*mine, intruder], parent_id=parents["甲類"], level=2
        )


def test_a_duplicated_id_is_refused(tmp_path: Path) -> None:
    """同一個 id 送兩次，長度剛好對得上 —— 這是最容易矇混過去的一種壞資料。"""
    store = _store(tmp_path)
    _make(store, ["甲類", "乙類", "丙類"])
    everyone = _ids(store, level=1)
    broken = [everyone[0], everyone[0], *everyone[2:]]
    assert len(broken) == len(everyone)

    with pytest.raises(ValueError, match="REORDER_LIST_STALE"):
        store.set_category_order(broken, parent_id=None, level=1)


def test_the_custom_order_also_drives_the_entry_page_dropdowns(tmp_path: Path) -> None:
    """`list_categories()` 是記帳頁下拉的來源，它也要照自訂順序。

    一份順序，兩個地方看到的一樣 —— 名冊排好了但下拉沒跟著，等於沒排。
    """
    store = _store(tmp_path)
    _make(store, ["甲類", "乙類", "丙類"])
    store.set_category_order(
        list(reversed(_ids(store, level=1))), parent_id=None, level=1
    )

    dropdown = [category.name for category in store.list_categories()]
    assert dropdown == _names(store, level=1)


# --- 帳戶 ---------------------------------------------------------------------


def test_accounts_can_be_reordered_and_the_dropdown_follows(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for name in ("郵局", "悠遊付", "信用卡"):
        store.create_account(name=name)
    before = [account.account_id for account in store.list_accounts()]
    assert len(before) >= 4

    store.set_account_order(list(reversed(before)))

    after = [account.account_id for account in store.list_accounts()]
    assert after == list(reversed(before))
    assert _store(tmp_path).list_accounts()[0].account_id == after[0], "重開之後順序沒留住"


def test_an_incomplete_account_list_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create_account(name="郵局")
    everyone = [account.account_id for account in store.list_accounts()]

    with pytest.raises(ValueError, match="REORDER_LIST_STALE"):
        store.set_account_order(everyone[:-1])


def test_archived_accounts_take_part_in_the_order(tmp_path: Path) -> None:
    """封存的也要排。藏起來的話它的順序值會停在舊的，恢復時就跑到莫名其妙的位置。"""
    store = _store(tmp_path)
    store.create_account(name="郵局")
    store.create_account(name="舊帳戶")
    archived = next(a for a in store.list_accounts() if a.name == "舊帳戶")
    store.archive_account(archived.account_id)

    everyone = [a.account_id for a in store.list_accounts(include_archived=True)]
    assert archived.account_id in everyone
    store.set_account_order(list(reversed(everyone)))

    after = [a.account_id for a in store.list_accounts(include_archived=True)]
    assert after == list(reversed(everyone))


# --- 模板 ---------------------------------------------------------------------


def _template(store: LedgerStore, name: str) -> str:
    """**id 要自己給。** `save_template()` 不產 id（那是 `new_template()` 的事），
    空字串會被 UPSERT 成同一列 —— 三個模板變成一個，測試會用一個看不懂的錯誤失敗。"""
    account = store.list_accounts()[0]
    parent = store.list_categories()[0]
    items = store.list_categories(parent_id=parent.category_id)
    category = items[0] if items else store.create_category(name="臨時項目", parent_id=parent.category_id)
    template = store.save_template(
        TransactionTemplate(
            template_id=f"tpl_{name}",
            name=name,
            status="active",
            entry_type="expense",
            account_id=account.account_id,
            destination_account_id=None,
            category_id=category.category_id,
            amount_minor=None,
            currency="TWD",
            description="",
            sort_order=100,
        )
    )
    return template.template_id


def test_templates_can_be_reordered(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for name in ("早餐", "捷運", "房租"):
        _template(store, name)
    before = [template.template_id for template in store.list_templates()]
    assert len(before) == 3

    store.set_template_order(list(reversed(before)))

    assert [t.template_id for t in store.list_templates()] == list(reversed(before))
    assert [t.template_id for t in _store(tmp_path).list_templates()] == list(
        reversed(before)
    ), "重開之後順序沒留住"


def test_reordering_templates_does_not_run_the_draft_validation(tmp_path: Path) -> None:
    """模板的帳戶被封存了，順序照樣調得動 —— 那兩件事無關。

    走 `save_template()` 的話會撞上草稿驗證，於是「有一個模板失效」就讓整份順序
    存不進去，而使用者根本不是在編輯那個模板。
    """
    store = _store(tmp_path)
    account = store.list_accounts()[0]
    first = _template(store, "早餐")
    second = _template(store, "捷運")
    store.archive_account(account.account_id)

    store.set_template_order([second, first])

    assert [t.template_id for t in store.list_templates()] == [second, first]
