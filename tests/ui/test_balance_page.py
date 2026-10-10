"""餘額盤點：建立快照，以及未解釋差額會不會跟著交易變動重算。

**盤點不建立交易、不改變餘額。** 它記的是「那一刻實際數出來多少」。
"""

from datetime import datetime

from PySide6.QtCore import QDate, QPoint
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QPushButton,
)

from tagcor_ledger.infrastructure.clock import TAIPEI
from tagcor_ledger.ui.navigation import PageId
from tagcor_ledger.ui.pages.balance_snapshot import BalanceSnapshotEditDialog
from tagcor_ledger.ui.widgets.forms import select_data

BUTTON_ROW = ("新增盤點", "編輯", "刪除")
"""一排，由左到右（使用者 2026-10-05 指定）。「補記交易」在底下「補記與待確認」那一塊；
「匯出盤點 CSV」搬到「系統設定 → 備份與還原」。"""


def _buttons(window) -> dict[str, QPushButton]:
    wanted = {*BUTTON_ROW, "補記交易"}
    found = {
        button.text(): button
        for button in window.balance.findChildren(QPushButton)
        if button.text() in wanted
    }
    assert set(found) == wanted, sorted(found)
    return found


def test_balance_snapshot_page_creates_snapshot(window) -> None:
    page = window.balance

    page.amount.setText("0")
    page.note.setText("初次盤點")
    page.create_snapshot()

    assert page.model.rowCount() == 1
    assert "餘額盤點已儲存" in page.result.text()
    assert "未解釋差額" in page.summary.text()


def _top(widget, page) -> int:
    """`widget` 在 `page` 裡的 y —— 不同父層的 widget 也能比上下。"""
    return widget.mapTo(page, QPoint(0, 0)).y()


def test_the_buttons_sit_in_one_row_and_record_lives_with_the_pending_items(window) -> None:
    """「新增盤點」「編輯」「刪除」同一排；「補記交易」在盤點紀錄底下的「補記與待確認」。
    「重新整理」拿掉了 —— 換帳戶本來就會重查，跨頁改動由主視窗通知。

    量的是版面座標（先切到這一頁，否則 offscreen 上每個 widget 的座標都是 0）。
    """
    window.show_page(PageId.BALANCE)
    QApplication.processEvents()
    page = window.balance
    buttons = _buttons(window)
    texts = [button.text() for button in page.findChildren(QPushButton)]
    assert "重新整理" not in texts
    assert "更新所選盤點" not in texts and "作廢所選盤點" not in texts

    row = [buttons[label] for label in BUTTON_ROW]
    assert len({_top(button, page) for button in row}) == 1, "新增、編輯、刪除要在同一排"
    xs = [button.x() for button in row]
    assert xs == sorted(xs) and len(set(xs)) == len(xs), "左右順序不對"

    record = buttons["補記交易"]
    assert _top(page.table, page) < _top(page.pending_title, page) < _top(record, page), (
        "補記交易要在盤點紀錄底下的「補記與待確認」那一塊"
    )
    assert _top(record, page) < _top(page.inbox, page), "補記交易排在待確認清單前面"


def test_editing_a_snapshot_goes_through_a_dialog_and_keeps_the_time_of_day(
    window, monkeypatch
) -> None:
    """「編輯」開對話框、按儲存才寫入；上方表單不再被點到的那一列蓋掉。

    對話框是 modal 的，把 `exec()` 換成「改金額、按儲存」的假貨，走的仍然是
    `edit_selected()` → `BalanceSnapshotEditDialog.save()` → controller 那條真實路徑。
    時分秒要沿用原值（只改金額不該讓它跳到當天最後一筆）。
    """
    page = window.balance
    page.amount.setText("1000")
    page.note.setText("初次盤點")
    page.create_snapshot()
    original = page.model.items[0]
    original_stamp = str(original["observed_at"])

    # 點列不再倒進表單：正在打的新盤點要留著。
    page.amount.setText("777")
    page.table.selectRow(0)
    assert page.amount.text() == "777", "點到一列把正在打的金額蓋掉了"

    opened: list[BalanceSnapshotEditDialog] = []

    def fake_exec(dialog: BalanceSnapshotEditDialog) -> int:
        opened.append(dialog)
        assert dialog.amount.text() == "1000", "對話框要帶入那一列原本的金額"
        assert dialog.note.text() == "初次盤點"
        dialog.amount.setText("1200")
        dialog.save()
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(BalanceSnapshotEditDialog, "exec", fake_exec)
    page.edit_selected()

    assert len(opened) == 1
    updated = page.model.items[0]
    assert int(updated["actual_balance_minor"]) == 1200
    assert "已更新" in page.result.text(), page.result.text()
    assert "1200" in page.summary.text(), "摘要要照新金額重算"
    before = datetime.fromisoformat(original_stamp).astimezone(TAIPEI)
    after = datetime.fromisoformat(str(updated["observed_at"])).astimezone(TAIPEI)
    assert after.time() == before.time(), "編輯不該改掉原本的時分秒"


