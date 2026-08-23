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
    before = [row.template.template_id for row in store.list_templates()]
    assert len(before) == 3

    store.set_template_order(list(reversed(before)))

    assert [r.template.template_id for r in store.list_templates()] == list(reversed(before))
    assert [r.template.template_id for r in _store(tmp_path).list_templates()] == list(
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

    assert [r.template.template_id for r in store.list_templates()] == [second, first]


# --- 多層排序（v0.19.0）--------------------------------------------------------


def test_a_two_level_spec_sorts_by_the_second_field_inside_ties(tmp_path: Path) -> None:
    """第二層要在第一層平手的時候真的有作用 —— 否則多層等於單層。"""
    from tagcor_ledger.domain.models import SortLevel

    store = _store(tmp_path)
    parents = _make(store, ["甲類", "乙類"])
    # 兩個類別底下各兩個項目，刻意讓「狀態」全部一樣、名稱交錯
    _make(store, ["丙", "甲"], parent_id=parents["甲類"])
    _make(store, ["丁", "乙"], parent_id=parents["乙類"])
    # 讓甲類排在乙類前面。**整組都要送** —— 預設帳本本來就有一個「伙食」，
    # 只送自己造的那兩個會撞上 `REORDER_LIST_STALE`（守門有效，是測試寫錯）。
    everyone = _ids(store, level=1)
    others = [i for i in everyone if i not in (parents["甲類"], parents["乙類"])]
    store.set_category_order(
        [parents["甲類"], parents["乙類"], *others], parent_id=None, level=1
    )

    nodes = store.list_category_tree(
        tree_filter=CategoryTreeFilter(
            level=2,
            sort=(SortLevel(field="parent_custom"), SortLevel(field="name")),
        )
    )
    pairs = [(node.parent_name, node.category.name) for node in nodes]

    # 斷言的是**性質**，不是硬寫的名次：中文照碼位排（丙 < 甲、丁 < 乙），
    # 而且預設帳本本來就有一個「伙食／7-11」。寫死順序只會測到我對排序規則的誤解。
    groups = [parent for parent, _ in pairs]
    assert groups.index("甲類") < groups.index("乙類"), f"第一層沒生效：{pairs}"
    assert groups == sorted(groups, key=lambda g: groups.index(g)), (
        f"同一個類別的項目沒有連在一起：{pairs}"
    )
    for parent in ("甲類", "乙類"):
        inside = [name for group, name in pairs if group == parent]
        assert inside == sorted(inside), f"{parent} 底下第二層沒有照名稱排：{inside}"
        assert len(inside) == 2, inside


def test_descending_actually_reverses(tmp_path: Path) -> None:
    from tagcor_ledger.domain.models import SortLevel

    store = _store(tmp_path)
    _make(store, ["甲類", "乙類", "丙類"])
    up = _names(store, level=1)  # 預設 = 自訂順序（目前全部平手，等於名稱序）
    nodes = store.list_category_tree(
        tree_filter=CategoryTreeFilter(
            level=1, sort=(SortLevel(field="name", descending=True),)
        )
    )
    assert [node.category.name for node in nodes] == list(reversed(sorted(up)))


def test_an_unknown_field_is_skipped_and_the_rest_still_applies(tmp_path: Path) -> None:
    """認不出來的**只跳過那一層**，不是整份丟掉，也不是拼進 SQL。"""
    from tagcor_ledger.domain.models import SortLevel

    store = _store(tmp_path)
    _make(store, ["甲類", "乙類", "丙類"])
    nodes = store.list_category_tree(
        tree_filter=CategoryTreeFilter(
            level=1,
            sort=(
                SortLevel(field="沒有這個欄位"),
                SortLevel(field="name", descending=True),
            ),
        )
    )
    names = [node.category.name for node in nodes]
    assert names == list(reversed(sorted(names))), f"合法的那一層沒有生效：{names}"


def test_the_same_field_twice_does_not_break_the_query(tmp_path: Path) -> None:
    """重複的欄位不能讓查詢壞掉。

    **這一條只證明「SQL 仍然合法」，不證明去重有做。** 去重是字串層級的規則
    （`name ASC, name DESC` 的結果本來就等於 `name ASC`，查詢分不出來），
    所以那件事由 `tests/unit/test_order_by.py` 守。
    """
    from tagcor_ledger.domain.models import SortLevel

    store = _store(tmp_path)
    _make(store, ["甲類", "乙類"])
    nodes = store.list_category_tree(
        tree_filter=CategoryTreeFilter(
            level=1,
            sort=(SortLevel(field="name"), SortLevel(field="name", descending=True)),
        )
    )
    names = [node.category.name for node in nodes]
    assert names == sorted(names), f"第一層應該贏：{names}"


def test_an_all_unknown_spec_falls_back_to_the_default_order(tmp_path: Path) -> None:
    """**先排一個跟名稱序不同的自訂順序**，否則這條測不到東西。

    第一版沒排：全部平手時「退回預設」與「只剩 tiebreaker」都落在名稱序，
    拿掉退回那段程式測試照樣綠（陽性對照抓到的）。
    """
    from tagcor_ledger.domain.models import SortLevel

    store = _store(tmp_path)
    _make(store, ["甲類", "乙類", "丙類"])
    reversed_ids = list(reversed(_ids(store, level=1)))
    store.set_category_order(reversed_ids, parent_id=None, level=1)
    default = _names(store, level=1)
    assert default != sorted(default), "自訂順序沒排開，這條又測不到東西了"

    nodes = store.list_category_tree(
        tree_filter=CategoryTreeFilter(level=1, sort=(SortLevel(field="亂打的"),))
    )
    assert [node.category.name for node in nodes] == default


def test_accounts_and_templates_take_a_spec_too(tmp_path: Path) -> None:
    from tagcor_ledger.domain.models import SortLevel

    store = _store(tmp_path)
    for name in ("郵局", "悠遊付", "信用卡"):
        store.create_account(name=name)
    by_name = [
        a.name
        for a in store.list_accounts(sort=(SortLevel(field="name", descending=True),))
    ]
    assert by_name == list(reversed(sorted(by_name))), by_name

    for name in ("早餐", "捷運", "房租"):
        _template(store, name)
    templates = [
        r.template.name
        for r in store.list_templates(sort=(SortLevel(field="name", descending=True),))
    ]
    assert templates == list(reversed(sorted(templates))), templates


def test_a_tie_falls_through_to_the_stored_order_not_to_chance(tmp_path: Path) -> None:
    """第一層全部平手時，後面接的 tiebreaker 要真的決定順序。

    **不要用「查兩次結果一樣」來測 tiebreaker** —— SQLite 對同一個查詢同一份資料
    本來就會給同一個順序，那樣寫拿掉 tiebreaker 也不會紅（陽性對照抓到的）。
    這裡改成斷言那個順序**是什麼**：tiebreaker 是名稱，所以整組平手時就是名稱序。
    """
    from tagcor_ledger.domain.models import SortLevel

    store = _store(tmp_path)
    _make(store, ["甲類", "乙類", "丙類"])
    # 先把自訂順序排成跟名稱序相反，確認接下來看到的名稱序不是 sort_order 造成的
    store.set_category_order(
        list(reversed(_ids(store, level=1))), parent_id=None, level=1
    )
    assert _names(store, level=1) != sorted(_names(store, level=1))

    nodes = store.list_category_tree(
        tree_filter=CategoryTreeFilter(level=1, sort=(SortLevel(field="status"),))
    )
    names = [node.category.name for node in nodes]
    assert names == sorted(names), f"整組平手時沒有落到名稱 tiebreaker：{names}"
