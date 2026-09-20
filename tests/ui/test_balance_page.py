"""餘額盤點：建立快照，以及未解釋差額會不會跟著交易變動重算。

**盤點不建立交易、不改變餘額。** 它記的是「那一刻實際數出來多少」。
"""

from datetime import datetime

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QMessageBox,
    QPushButton,
)

from tagcor_ledger.infrastructure.clock import TAIPEI
from tagcor_ledger.ui.navigation import PageId
from tagcor_ledger.ui.pages.balance_snapshot import BalanceSnapshotEditDialog

BUTTON_ROWS = (("新增盤點", "補記交易"), ("編輯", "刪除", "匯出盤點 CSV"))
"""兩排按鈕，由上到下、由左到右。第一排產生新東西，第二排對所選盤點動作（加匯出）。"""


def _buttons(window) -> dict[str, QPushButton]:
    wanted = {label for row in BUTTON_ROWS for label in row}
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


def test_the_buttons_sit_in_two_rows_and_there_is_no_refresh_button(window) -> None:
    """第一排「新增盤點」「補記交易」，第二排「編輯」「刪除」「匯出盤點 CSV」；
    「重新整理」拿掉了 —— 換帳戶、換狀態本來就會重查，跨頁改動由主視窗通知。

    量的是版面座標（先切到這一頁，否則 offscreen 上每個 widget 的座標都是 0）。
    """
    window.show_page(PageId.BALANCE)
    QApplication.processEvents()
    buttons = _buttons(window)
    texts = [button.text() for button in window.balance.findChildren(QPushButton)]
    assert "重新整理" not in texts
    assert "更新所選盤點" not in texts and "作廢所選盤點" not in texts

    first_row = [buttons[label] for label in BUTTON_ROWS[0]]
    second_row = [buttons[label] for label in BUTTON_ROWS[1]]
    assert len({button.y() for button in first_row}) == 1, "第一排要在同一列"
    assert len({button.y() for button in second_row}) == 1, "第二排要在同一列"
    assert first_row[0].y() < second_row[0].y(), "新增那一排要在上面"
    for row in (first_row, second_row):
        xs = [button.x() for button in row]
        assert xs == sorted(xs) and len(set(xs)) == len(xs), "同一排的左右順序不對"


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


def test_deleting_a_snapshot_keeps_the_record_under_the_deleted_filter(
    window, monkeypatch
) -> None:
    """「刪除」是 `void`：那一列從「有效」消失、在「已刪除」看得到；選到它時
    「編輯」「刪除」停用（以前是按了沒反應）。"""
    page = window.balance
    page.amount.setText("1000")
    page.create_snapshot()
    page.table.selectRow(0)
    buttons = _buttons(window)
    assert buttons["編輯"].isEnabled() and buttons["刪除"].isEnabled()

    asked: list[str] = []

    def confirm(*args, **kwargs) -> QMessageBox.StandardButton:
        asked.append(str(args[2]))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(
        "tagcor_ledger.ui.pages.balance_snapshot.QMessageBox.question", confirm
    )
    page.delete_selected()

    assert "已刪除" in page.result.text(), page.result.text()
    assert "保留" in asked[0], "確認框要講紀錄會保留"
    assert page.model.rowCount() == 0, "「有效」篩選下那一列該消失"

    page.status.setCurrentIndex(page.status.findData("voided"))
    assert page.model.rowCount() == 1, "「已刪除」篩選下要看得到"
    assert page.model.index(0, 6).data() == "已刪除"
    page.table.selectRow(0)
    assert not buttons["編輯"].isEnabled(), "已刪除的盤點不能再編輯，按鈕要停用"
    assert not buttons["刪除"].isEnabled(), "已刪除的盤點不能再刪一次，按鈕要停用"


def _amount_in_summary(text: str) -> str:
    """從餘額盤點的摘要裡取出「未解釋差額」那一段，用來比對它有沒有變。"""
    marker = "未解釋差額"
    index = text.find(marker)
    assert index >= 0, f"摘要裡沒有未解釋差額：{text!r}"
    return text[index:]


def test_deleting_a_transaction_recalculates_the_balance_gap(window, monkeypatch) -> None:
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
    monkeypatch.setattr(
        "tagcor_ledger.ui.pages.transactions.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    page.delete_selected()

    assert _amount_in_summary(window.balance.summary.text()) == before, (
        "刪除之後差額應該回到記帳前的值 —— 沒回去就代表餘額盤點沒有被通知"
    )
