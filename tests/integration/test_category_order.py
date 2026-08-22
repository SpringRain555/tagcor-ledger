"""自訂順序：`sort_order` 從 schema v1 就在，這是第一次真的有人寫它。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.domain.models import CategoryTreeFilter
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


def _store(tmp_path: Path) -> LedgerStore:
    return LedgerStore(resolve_app_paths(tmp_path / "ledger-data"))


def _names(store: LedgerStore, *, level: int, parent_id: str | None = None) -> list[str]:
    """畫面上會看到的順序（`default` = 自訂順序）。"""
    nodes = store.list_category_tree(
        tree_filter=CategoryTreeFilter(level=level, parent_id=parent_id)
    )
    return [node.category.name for node in nodes]


def _make(store: LedgerStore, names: list[str], parent_id: str | None = None) -> dict[str, str]:
    return {
        name: store.create_category(name=name, parent_id=parent_id).category_id
        for name in names
    }


def test_new_categories_all_tie_on_sort_order_so_they_fall_back_to_name(
    tmp_path: Path,
) -> None:
    """**這是修好之前的行為，記在這裡當基準。**

    `create_category()` 把 `sort_order` 寫死成 100，所以整組平手，實際順序是靠
    `ORDER BY sort_order, name COLLATE NOCASE` 後面那個名稱 tiebreaker 撐著。
    """
    store = _store(tmp_path)
    _make(store, ["丙類", "甲類", "乙類"])
    assert _names(store, level=1)[-3:] == sorted(["丙類", "甲類", "乙類"], key=str.casefold)


def test_moving_a_category_up_changes_what_the_list_shows(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ids = _make(store, ["甲類", "乙類", "丙類"])
    before = _names(store, level=1)

    store.reorder_category(ids["丙類"], anchor_id=ids["甲類"], place="before")

    after = _names(store, level=1)
    assert after.index("丙類") < after.index("甲類")
    assert after != before
    assert sorted(after) == sorted(before), "移動不該讓任何一列消失或多出來"


def test_moving_down_puts_it_after_the_anchor(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ids = _make(store, ["甲類", "乙類", "丙類"])
    store.reorder_category(ids["甲類"], anchor_id=ids["丙類"], place="after")
    after = _names(store, level=1)
    assert after.index("甲類") > after.index("丙類")


def test_the_order_survives_a_reload(tmp_path: Path) -> None:
    """順序要真的寫進資料庫，不是只活在這一個 store 物件裡。"""
    store = _store(tmp_path)
    ids = _make(store, ["甲類", "乙類", "丙類"])
    store.reorder_category(ids["丙類"], anchor_id=ids["甲類"], place="before")
    expected = _names(store, level=1)

    assert _names(_store(tmp_path), level=1) == expected


def test_items_are_ordered_inside_their_own_category(tmp_path: Path) -> None:
    store = _store(tmp_path)
    parents = _make(store, ["甲類", "乙類"])
    items = _make(store, ["早", "中", "晚"], parent_id=parents["甲類"])
    other = _make(store, ["外一", "外二"], parent_id=parents["乙類"])

    store.reorder_category(items["晚"], anchor_id=items["早"], place="before")

    inside = _names(store, level=2, parent_id=parents["甲類"])
    # 斷言的是**相對位置**，不是絕對名次。原始順序來自名稱 tiebreaker，而中文照
    # 碼位排（中 < 早 < 晚），把「晚」移到「早」前面之後第一列仍然是「中」。
    assert inside.index("晚") < inside.index("早")
    assert sorted(inside) == sorted(["早", "中", "晚"])
    # 別的類別底下完全沒被動到
    assert _names(store, level=2, parent_id=parents["乙類"]) == sorted(
        other, key=str.casefold
    )


def test_an_item_cannot_be_moved_next_to_another_category_s_item(tmp_path: Path) -> None:
    """跨類別移動要擋下來 —— 那是「換類別」，不是「調順序」。"""
    store = _store(tmp_path)
    parents = _make(store, ["甲類", "乙類"])
    mine = _make(store, ["我的"], parent_id=parents["甲類"])
    theirs = _make(store, ["別人的"], parent_id=parents["乙類"])

    with pytest.raises(ValueError, match="CATEGORY_REORDER_DIFFERENT_PARENT"):
        store.reorder_category(mine["我的"], anchor_id=theirs["別人的"], place="before")


def test_a_category_cannot_be_moved_next_to_an_item(tmp_path: Path) -> None:
    """第一層與第二層不是同一組，即使項目的 parent 就是那個類別。"""
    store = _store(tmp_path)
    parents = _make(store, ["甲類"])
    items = _make(store, ["早"], parent_id=parents["甲類"])

    with pytest.raises(ValueError, match="CATEGORY_REORDER_DIFFERENT_PARENT"):
        store.reorder_category(parents["甲類"], anchor_id=items["早"], place="before")


def test_an_unknown_place_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ids = _make(store, ["甲類", "乙類"])
    with pytest.raises(ValueError, match="CATEGORY_REORDER_PLACE_INVALID"):
        store.reorder_category(ids["甲類"], anchor_id=ids["乙類"], place="上面一點")


def test_a_missing_category_says_not_found(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ids = _make(store, ["甲類"])
    with pytest.raises(Exception, match="CATEGORY_NOT_FOUND"):
        store.reorder_category("cat_nope", anchor_id=ids["甲類"], place="before")
    with pytest.raises(Exception, match="CATEGORY_NOT_FOUND"):
        store.reorder_category(ids["甲類"], anchor_id="cat_nope", place="before")


def test_the_custom_order_also_drives_the_entry_page_dropdowns(tmp_path: Path) -> None:
    """`list_categories()` 是記帳頁下拉的來源，它也要照自訂順序。

    一份順序，兩個地方看到的一樣 —— 名冊排好了但下拉沒跟著，等於沒排。
    """
    store = _store(tmp_path)
    ids = _make(store, ["甲類", "乙類", "丙類"])
    store.reorder_category(ids["丙類"], anchor_id=ids["甲類"], place="before")

    dropdown = [category.name for category in store.list_categories()]
    tree = _names(store, level=1)
    assert dropdown == tree
