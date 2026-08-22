"""自訂順序的排序視窗：帳戶、類別、項目、模板四頁。

預設帳本只有一個類別（「伙食」）與一個帳戶（「現金」），所以每一條都自己造資料。
每一條都有一個「對話框真的開過」的斷言 —— 少了它，`exec` 被換掉之後測試會在
什麼都沒檢查的情況下變綠。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtWidgets import QDialog

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.domain.models import CategoryTreeFilter
from tagcor_ledger.ui.main_window import MainWindow
from tagcor_ledger.ui.widgets import reorder_dialog as reorder_module


def _window(qtbot: Any, tmp_path: Path) -> MainWindow:
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    return window


def _rows(page: Any, column: int = 0) -> list[str]:
    return [page.model.index(row, column).data() for row in range(page.model.rowCount())]


def _texts(order_list: Any) -> list[str]:
    return [order_list.list.item(row).text() for row in range(order_list.list.count())]


def _open(monkeypatch: Any, page: Any, act: Callable[[Any], bool]) -> list[int]:
    """把 `ReorderDialog.exec` 換掉，直接在對話框上動作。

    `act(dialog)` 回傳 True 代表按「確定」、False 代表「取消」。
    回傳的 list 長度就是「對話框開過幾次」，呼叫端要斷言它。
    """
    opened: list[int] = []

    def fake_exec(self: Any) -> int:
        opened.append(1)
        accepted = act(self)
        code = QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected
        return int(code.value)

    monkeypatch.setattr(reorder_module.ReorderDialog, "exec", fake_exec)
    page.edit_order()
    return opened


def _move_last_to_top(order_list: Any) -> None:
    order_list.list.setCurrentRow(order_list.list.count() - 1)
    for _ in range(order_list.list.count() - 1):
        order_list.up.click()


# --- 類別 ---------------------------------------------------------------------


def test_the_dialog_opens_showing_the_order_that_is_on_screen(
    qtbot: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    """視窗一開就要是目前的順序 —— 不是名稱排、也不是資料庫的插入順序。"""
    window = _window(qtbot, tmp_path)
    for name in ("交通", "居住", "娛樂"):
        assert window.controller.create_category(name).success
    page = window.operation_settings.categories
    page.refresh()
    before = _rows(page)
    assert len(before) >= 4, f"造資料失敗：{before}"
    seen: list[list[str]] = []

    opened = _open(monkeypatch, page, lambda d: (seen.append(_texts(d.parents)), False)[1])

    assert opened, "對話框沒開"
    assert seen[0] == before, f"視窗顯示的不是目前順序：{seen[0]} vs {before}"


def test_moving_the_last_category_to_the_top_changes_the_page(
    qtbot: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    window = _window(qtbot, tmp_path)
    for name in ("交通", "居住", "娛樂"):
        assert window.controller.create_category(name).success
    page = window.operation_settings.categories
    page.refresh()
    before = _rows(page)

    def act(dialog: Any) -> bool:
        _move_last_to_top(dialog.parents)
        return True

    assert _open(monkeypatch, page, act), "對話框沒開"

    after = _rows(page)
    assert after[0] == before[-1], f"{before} -> {after}"
    assert sorted(after) == sorted(before), "移動不該讓任何一列消失或多出來"


def test_cancelling_changes_nothing(
    qtbot: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    """拖到一半按取消要真的什麼都沒發生。"""
    window = _window(qtbot, tmp_path)
    for name in ("交通", "居住"):
        assert window.controller.create_category(name).success
    page = window.operation_settings.categories
    page.refresh()
    before = _rows(page)

    def act(dialog: Any) -> bool:
        _move_last_to_top(dialog.parents)
        assert _texts(dialog.parents) != before, "對話框裡根本沒動到，這條沒在測取消"
        return False

    assert _open(monkeypatch, page, act), "對話框沒開"
    assert _rows(page) == before


def test_archived_entries_are_listed_and_marked(
    qtbot: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    """封存的也要在清單裡，而且看得出來是封存的。

    藏起來的話它的 `sort_order` 會停在舊值，日後恢復就出現在莫名其妙的位置。
    """
    window = _window(qtbot, tmp_path)
    controller = window.controller
    assert controller.create_category("交通").success
    archived = next(
        item["category_id"]
        for item in controller.category_tree(tree_filter=CategoryTreeFilter(level=1))
        if item["name"] == "交通"
    )
    assert controller.archive_category(archived).success
    page = window.operation_settings.categories
    page.refresh()
    seen: list[list[str]] = []

    opened = _open(monkeypatch, page, lambda d: (seen.append(_texts(d.parents)), False)[1])

    assert opened, "對話框沒開"
    assert "交通（已封存）" in seen[0], f"封存的沒出現或沒標註：{seen[0]}"


def test_the_first_row_cannot_move_up_and_the_last_cannot_move_down(
    qtbot: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    window = _window(qtbot, tmp_path)
    assert window.controller.create_category("交通").success
    page = window.operation_settings.categories
    page.refresh()

    def act(dialog: Any) -> bool:
        assert dialog.parents.list.count() >= 2
        dialog.parents.list.setCurrentRow(0)
        assert not dialog.parents.up.isEnabled(), "第一列還能往上移"
        assert dialog.parents.down.isEnabled()
        dialog.parents.list.setCurrentRow(dialog.parents.list.count() - 1)
        assert dialog.parents.up.isEnabled()
        assert not dialog.parents.down.isEnabled(), "最後一列還能往下移"
        return False

    assert _open(monkeypatch, page, act), "對話框沒開"


def test_the_lists_are_tall_enough_that_nothing_is_cut_off(
    qtbot: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    """要拖曳的清單**看不到全部就沒辦法決定拖到哪裡**。

    2026-08-22 第一版沒設高度下限，實機截圖上五個項目就被切掉第五列 —— 純看程式碼
    看不出來。量的是捲軸範圍（geometry），不是「有沒有設定 minimumHeight」。
    """
    window = _window(qtbot, tmp_path)
    controller = window.controller
    assert controller.create_category("交通").success
    transport = next(
        item["category_id"]
        for item in controller.category_options()
        if item["name"] == "交通"
    )
    for name in ("捷運", "公車", "計程車", "高鐵", "客運"):
        assert controller.create_category(name, transport).success
    page = window.operation_settings.items
    page.refresh()

    def act(dialog: Any) -> bool:
        dialog.show()
        parents = _texts(dialog.parents)
        dialog.parents.list.setCurrentRow(parents.index("交通"))
        for label, order_list in (("左欄", dialog.parents), ("右欄", dialog.children)):
            count = order_list.list.count()
            assert 0 < count <= reorder_module.VISIBLE_ROWS, (
                f"{label}的列數 {count} 超過 {reorder_module.VISIBLE_ROWS}，這條測不到東西"
            )
            bar = order_list.list.verticalScrollBar()
            assert bar.maximum() == 0, (
                f"{label} {count} 列就需要捲了（捲軸範圍 0~{bar.maximum()}）—— 有列被切掉"
            )
        dialog.hide()
        return False

    assert _open(monkeypatch, page, act), "對話框沒開"


# --- 項目（兩欄）---------------------------------------------------------------


def _with_transport_items(window: MainWindow, names: tuple[str, ...]) -> str:
    controller = window.controller
    assert controller.create_category("交通").success
    transport = next(
        item["category_id"]
        for item in controller.category_options()
        if item["name"] == "交通"
    )
    for name in names:
        assert controller.create_category(name, transport).success
    return str(transport)


def test_the_items_dialog_has_two_panes_and_orders_within_one_category(
    qtbot: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    """項目的順序是「每個類別各自一組」，所以視窗是兩欄。"""
    window = _window(qtbot, tmp_path)
    _with_transport_items(window, ("捷運", "公車", "計程車"))
    page = window.operation_settings.items
    page.refresh()

    def act(dialog: Any) -> bool:
        assert dialog.children is not None, "項目的排序視窗沒有第二欄"
        parents = _texts(dialog.parents)
        dialog.parents.list.setCurrentRow(parents.index("交通"))
        inside = _texts(dialog.children)
        assert set(inside) == {"捷運", "公車", "計程車"}, f"右欄不是交通的項目：{inside}"
        _move_last_to_top(dialog.children)
        return True

    assert _open(monkeypatch, page, act), "對話框沒開"

    rows = [
        (page.model.index(row, 0).data(), page.model.index(row, 1).data())
        for row in range(page.model.rowCount())
    ]
    transport_items = [name for parent, name in rows if parent == "交通"]
    assert transport_items[0] == "計程車", f"排序沒有生效：{rows}"


def test_switching_categories_keeps_what_you_already_moved(
    qtbot: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    """左欄切走再切回來，右欄要記得剛才的順序 —— 否則使用者以為白拖了。"""
    window = _window(qtbot, tmp_path)
    _with_transport_items(window, ("捷運", "公車"))
    page = window.operation_settings.items
    page.refresh()

    def act(dialog: Any) -> bool:
        parents = _texts(dialog.parents)
        assert len(parents) >= 2, f"至少要兩個類別才切得動：{parents}"
        home = parents.index("交通")
        dialog.parents.list.setCurrentRow(home)
        _move_last_to_top(dialog.children)
        moved = _texts(dialog.children)

        dialog.parents.list.setCurrentRow(0 if home else 1)
        dialog.parents.list.setCurrentRow(home)
        assert _texts(dialog.children) == moved, "切走再切回來，剛才的順序沒了"
        return False

    assert _open(monkeypatch, page, act), "對話框沒開"


def test_the_items_dialog_also_orders_the_categories(
    qtbot: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    """左欄就是「哪一組排前面」，它也要存得下去。"""
    window = _window(qtbot, tmp_path)
    _with_transport_items(window, ("捷運",))
    page = window.operation_settings.items
    page.refresh()
    categories = window.operation_settings.categories
    categories.refresh()
    before = _rows(categories)

    def act(dialog: Any) -> bool:
        _move_last_to_top(dialog.parents)
        return True

    assert _open(monkeypatch, page, act), "對話框沒開"

    categories.refresh()
    assert _rows(categories)[0] == before[-1], "左欄的類別順序沒有存下來"


# --- 下拉選單要跟著 -------------------------------------------------------------


def test_the_custom_order_shows_up_in_the_entry_page_dropdown(
    qtbot: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    """名冊排好了但記帳頁下拉沒跟著，等於沒排。"""
    window = _window(qtbot, tmp_path)
    for name in ("交通", "居住", "娛樂"):
        assert window.controller.create_category(name).success
    page = window.operation_settings.categories
    page.refresh()
    before = _rows(page)

    assert _open(monkeypatch, page, lambda d: (_move_last_to_top(d.parents), True)[1])

    window.entry.reload_options()
    dropdown = [
        window.entry.category.itemText(index)
        for index in range(window.entry.category.count())
    ]
    assert dropdown[0] == before[-1], f"下拉沒有跟著自訂順序走：{dropdown}"


# --- 帳戶與模板 -----------------------------------------------------------------


def test_accounts_can_be_reordered_and_the_dropdown_follows(
    qtbot: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    window = _window(qtbot, tmp_path)
    for name in ("郵局", "悠遊付"):
        assert window.controller.create_account(name, "0").success
    page = window.operation_settings.accounts
    page.refresh()
    before = _rows(page)
    assert len(before) >= 3, f"造資料失敗：{before}"

    assert _open(monkeypatch, page, lambda d: (_move_last_to_top(d.parents), True)[1])

    assert _rows(page)[0] == before[-1]
    window.entry.reload_options()
    assert window.entry.account.itemText(0) == before[-1], "記帳頁的帳戶下拉沒有跟著"


def test_templates_can_be_reordered(
    qtbot: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    window = _window(qtbot, tmp_path)
    controller = window.controller
    account = controller.account_options()[0]["account_id"]
    parent = controller.category_options()[0]["category_id"]
    category = controller.category_options(parent)[0]["category_id"]
    for name in ("早餐", "捷運"):
        template = controller.new_template(
            name=name,
            entry_type="expense",
            account_id=account,
            destination_account_id=None,
            category_id=category,
            amount_minor=None,
            description="",
        )
        assert controller.save_template(template).success

    page = window.operation_settings.templates
    page.refresh()
    before = _rows(page)
    assert len(before) == 2, f"造資料失敗：{before}"

    assert _open(monkeypatch, page, lambda d: (_move_last_to_top(d.parents), True)[1])

    assert _rows(page) == list(reversed(before))
