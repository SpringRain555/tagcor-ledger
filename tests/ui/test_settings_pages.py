"""系統設定：資料路徑、備份清單與刪除、重製確認框。"""

import re
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMessageBox,
)

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.ui.main_window import MainWindow


def test_reset_confirmation_names_what_will_be_lost(window) -> None:
    """不可逆的操作要講得出「會失去什麼」，不能只說「這會清空資料」。"""
    window.controller.submit(
        occurred_at="2026-08-19T10:00:00+08:00",
        entry_type="expense",
        amount="85",
        account_id="acct_cash",
        destination_account_id=None,
        category_id="cat_food_711",
        description="午餐",
    )

    summary = window.system_settings.reset.loss_summary()
    assert "交易 1 筆" in summary
    assert "帳戶 1 筆" in summary


def test_the_paths_page_shows_the_data_root(window, qtbot, tmp_path: Path) -> None:
    """「資料路徑」要看得到資料根目錄。

    `PATH_OUTSIDE_DATA_ROOT` 這個錯誤講的正是這個值，而它是從「記帳資料路徑」的
    上一層推出來的 —— 畫面上沒有它，使用者就只能猜訊息在說哪個資料夾。
    """
    # 不用 `window` fixture：這一段要先拿到 `paths` 才建視窗（訊息裡要比對資料夾路徑），
    # 而 fixture 只回視窗。這個檔案其餘幾處是刻意不 `show()`。
    paths = resolve_app_paths(tmp_path / "ledger-data")
    window = MainWindow(paths)
    qtbot.addWidget(window)
    window.show()
    page = window.system_settings.paths

    assert page.data_root.isReadOnly(), "資料根目錄是推導值，不該讓人編輯"
    assert page.data_root.text() == str(paths.data_dir)
    # 它必須真的是那兩個路徑的上層，否則顯示了也沒有意義。
    assert str(paths.ledger_dir).startswith(page.data_root.text())
    assert str(paths.backup_dir).startswith(page.data_root.text())


def test_backup_list_never_shows_a_raw_error_code(window, qtbot, tmp_path: Path) -> None:
    """備份清單那一欄以前印的是 `無效：BACKUP_CHECKSUM_MISMATCH`。

    這一頁是使用者遇到麻煩時才會來的地方 —— 在這裡丟一串英文碼給他，等於在他最
    需要看懂的時候換一種語言。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    page = window.system_settings.maintenance

    backup_dir = window.controller.create_backup()
    (backup_dir / "ledger.sqlite3").write_bytes(b"tampered")
    page.refresh()

    assert page.list.count() == 1
    text = page.list.item(0).text()
    assert "不可用（內容被改過）" in text, text
    assert "BACKUP_" not in text, text
    # **壞掉的備份也要有時間。** `validate_backup()` 一發現問題就回傳，`created_at`
    # 讀不到，那一列開頭因此是空的 —— 而使用者正是在「這幾份都壞了，該刪哪一份」
    # 的時候需要那個時間。讀不到清單檔就退回資料夾名字裡的時間戳。
    assert not text.startswith("｜"), f"時間欄是空的：{text}"
    stamp = text.split("｜")[0]
    assert re.fullmatch(r"\d{4}/\d{2}/\d{2} \d{2}:\d{2}", stamp), stamp

    # **完整路徑不進那一列** —— 上百字元的絕對路徑會把清單撐出一條橫向捲軸，
    # 而每一列前面那一大段還完全相同。放 tooltip，滑過去就看得到。
    item = page.list.item(0)
    assert str(backup_dir) not in text, f"完整路徑跑進列裡了：{text}"
    assert text.endswith(backup_dir.name), text
    assert item.toolTip() == str(backup_dir), item.toolTip()

    # 按「驗證」要給完整說法，不是短標籤也不是英文碼。
    page.list.setCurrentRow(0)
    page.validate_selected()
    assert "雜湊對不起來" in page.result.text(), page.result.text()
    assert "BACKUP_" not in page.result.text()


def test_deleting_a_broken_backup_from_the_page(window, qtbot, tmp_path: Path, monkeypatch) -> None:
    """走**真正的按鈕路徑**：選一列 → 按刪除 → 確認 → 清單少一列、資料夾真的不見。

    不呼叫 `controller.delete_backup()` 了事 —— 那樣測不到選取綁定、確認框，
    也測不到刪完有沒有重新整理。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    page = window.system_settings.maintenance

    keep = window.controller.create_backup()
    drop = window.controller.create_backup()
    (drop / "ledger.sqlite3").write_bytes(b"tampered")
    page.refresh()
    assert page.list.count() == 2

    asked: list[str] = []

    def confirm(*args: Any, **kwargs: Any) -> QMessageBox.StandardButton:
        asked.append(str(args[2]))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", staticmethod(confirm))

    row = next(
        index
        for index in range(page.list.count())
        if page.list.item(index).data(Qt.ItemDataRole.UserRole) == str(drop)
    )
    page.list.setCurrentRow(row)
    page.delete_button.click()

    assert not drop.exists(), "壞掉的備份要刪得掉 —— 那是這顆按鈕的主要用途"
    assert keep.is_dir(), "不該動到別的備份"
    assert page.list.count() == 1
    assert page.list.item(0).data(Qt.ItemDataRole.UserRole) == str(keep)
    # 確認框要念出這一份是什麼，還要說刪完還剩幾份可用的。
    assert str(drop) in asked[0], asked[0]
    assert "還有 1 份可用的備份" in asked[0], asked[0]


def test_the_last_usable_backup_says_so_before_it_goes(
    window,
    qtbot,
    tmp_path: Path,
    monkeypatch,
) -> None:
    """**不擋、只講。** 刪掉最後一份可用的備份是使用者的決定，但他要知道。"""
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    page = window.system_settings.maintenance

    only = window.controller.create_backup()
    page.refresh()

    asked: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(
            lambda *args, **kwargs: (
                asked.append(str(args[2])) or QMessageBox.StandardButton.No
            )
        ),
    )

    page.list.setCurrentRow(0)
    page.delete_button.click()

    assert "這之後就沒有任何可用的備份了" in asked[0], asked[0]
    assert only.is_dir(), "按了「否」就不該刪"
    assert page.list.count() == 1


def test_backup_buttons_are_disabled_until_a_backup_is_selected(
    window,
    qtbot,
    tmp_path: Path,
) -> None:
    """沒選取就停用 —— 對「刪除」這種不可逆的操作尤其不能按了沒反應。"""
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    page = window.system_settings.maintenance

    buttons = (page.validate_button, page.restore_button, page.delete_button)
    assert not any(button.isEnabled() for button in buttons), "沒有備份時就不該能按"

    window.controller.create_backup()
    page.refresh()
    assert not any(button.isEnabled() for button in buttons), "重整之後選取被清掉了"

    page.list.setCurrentRow(0)
    assert all(button.isEnabled() for button in buttons)
