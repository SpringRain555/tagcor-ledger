"""待確認：兩種來源合成一張表，以及「確認入帳」之後別頁要跟著動。

跨頁連動集中在 `main_window.py::_ledger_changed()`，那條線少接一段不會有
任何東西報錯 —— 所以這裡有測試盯著。
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QTableView,
)

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.ui.main_window import MainWindow
from tagcor_ledger.ui.navigation import PageId
from tagcor_ledger.ui.widgets.sidebar import BADGE_ROLE


def _inbox_rows(window: MainWindow) -> list[list[str]]:
    model = window.inbox.model
    return [
        [model.index(row, column).data() for column in range(model.columnCount())]
        for row in range(model.rowCount())
    ]


def _make_schedule(controller, name: str, start_date: str) -> None:
    result = controller.save_schedule(
        controller.new_schedule(
            name=name,
            entry_type="expense",
            account_id="acct_cash",
            destination_account_id=None,
            category_id="cat_food_711",
            amount_minor=1200000,
            description="",
            frequency="monthly",
            interval_count=1,
            start_date=start_date,
            end_date=None,
        )
    )
    assert result.success, result.message


def _make_deposit(controller) -> None:
    account_id = str(controller.account_options()[0]["account_id"])
    result = controller.create_deposit_contract(
        account_id=account_id,
        name="郵局定存",
        interest_method="lump_sum",
        maturity_action="renew_principal_only",
        interest_destination_account_id=account_id,
        term_months=12,
        start_date="2020-01-15",
        principal="100000",
        annual_rate_ppm=16_000,
    )
    assert result.success, result.message


def test_the_inbox_is_one_table_with_a_source_column(qtbot, tmp_path: Path) -> None:
    """定期收支與定存**在同一張表**，靠「來源」欄分辨。

    以前是上下兩張表加六顆按鈕：「我還有幾件事要處理」要自己把兩個數字加起來，
    按按鈕之前還得先想清楚哪三顆是對上面那張表的。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    controller = window.controller

    _make_schedule(controller, "房租", "2026-06-01")
    _make_deposit(controller)
    assert controller.generate_due().success
    window.inbox.refresh()

    model = window.inbox.model
    assert [
        model.headerData(column, Qt.Orientation.Horizontal)
        for column in range(model.columnCount())
    ] == ["到期日", "來源", "名稱", "類型", "金額（TWD）", "狀態說明"]

    sources = {row[1] for row in _inbox_rows(window)}
    assert sources == {"定期", "定存"}, sources
    # 一張表，不是兩張。
    assert len(window.inbox.findChildren(QTableView)) == 1

    # 依到期日排序，而且是顯示用的斜線格式，不是資料庫的 ISO 字串。
    dates = [row[0] for row in _inbox_rows(window)]
    assert dates == sorted(dates)
    assert all("/" in date_text for date_text in dates), dates


def test_the_inbox_explains_itself_when_it_is_empty(qtbot, tmp_path: Path) -> None:
    """**這一段文字就是「我忘記這頁是做什麼的」的正解。**

    空表格加三顆停用的按鈕說不出任何事情。沒有項目時整組操作收起來，換成說明。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    window.show_page(PageId.INBOX)

    page = window.inbox
    assert page.model.rowCount() == 0
    assert page.empty.isVisibleTo(page)
    assert not page.table.isVisibleTo(page)
    for button in (page.confirm_button, page.skip_button, page.confirm_all_button):
        assert not button.isVisibleTo(page)

    text = page.empty.text()
    assert "定期收支" in text
    assert "定存" in text
    assert "確認之後才會變成交易" in text
    assert "操作設定 → 定期收支" in text

    # 有東西之後就換回表格。
    _make_schedule(window.controller, "房租", "2026-06-01")
    assert window.controller.generate_due().success
    page.refresh()
    assert page.table.isVisibleTo(page)
    assert not page.empty.isVisibleTo(page)
    assert page.confirm_button.isVisibleTo(page)


def test_confirming_dispatches_by_source(qtbot, tmp_path: Path, monkeypatch) -> None:
    """「確認入帳」對定期收支開修改對話框，對定存問實際金額。

    兩種來源在同一張表裡，所以分派錯了不會有任何錯誤訊息 —— 只會開錯一個視窗。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    controller = window.controller
    _make_deposit(controller)
    assert controller.generate_due().success
    window.inbox.refresh()

    rows = [
        index
        for index in range(window.inbox.model.rowCount())
        if window.inbox.model.items[index]["source"] == "deposit"
    ]
    assert rows, "沒有定存項目，這條測試等於沒作用"
    window.inbox.table.selectRow(rows[0])

    asked: list[str] = []

    def fake_get_text(*args: object, **kwargs: object) -> tuple[str, bool]:
        asked.append(str(args[2]) if len(args) > 2 else "")
        return ("842", True)

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", fake_get_text)
    before = controller.inbox_count()
    window.inbox.confirm_selected()

    assert asked, "定存項目沒有問實際金額"
    assert "存摺" in asked[0], asked[0]
    assert controller.inbox_count() == before - 1