def test_a_failed_edit_stays_in_the_dialog(window, monkeypatch) -> None:
    """金額打錯要在視窗裡說，不能關掉視窗 —— 關掉的話剛改的其他欄位就沒了。"""
    page = window.balance
    page.amount.setText("1000")
    page.create_snapshot()
    page.table.selectRow(0)

    def fake_exec(dialog: BalanceSnapshotEditDialog) -> int:
        dialog.amount.setText("這不是金額")
        dialog.save()
        assert dialog.error.text(), "要在對話框裡說哪裡不對"
        assert dialog.saved_result is None
        assert dialog.result() != QDialog.DialogCode.Accepted, "失敗不能關視窗"
        return int(QDialog.DialogCode.Rejected)

    monkeypatch.setattr(BalanceSnapshotEditDialog, "exec", fake_exec)
    page.edit_selected()
    assert int(page.model.items[0]["actual_balance_minor"]) == 1000, "取消之後什麼都不該變"


def test_deleting_a_snapshot_removes_it_for_real(window, answer_confirmations) -> None:
    """「刪除」**真的移除**那一筆（ADR-0015）：清單裡不見了，也沒有「已刪除」篩選可以
    再看到它。確認框要講「找不回來」，而且要說出是哪一天那次盤點。"""
    page = window.balance
    page.amount.setText("1000")
    page.create_snapshot()
    page.table.selectRow(0)
    buttons = _buttons(window)
    assert buttons["編輯"].isEnabled() and buttons["刪除"].isEnabled()

    asked = answer_confirmations(True)
    page.delete_selected()

    assert "已刪除" in page.result.text(), page.result.text()
    assert "找不回來" in asked[0], "確認框要講刪掉就找不回來"
    assert QDate.currentDate().toString("yyyy/MM/dd") in asked[0], "確認框要說是哪一次盤點"
    assert page.model.rowCount() == 0
    assert page.controller.list_balance_snapshots(account_id=page._account_id()) == []
    assert not hasattr(page, "status"), "「列表狀態」篩選拿掉了 —— 盤點不再有已刪除"
    assert not buttons["編輯"].isEnabled(), "清單空了，對所選盤點的按鈕要停用"


def _amount_in_summary(text: str) -> str:
    """從餘額盤點的摘要裡取出「未解釋差額」那一段，用來比對它有沒有變。"""
    marker = "未解釋差額"
    index = text.find(marker)
    assert index >= 0, f"摘要裡沒有未解釋差額：{text!r}"
    return text[index:]


def test_deleting_a_transaction_recalculates_the_balance_gap(
    window, answer_confirmations
) -> None:
    """從交易紀錄刪除一筆帳，餘額盤點的未解釋差額要跟著變。

    未解釋差額 ＝ 盤點金額 － 期間內 posting 加總，所以任何一筆交易的增減都會改變它。
    以前 `TransactionsPage` 只重刷自己那張表、不對外發訊號，於是刪掉一筆錯帳之後
    切到餘額盤點，差額還是舊的 —— 而那個數字正是那一頁存在的唯一理由。

    **那筆帳要記在昨天，不要用預設的今天。** posting 的納入條件是
    `occurred_at <= observed_at`（`stores/balance.py`），而兩個時間戳都由
    `iso_from_date()` 補上牆上時鐘的時分秒、**只到秒**。兩者都用今天的話，
    這筆帳算不算得進去取決於這幾行之間有沒有跨過一次秒界 —— 2026-09-01 實測
    整套跑四次紅一次，就是這個。記昨天就與時鐘無關了。
    """

    window.balance.amount.setText("0")
    window.balance.create_snapshot()
    before = _amount_in_summary(window.balance.summary.text())

    window.entry.select_entry_type("expense")
    window.entry.amount.setText("85")
    window.entry.occurred_at.setDate(QDate.currentDate().addDays(-1))
    window.entry.submit()
    after_entry = _amount_in_summary(window.balance.summary.text())
    assert after_entry != before, "記帳之後差額就該變了"

    page = window.transactions
    page.first_page()
    page.table.selectRow(0)
    selected = page.model.selected_item(page.table)
    assert selected is not None and selected["status"] == "active"

    # 走真正的按鈕路徑（`delete_selected`），不要自己 emit —— 這條測試要驗的正是
    # 「那顆按鈕有沒有通知別人」。
    answer_confirmations(True)
    page.delete_selected()

    assert _amount_in_summary(window.balance.summary.text()) == before, (
        "刪除之後差額應該回到記帳前的值 —— 沒回去就代表餘額盤點沒有被通知"
    )


