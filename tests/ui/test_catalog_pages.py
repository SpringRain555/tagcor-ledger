"""帳戶／類別／項目三個名冊分頁：篩選、排序入口、新增與改名對話框。

**每個類別都有自己的一列**，不管它有沒有子項目 —— 舊版不是這樣，
於是改名、封存、刪除對類別全部失效卻看起來有作用。
"""

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QDialogButtonBox,
    QPushButton,
    QTabWidget,
)

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.ui.main_window import MainWindow
from tagcor_ledger.ui.widgets.simple_form import SimpleFormDialog, TextField


def test_a_category_with_items_can_be_selected_and_renamed(window, monkeypatch) -> None:
    """**有子項目的類別必須有自己的一列。**

    舊的 `CatalogPage` 只在類別「沒有」子項目時才把它自己加成一列，所以「伙食」永遠
    不會出現 —— 畫面上看到的那個「伙食」是項目那一列的第一欄。於是改名、封存、刪除
    對類別**全部失效**：你選到的一直是項目。

    這裡不能只斷言「畫面上有『伙食』兩個字」—— 那在壞掉的版本裡照樣成立。
    要比對的是**那一列的 category_id**。
    """
    controller = window.controller

    page = window.operation_settings.categories
    page.refresh()
    rows = [page.model.items[index] for index in range(page.model.rowCount())]
    ids = [str(row["category_id"]) for row in rows]
    assert "cat_food" in ids, f"「伙食」有子項目，但列表裡沒有它自己的列：{ids}"

    # 選到它，改名，然後確認改的是類別而不是項目。
    row_index = ids.index("cat_food")
    page.table.selectRow(row_index)
    monkeypatch.setattr(
        "tagcor_ledger.ui.pages.catalog.ask_form",
        lambda *args, **kwargs: {"name": "伙食費"},
    )
    page.rename_selected()

    names = {
        str(item["category_id"]): str(item["name"])
        for item in controller.category_options()
    }
    assert names["cat_food"] == "伙食費"
    assert names.get("cat_food_711") is None  # 項目不在第一層
    children = {
        str(item["category_id"]): str(item["name"])
        for item in controller.category_options("cat_food")
    }
    assert children["cat_food_711"] == "7-11", "改到的是項目，不是類別"

    # 舊交易要跟著顯示新名字。
    controller.submit(
        occurred_at="2026-08-19T10:00:00+08:00",
        entry_type="expense",
        amount="85",
        account_id="acct_cash",
        destination_account_id=None,
        category_id="cat_food_711",
        description="午餐",
    )
    window.transactions.first_page()
    assert window.transactions.model.index(0, 3).data() == "伙食費 / 7-11"


def test_operation_settings_has_five_tabs_in_the_agreed_order(window) -> None:
    """**順序本身就是分組**：前四個是記帳會用到的名冊，最後一個是會自己到期的東西。

    所以這裡連順序一起釘住，不只是「有沒有這五個」。
    定期收支在 v0.23.0 移除（ADR-0011），分頁從六個變五個。
    """

    tabs = window.operation_settings.findChild(QTabWidget, "settingsTabs")
    assert tabs is not None
    assert [tabs.tabText(index) for index in range(tabs.count())] == [
        "帳戶",
        "類別",
        "項目",
        "模板",
        "定存",
    ]
    # 分頁與屬性必須是同一個物件，不然 refresh() 會刷到沒有顯示出來的那一份。
    page = window.operation_settings
    assert [tabs.widget(index) for index in range(tabs.count())] == [
        page.accounts,
        page.categories,
        page.items,
        page.templates,
        page.deposits,
    ]


def test_recurring_income_and_expense_is_gone_from_the_ui(window) -> None:
    """定期收支在 v0.23.0 整個移除了（ADR-0011），畫面上不該再有它的殘跡。

    這一條以前守的是「別把它叫成『週期排程』」（那是實作的名字）。功能本身移除之後
    要守的變成**沒有半個入口留在畫面上** —— 一顆通往不存在功能的按鈕比錯的用詞更糟。
    """

    texts = [
        button.text() for button in window.operation_settings.findChildren(QPushButton)
    ]
    tabs = window.operation_settings.findChild(QTabWidget, "settingsTabs")
    assert tabs is not None
    texts += [tabs.tabText(index) for index in range(tabs.count())]

    offenders = [text for text in texts if "定期收支" in text or "排程" in text]
    assert not offenders, f"畫面上還有定期收支的殘跡：{offenders}"