def test_confirm_all_leaves_deposits_alone_and_says_so(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    """**「全部確認」不碰定存。**

    定存的權威金額在存摺上，建議值只是試算 —— 批次套用試算值等於替使用者決定了一個
    他沒看過的數字。但也不能默默跳過，訊息要講清楚還剩幾件。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    controller = window.controller
    _make_schedule(controller, "房租", "2026-06-01")
    _make_deposit(controller)
    assert controller.generate_due().success
    window.inbox.refresh()

    shown: list[str] = []
    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.information",
        lambda *args, **kwargs: shown.append(str(args[2])),
    )
    window.inbox.confirm_all()

    assert shown and "定存" in shown[0], shown
    remaining = {item["source"] for item in controller.list_inbox()}
    assert remaining == {"deposit"}, f"定存不該被批次確認掉：{remaining}"


def test_generate_button_only_shows_up_when_there_is_more_to_generate(
    qtbot, tmp_path: Path
) -> None:
    """「繼續產生」平常不出現。

    啟動時本來就會產生一次，所以平常按它什麼都不會發生 —— **一顆按了沒反應的按鈕
    比沒有按鈕更糟**。只有真的還有漏期時才浮出一行提示與一顆行內按鈕。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    page = window.inbox

    assert not window.controller.generation_has_more
    assert not page.more_button.isVisibleTo(page)
    assert not page.more_hint.isVisibleTo(page)

    window.controller.generation_has_more = True
    page.refresh()
    assert page.more_button.isVisibleTo(page)
    assert "漏期" in page.more_hint.text()


def test_confirming_an_inbox_item_refreshes_the_transaction_list(
    qtbot, tmp_path: Path
) -> None:
    """待確認按下確認入帳會建立**真的交易**，所以交易紀錄與側邊欄數字都要跟著動。

    以前 `inbox.changed` 只接到側邊欄徽章，於是確認完房租切到交易紀錄，那一筆不在那裡。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    controller = window.controller

    schedule = controller.new_schedule(
        name="房租",
        entry_type="expense",
        account_id="acct_cash",
        destination_account_id=None,
        category_id="cat_food_711",
        amount_minor=12_000,
        description="每月房租",
        frequency="yearly",
        interval_count=1,
        start_date="2026-01-01",
        end_date="2026-01-01",
    )
    assert controller.save_schedule(schedule).success
    assert controller.generate_due().success
    window.inbox.refresh()

    occurrence = controller.list_pending()[0]
    badge_before = window.sidebar.item_for(PageId.INBOX).data(BADGE_ROLE)
    assert badge_before, "先要有一件待確認，否則這條測試什麼都沒驗到"
    assert window.transactions.model.rowCount() == 0

    assert controller.confirm_occurrence(str(occurrence["occurrence_id"])).success
    window.inbox.refresh()

    assert window.transactions.model.rowCount() == 1, (
        "確認入帳會建立交易，交易紀錄必須重載 —— 沒有就代表 inbox 只通知了徽章"
    )
    assert not window.sidebar.item_for(PageId.INBOX).data(BADGE_ROLE)
