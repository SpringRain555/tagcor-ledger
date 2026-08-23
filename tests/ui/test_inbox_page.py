"""待確認：定存到期的草稿，以及「確認入帳」之後別頁要跟著動。

跨頁連動集中在 `main_window.py::_ledger_changed()`，那條線少接一段不會有
任何東西報錯 —— 所以這裡有測試盯著。

**v0.23.0 之前這一頁有兩個來源**，所以有一組測試在守「兩種形狀合成一張表、
確認與略過依來源分派、全部確認不碰定存」。定期收支移除之後
（[ADR-0011](../../docs/decisions/ADR-0011-drop-recurring-schedules.md)）
那些分派都不存在了，測試跟著走 —— 但**「確認入帳要建立真的交易並連動別頁」
那一條留著，只是改走定存**：它守的是跨頁連動，與來源是誰無關。
"""

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableView

from tagcor_ledger.ui.main_window import MainWindow
from tagcor_ledger.ui.navigation import PageId
from tagcor_ledger.ui.widgets.sidebar import BADGE_ROLE


def _inbox_rows(window: MainWindow) -> list[list[str]]:
    model = window.inbox.model
    return [
        [model.index(row, column).data() for column in range(model.columnCount())]
        for row in range(model.rowCount())
    ]


def _make_deposit(controller: Any, *, name: str = "郵局定存") -> None:
    account_id = str(controller.account_options()[0]["account_id"])
    result = controller.create_deposit_contract(
        account_id=account_id,
        name=name,
        interest_method="lump_sum",
        maturity_action="renew_principal_only",
        interest_destination_account_id=account_id,
        term_months=12,
        start_date="2020-01-15",
        principal="100000",
        annual_rate_ppm=16_000,
    )
    assert result.success, result.message
    # **合約建好不會自己產生事件** —— 那是啟動任務或定存頁那顆按鈕做的。
    assert controller.generate_deposit_events().success


def test_the_inbox_is_one_table_of_deposit_events(window) -> None:
    """一張表，四欄，依到期日排序。

    **沒有「來源」欄，也沒有「狀態說明」欄。** 兩者在只剩一個來源之後都變成
    「每一列印同一個字」—— 依 `formatting/rows.py` 自己的規則那就是雜訊。
    「金額以存摺為準」那句話改成表格上方講一次。
    """
    controller = window.controller
    _make_deposit(controller, name="郵局定存")
    _make_deposit(controller, name="郵局二年期")
    window.inbox.refresh()

    model = window.inbox.model
    assert [
        model.headerData(column, Qt.Orientation.Horizontal)
        for column in range(model.columnCount())
    ] == ["到期日", "定存合約", "類型", "建議金額（TWD）"]

    assert model.rowCount() >= 2, "測試資料沒有產生待確認項目，這條測試等於沒作用"
    # 一張表，不是兩張。
    assert len(window.inbox.findChildren(QTableView)) == 1

    # 依到期日排序，而且是顯示用的斜線格式，不是資料庫的 ISO 字串。
    dates = [row[0] for row in _inbox_rows(window)]
    assert dates == sorted(dates)
    assert all("/" in date_text for date_text in dates), dates

    assert window.inbox.hint.isVisibleTo(window.inbox)
    assert "存摺" in window.inbox.hint.text()


def test_the_inbox_explains_itself_when_it_is_empty(window) -> None:
    """**這一段文字就是「我忘記這頁是做什麼的」的正解。**

    空表格加兩顆停用的按鈕說不出任何事情。沒有項目時整組操作收起來，換成說明。
    """
    window.show_page(PageId.INBOX)

    page = window.inbox
    assert page.model.rowCount() == 0
    assert page.empty.isVisibleTo(page)
    assert not page.table.isVisibleTo(page)
    assert not page.hint.isVisibleTo(page)
    for button in (page.confirm_button, page.skip_button):
        assert not button.isVisibleTo(page)

    text = page.empty.text()
    assert "定存" in text
    assert "確認之後才會變成交易" in text
    assert "操作設定 → 定存" in text
    assert "定期收支" not in text, "定期收支已經移除了，空狀態不該再提它"

    # 有東西之後就換回表格。
    _make_deposit(window.controller)
    page.refresh()
    assert page.table.isVisibleTo(page)
    assert not page.empty.isVisibleTo(page)
    assert page.confirm_button.isVisibleTo(page)
    assert page.hint.isVisibleTo(page)