def test_items_page_filters_by_category(window) -> None:
    """項目一多就找不到自己要的那一個，所以「項目」分頁上方有類別篩選。"""
    controller = window.controller

    transport = controller.create_category("交通")
    assert transport.success
    transport_id = str(transport.details["category_id"])
    assert controller.create_category("電子票證儲值", transport_id).success
    assert controller.create_category("早餐店", "cat_food").success

    page = window.operation_settings.items
    page.refresh()
    assert {page.model.index(row, 1).data() for row in range(page.model.rowCount())} == {
        "7-11",
        "早餐店",
        "電子票證儲值",
    }

    index = page.parent_filter.findData(transport_id)
    assert index > 0, "篩選下拉裡沒有「交通」"
    page.parent_filter.setCurrentIndex(index)
    rows = [
        (page.model.index(row, 0).data(), page.model.index(row, 1).data())
        for row in range(page.model.rowCount())
    ]
    assert rows == [("交通", "電子票證儲值")]

    # 篩選在重新整理之後要保住 —— 新增一個項目不該把畫面跳回「全部」。
    assert controller.create_category("加油", transport_id).success
    page.refresh()
    assert page.parent_filter.currentData() == transport_id
    assert page.model.rowCount() == 2


def test_categories_page_counts_its_items(window) -> None:
    """「項目數」是一起查出來的，不是每個類別再查一次。"""
    assert window.controller.create_category("早餐店", "cat_food").success
    assert window.controller.create_category("交通").success

    page = window.operation_settings.categories
    page.refresh()
    counts = {
        page.model.index(row, 0).data(): page.model.index(row, 1).data()
        for row in range(page.model.rowCount())
    }
    assert counts["伙食"] == "2 項"
    assert counts["交通"] == "0 項"


def test_the_simple_form_disables_ok_until_required_fields_are_filled(qtbot) -> None:
    """必填欄空白時「確定」是停用的。

    **不要讓使用者按下去才知道不行。** 空白名稱送到 store 換來的是
    `..._NAME_REQUIRED` 警告框，而那句話說的是他早就看得到的事。
    """
    dialog = SimpleFormDialog(
        "新增帳戶",
        [TextField("name", "帳戶名稱"), TextField("balance", "期初餘額（TWD）", default="0")],
        None,
    )
    qtbot.addWidget(dialog)
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)

    assert ok.isEnabled() is False, "名稱還空著就可以按確定"
    dialog._widgets["name"].setText("郵局")
    assert ok.isEnabled() is True
    dialog._widgets["name"].setText("   ")
    assert ok.isEnabled() is False, "只打空白也算沒填"

    dialog._widgets["name"].setText("郵局")
    assert dialog.values() == {"name": "郵局", "balance": "0"}


def test_adding_an_item_asks_everything_in_one_dialog(window, monkeypatch) -> None:
    """新增項目**只開一次對話框**，而且類別是用 id 帶的不是用名字反查的。

    舊版是兩個連續的 `QInputDialog`：先選上層類別按 OK，再打名稱按 OK ——
    取消第二個，第一個選的類別就靜靜消失了。
    """
    controller = window.controller
    assert controller.create_category("交通").success
    transport_id = next(
        str(item["category_id"])
        for item in controller.category_options()
        if item["name"] == "交通"
    )

    asked: list[list[Any]] = []

    def fake_ask(parent: Any, title: str, fields: Any) -> dict[str, Any]:
        asked.append(list(fields))
        assert title == "新增項目"
        options = dict(fields[0].options)
        # 下拉帶的是 id，不是顯示文字 —— 這正是舊版用 `labels.index()` 反查的地方。
        return {"parent_id": options["交通"], "name": "捷運"}

    monkeypatch.setattr("tagcor_ledger.ui.pages.catalog.ask_form", fake_ask)
    page = window.operation_settings.items
    page.add_item()

    assert len(asked) == 1, f"問了 {len(asked)} 次，應該只問一次"
    labels = [spec.label for spec in asked[0]]
    assert labels == ["所屬類別", "項目名稱"], labels

    children = {
        str(item["name"]): str(item["category_id"])
        for item in controller.category_options(transport_id)
    }
    assert "捷運" in children, f"項目沒有建在「交通」底下：{children}"


def test_adding_an_account_asks_everything_in_one_dialog(window, monkeypatch) -> None:
    """新增帳戶也是一次問完，而且第一格叫「帳戶名稱」不是「名稱」。"""

    asked: list[list[Any]] = []
    monkeypatch.setattr(
        "tagcor_ledger.ui.pages.catalog.ask_form",
        lambda parent, title, fields: (
            asked.append(list(fields)) or {"name": "郵局", "balance": "100000"}
        ),
    )
    window.operation_settings.accounts.add_item()

    assert len(asked) == 1
    assert [spec.label for spec in asked[0]] == ["帳戶名稱", "期初餘額（TWD）"]
    names = {str(item["name"]) for item in window.controller.account_options()}
    assert "郵局" in names