def test_more_records_load_on_demand(window, monkeypatch) -> None:
    """一次列 `PAGE_SIZE` 筆；滿了才出現「載入更多」，按了多一頁；換帳戶從第一頁開始。

    以前寫死 50 筆、沒有下一頁 —— 一個帳戶每月盤點一次，四年多之後最舊的就看不到了。
    """
    monkeypatch.setattr("tagcor_ledger.ui.pages.balance_snapshot.PAGE_SIZE", 2)
    page = window.balance
    account_id = page._account_id()
    for day in (1, 2, 3):
        assert window.controller.create_balance_snapshot(
            account_id=account_id,
            observed_at=f"2026-06-0{day}T09:00:00+08:00",
            actual_balance="100",
            note="",
        ).success
    page._account_changed()

    assert page.model.rowCount() == 2
    assert page.more_button.isVisibleTo(page)
    page.more_button.click()
    assert page.model.rowCount() == 3
    assert not page.more_button.isVisibleTo(page), "全部列完了，按鈕要消失"

    page._account_changed()
    assert page.model.rowCount() == 2, "換帳戶要從第一頁重新開始"


def test_record_opens_the_entry_page_on_the_account_being_checked(window) -> None:
    """「補記交易」切到記帳頁，**帳戶先選好**這一頁正在看的那一個；記帳頁其他欄位不動。"""
    controller = window.controller
    created = controller.create_account("郵局活儲", "0")
    assert created.success, created.message
    account_id = str(created.details["account_id"])
    window.entry.reload_options()
    window.balance.reload_accounts()
    select_data(window.balance.account, account_id)
    window.entry.description.setText("正在打的備註")
    assert window.entry.account.currentData() != account_id, "前提：記帳頁原本選的是別的帳戶"

    _buttons(window)["補記交易"].click()

    assert window.current_page_widget() is window.entry
    assert window.entry.account.currentData() == account_id
    assert window.entry.description.text() == "正在打的備註", "只選帳戶，不動其他欄位"


def test_confirming_a_pending_item_recalculates_the_gap_on_the_same_page(
    window, make_deposit, monkeypatch
) -> None:
    """待確認併進這一頁的理由（ADR-0016）：**利息沒確認入帳，那個帳戶的盤點就差那麼多**。
    在同一頁按下確認入帳，差額當場重算，側邊欄的數字跟著少一。"""
    from tagcor_ledger.ui.navigation import PENDING_PAGE
    from tagcor_ledger.ui.widgets.sidebar import BADGE_ROLE

    controller = window.controller
    make_deposit(controller)
    page = window.balance
    account_id = str(controller.account_options()[0]["account_id"])
    select_data(page.account, account_id)
    assert controller.create_balance_snapshot(
        account_id=account_id,
        observed_at=f"{QDate.currentDate().toString('yyyy-MM-dd')}T09:00:00+08:00",
        actual_balance="1600",
        note="存摺上多了利息",
    ).success
    window.balance.reload_accounts()
    window.refresh_pending_badge()
    before = _amount_in_summary(page.summary.text())
    badge_before = window.sidebar.item_for(PENDING_PAGE).data(BADGE_ROLE)
    assert badge_before, "先要有一件待確認，否則這條測試什麼都沒驗到"

    monkeypatch.setattr(
        "tagcor_ledger.ui.pages.inbox.ask_form",
        lambda *args, **kwargs: {"occurred_on": "2021-01-15", "amount": "1600"},
    )
    page.inbox.table.selectRow(0)
    page.inbox.confirm_selected()

    assert _amount_in_summary(page.summary.text()) != before, "確認入帳之後差額要當場重算"
    assert window.sidebar.item_for(PENDING_PAGE).data(BADGE_ROLE) in (None, badge_before - 1)
    assert window.transactions.model.rowCount() >= 1, "確認入帳建立了交易，交易紀錄要重載"
