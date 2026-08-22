"""餘額盤點：建立快照，以及未解釋差額會不會跟著交易變動重算。

**盤點不建立交易、不改變餘額。** 它記的是「那一刻實際數出來多少」。
"""

from pathlib import Path

from PySide6.QtWidgets import (
    QMessageBox,
)

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.ui.main_window import MainWindow


def test_balance_snapshot_page_creates_snapshot_and_setting(qtbot, tmp_path: Path) -> None:
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    page = window.balance

    page.amount.setText("0")
    page.note.setText("初次盤點")
    page.create_snapshot()

    assert page.model.rowCount() == 1
    assert "餘額盤點已儲存" in page.result.text()
    assert "未解釋差額" in page.summary.text()

    window.system_settings.general.balance_snapshot_reminder.setChecked(False)
    window.system_settings.general.save()
    assert not window.controller.get_settings().balance_snapshot_reminder


def _amount_in_summary(text: str) -> str:
    """從餘額盤點的摘要裡取出「未解釋差額」那一段，用來比對它有沒有變。"""
    marker = "未解釋差額"
    index = text.find(marker)
    assert index >= 0, f"摘要裡沒有未解釋差額：{text!r}"
    return text[index:]


def test_voiding_a_transaction_recalculates_the_balance_gap(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    """從交易紀錄作廢一筆帳，餘額盤點的未解釋差額要跟著變。

    未解釋差額 ＝ 盤點金額 － 期間內 posting 加總，所以任何一筆交易的增減都會改變它。
    以前 `TransactionsPage` 只重刷自己那張表、不對外發訊號，於是作廢一筆錯帳之後
    切到餘額盤點，差額還是舊的 —— 而那個數字正是那一頁存在的唯一理由。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()

    window.balance.amount.setText("0")
    window.balance.create_snapshot()
    before = _amount_in_summary(window.balance.summary.text())

    window.entry.select_entry_type("expense")
    window.entry.amount.setText("85")
    window.entry.submit()
    after_entry = _amount_in_summary(window.balance.summary.text())
    assert after_entry != before, "記帳之後差額就該變了"

    page = window.transactions
    page.first_page()
    page.table.selectRow(0)
    selected = page.model.selected_item(page.table)
    assert selected is not None and selected["status"] == "active"

    # 走真正的按鈕路徑（`void_selected`），不要自己 emit —— 這條測試要驗的正是
    # 「那顆按鈕有沒有通知別人」。
    monkeypatch.setattr(
        "tagcor_ledger.ui.pages.transactions.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    page.void_selected()

    assert _amount_in_summary(window.balance.summary.text()) == before, (
        "作廢之後差額應該回到記帳前的值 —— 沒回去就代表餘額盤點沒有被通知"
    )