def test_confirming_an_inbox_item_refreshes_the_transaction_list(window, monkeypatch) -> None:
    """待確認按下確認入帳會建立**真的交易**，所以交易紀錄與側邊欄數字都要跟著動。

    以前 `inbox.changed` 只接到側邊欄徽章，於是確認完切到交易紀錄，那一筆不在那裡。
    **這一條在 v0.23.0 之前走的是定期收支**，改走定存 —— 它守的是跨頁連動，
    與草稿是誰產生的無關。
    """
    controller = window.controller
    _make_deposit(controller)
    window.inbox.refresh()

    badge_before = window.sidebar.item_for(PageId.INBOX).data(BADGE_ROLE)
    assert badge_before, "先要有一件待確認，否則這條測試什麼都沒驗到"
    assert window.transactions.model.rowCount() == 0

    monkeypatch.setattr(
        "tagcor_ledger.ui.pages.inbox.QInputDialog.getText",
        lambda *args, **kwargs: ("1600", True),
    )
    window.inbox.table.selectRow(0)
    window.inbox.confirm_selected()

    assert window.transactions.model.rowCount() >= 1, (
        "確認入帳會建立交易，交易紀錄必須重載 —— 沒有就代表 inbox 只通知了徽章"
    )


def test_a_bad_amount_when_confirming_says_so_in_chinese(window, monkeypatch) -> None:
    """確認時打錯金額：跳中文警告，**而且不入帳**。

    這是「使用者照存摺輸入實際利息」的入口 —— 打錯字被安靜吞掉的話，
    帳上會多一筆金額不對的利息收入。
    """
    controller = window.controller
    _make_deposit(controller)
    window.inbox.refresh()
    window.inbox.table.selectRow(0)
    before = window.inbox.model.rowCount()

    monkeypatch.setattr(
        "tagcor_ledger.ui.pages.inbox.QInputDialog.getText",
        lambda *args, **kwargs: ("一千元", True),
    )
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "tagcor_ledger.ui.pages.inbox.QMessageBox.warning",
        lambda parent, title, text: warnings.append((title, text)),
    )

    window.inbox.confirm_selected()

    assert warnings, "金額打錯卻什麼都沒說"
    title, text = warnings[0]
    assert title == "金額無效"
    assert "數字" in text, f"訊息要講人話：{text!r}"
    assert "MoneyError" not in text and "AMOUNT_" not in text, "不准印英文碼"

    window.inbox.refresh()
    assert window.inbox.model.rowCount() == before, "打錯金額不該把項目入帳掉"


def test_cancelling_the_amount_prompt_leaves_the_item_alone(window, monkeypatch) -> None:
    """在金額對話框按取消 = 什麼都不做。"""
    controller = window.controller
    _make_deposit(controller)
    window.inbox.refresh()
    window.inbox.table.selectRow(0)
    before = window.inbox.model.rowCount()

    monkeypatch.setattr(
        "tagcor_ledger.ui.pages.inbox.QInputDialog.getText",
        lambda *args, **kwargs: ("", False),
    )
    window.inbox.confirm_selected()

    window.inbox.refresh()
    assert window.inbox.model.rowCount() == before


def test_skipping_removes_the_item_without_creating_a_transaction(window) -> None:
    """略過 = 「我看過，這一期不記」。**不產生交易。**"""
    controller = window.controller
    _make_deposit(controller)
    window.inbox.refresh()
    before = window.inbox.model.rowCount()
    assert before >= 1

    window.inbox.table.selectRow(0)
    window.inbox.skip_selected()

    assert window.inbox.model.rowCount() == before - 1
    assert window.transactions.model.rowCount() == 0