def test_creating_a_duplicate_category_says_which_name_clashed(
    window,
    qtbot,
    tmp_path: Path,
) -> None:
    """同名衝突要有自己的錯誤碼與說法，不要塌成一句「請確認名稱沒有重複且上層類別有效」。

    以前三種失敗共用 `CATEGORY_CREATE_FAILED`，訊息後面還接著 SQLite 原文
    —— 一句同時指控兩個欄位、又沒說是哪個名字重複的話。
    """
    # 不用 `window` fixture：這一條刻意**不 `show()`**，它驗的是「還沒顯示就先呼叫
    # 建立」的那條路。fixture 一律會 show。
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    controller = window.controller

    duplicate = controller.create_category("伙食")
    assert not duplicate.success
    assert duplicate.error_code == "CATEGORY_ACTIVE_NAME_CONFLICT", duplicate.error_code
    assert "伙食" in duplicate.message
    assert "reason" not in duplicate.details, "SQLite 原文不可以印到畫面上"

    blank = controller.create_category("   ")
    assert blank.error_code == "CATEGORY_NAME_REQUIRED", blank.error_code

    orphan = controller.create_category("早餐", "cat_does_not_exist")
    assert orphan.error_code == "CATEGORY_PARENT_INVALID", orphan.error_code


def _column(page: Any, column: int) -> list[str]:
    return [
        str(page.model.index(row, column).data()) for row in range(page.model.rowCount())
    ]


def test_catalog_pages_filter_by_search_status_and_parent(window) -> None:
    """搜尋、狀態、所屬類別三個條件都要真的縮短清單。

    **項目也要能用類別名搜到** —— 打「交通」就該列出交通底下的每一項，
    不然使用者得先知道項目叫什麼才找得到它。
    """
    controller = window.controller

    transport = controller.create_category("交通")
    assert transport.success
    transport_id = str(transport.details["category_id"])
    assert controller.create_category("捷運", transport_id).success
    assert controller.create_category("加油", transport_id).success
    assert controller.create_category("早餐店", "cat_food").success

    page = window.operation_settings.items
    page.refresh()
    assert set(_column(page, 1)) == {"7-11", "早餐店", "捷運", "加油"}

    # 用項目名搜
    page.filter_bar.search.setText("捷")
    assert _column(page, 1) == ["捷運"]

    # 用類別名搜 —— 交通底下的兩個都要出來
    page.filter_bar.search.setText("交通")
    assert set(_column(page, 1)) == {"捷運", "加油"}

    page.filter_bar.search.clear()
    index = page.parent_filter.findData(transport_id)
    assert index > 0, "篩選下拉裡沒有「交通」"
    page.parent_filter.setCurrentIndex(index)
    assert set(_column(page, 1)) == {"捷運", "加油"}

    # 狀態：封存一個之後，「使用中」看不到它、「已封存」只看得到它
    page.parent_filter.setCurrentIndex(0)
    page.filter_bar.search.clear()
    assert controller.archive_category("cat_food_711").success
    page.refresh()

    page.filter_bar.status.setCurrentIndex(
        page.filter_bar.status.findData("active")
    )
    assert "7-11" not in _column(page, 1)
    page.filter_bar.status.setCurrentIndex(
        page.filter_bar.status.findData("archived")
    )
    assert _column(page, 1) == ["7-11"]
    page.filter_bar.status.setCurrentIndex(page.filter_bar.status.findData("all"))
    assert "7-11" in _column(page, 1)


def test_the_header_is_no_longer_a_sorting_entry_point(window) -> None:
    """點表頭排序在 v0.19.0 拿掉了，排序只有「排序設定」視窗一個入口。

    以前兩種入口並存：點表頭會把使用者在視窗裡設好的多層規格整個換成單層，
    而畫面上沒有任何東西說明剛才設的為什麼不見了。

    `setSortingEnabled` 仍然要是 False —— 那會讓 `QTableView` 在 Python 裡排序，
    是 `AGENTS.md` 明文禁止的事。拿掉表頭排序不代表可以改用那條路。
    """
    for page in (
        window.operation_settings.categories,
        window.operation_settings.items,
        window.operation_settings.accounts,
    ):
        header = page.table.horizontalHeader()
        assert not header.sectionsClickable(), (
            f"{type(page).__name__} 的表頭還可以點 —— 那是第二個排序入口"
        )
        assert not header.isSortIndicatorShown(), (
            f"{type(page).__name__} 還畫著排序箭頭，但點了不會有反應"
        )
        assert page.table.isSortingEnabled() is False, (
            "setSortingEnabled(True) 會讓 QTableView 在 Python 裡排序 —— 規則禁止"
        )


def test_the_parent_dropdown_keeps_every_category_while_searching(window) -> None:
    """搜尋縮短了清單，**「所屬類別」下拉不能跟著只剩搜到的那幾個** —— 否則換不回去。"""
    assert window.controller.create_category("交通").success

    page = window.operation_settings.items
    page.refresh()
    before = [page.parent_filter.itemText(i) for i in range(page.parent_filter.count())]
    assert {"伙食", "交通"} <= set(before), before

    page.filter_bar.search.setText("7-11")
    after = [page.parent_filter.itemText(i) for i in range(page.parent_filter.count())]
    assert after == before, f"搜尋把下拉也縮掉了：{before} -> {after}"
