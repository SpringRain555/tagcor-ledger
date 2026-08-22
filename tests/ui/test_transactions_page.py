"""交易紀錄頁：選取連動、金額的正負號與紅綠、複製到記帳。

**顏色由 model 的 `ForegroundRole` 決定，QSS 不得設 `color`** ——
那會把紅綠壓成同一個白，而這裡就是抓那件事的地方。
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QPushButton,
)

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.ui import colors
from tagcor_ledger.ui.main_window import MainWindow


def test_action_buttons_are_disabled_until_a_row_is_selected(qtbot, tmp_path: Path) -> None:
    """沒選取就按按鈕，以前是**完全沒有反應** —— 沒有訊息、沒有變化，像當掉。"""
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()

    table = window.transactions.table
    buttons = [
        button
        for button in window.transactions.findChildren(QPushButton)
        if button.text() in {"編輯／替換", "複製到記帳", "作廢"}
    ]
    assert len(buttons) == 3
    assert all(not button.isEnabled() for button in buttons)

    window.controller.submit(
        occurred_at="2026-08-19T10:00:00+08:00",
        entry_type="expense",
        amount="85",
        account_id="acct_cash",
        destination_account_id=None,
        category_id="cat_food_711",
        description="午餐",
    )
    window.transactions.first_page()
    table.selectRow(0)
    assert all(button.isEnabled() for button in buttons)


def test_transaction_amounts_are_signed_right_aligned_and_coloured(qtbot, tmp_path: Path) -> None:
    """金額欄是整個帳本最常被掃的一欄。

    QSS 的 `color` / `selection-color` 會蓋掉 model 的 `ForegroundRole`，
    所以這裡連**選取狀態**都要驗 —— 2026-08-19 截圖比對時就是這樣發現紅綠沒出現的。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    controller = window.controller

    for entry_type, amount in (("expense", "1200"), ("income", "36000")):
        controller.submit(
            occurred_at="2026-08-19T10:00:00+08:00",
            entry_type=entry_type,
            amount=amount,
            account_id="acct_cash",
            destination_account_id=None,
            category_id="cat_food_711",
            description="",
        )
    window.transactions.first_page()
    model = window.transactions.model
    assert model.amount_column == 4

    shown = {
        model.index(row, 4).data(Qt.ItemDataRole.DisplayRole) for row in range(model.rowCount())
    }
    assert shown == {"+36,000", "-1,200"}, shown

    for row in range(model.rowCount()):
        index = model.index(row, 4)
        alignment = index.data(Qt.ItemDataRole.TextAlignmentRole)
        assert alignment & Qt.AlignmentFlag.AlignRight
        colour = index.data(Qt.ItemDataRole.ForegroundRole).name().upper()
        expected = colors.INCOME if "+" in index.data() else colors.EXPENSE
        assert colour == expected.upper()

    # 選取之後顏色必須還在。
    window.transactions.table.selectRow(0)
    still = model.index(0, 4).data(Qt.ItemDataRole.ForegroundRole).name().upper()
    assert still in {colors.INCOME.upper(), colors.EXPENSE.upper()}


def _distance(first: str, second: str) -> int:
    left = QColor(first)
    right = QColor(second)
    return (
        abs(left.red() - right.red())
        + abs(left.green() - right.green())
        + abs(left.blue() - right.blue())
    )


def _rendered_text_colour(table, row: int, column: int) -> str:
    """把某一格畫出來，取「離背景最遠」的那個像素當作文字顏色。

    不能直接比對色碼：文字有反鋸齒，邊緣像素是文字色與背景色的混合。
    離背景最遠的那一顆才是真正的筆色。
    """
    rect = table.visualRect(table.model().index(row, column))
    image = table.grab(rect).toImage()
    background = image.pixelColor(0, 0).name()
    furthest = background
    for y in range(image.height()):
        for x in range(image.width()):
            candidate = image.pixelColor(x, y).name()
            if _distance(candidate, background) > _distance(furthest, background):
                furthest = candidate
    return furthest.upper()


def test_amount_colours_survive_the_stylesheet(qtbot, tmp_path: Path) -> None:
    """**這條要看畫出來的像素，不能只看 model。**

    QSS 的 `QTableView::item { color: ... }` 會蓋掉 model 的 `ForegroundRole`：
    model 照樣回報紅色，畫面上卻是白的。只驗 model 的測試在那個 bug 下**照樣通過** ——
    2026-08-19 實際注入驗證過。所以這裡把儲存格畫出來取像素。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    controller = window.controller
    for entry_type, amount in (("expense", "1200"), ("income", "36000")):
        controller.submit(
            occurred_at="2026-08-19T10:00:00+08:00",
            entry_type=entry_type,
            amount=amount,
            account_id="acct_cash",
            destination_account_id=None,
            category_id="cat_food_711",
            description="",
        )
    window.transactions.first_page()
    table = window.transactions.table
    table.resizeColumnsToContents()
    qtbot.waitExposed(window)

    for row in range(window.transactions.model.rowCount()):
        shown = window.transactions.model.index(row, 4).data()
        expected = colors.INCOME if shown.startswith("+") else colors.EXPENSE
        painted = _rendered_text_colour(table, row, 4)
        assert _distance(painted, expected) < _distance(painted, colors.TEXT), (
            f"{shown} 畫出來是 {painted}，比較接近一般文字色而不是 {expected} —— "
            "多半是 QSS 又設了 QTableView::item 的 color"
        )


def test_duplicating_a_transaction_keeps_the_original_item(qtbot, tmp_path: Path) -> None:
    """「複製到記帳」要帶回**原本那個項目**，不是該類別的第一個。

    交易紀錄送出的 dict 裡 `category_id` 是類別（第一層）、`subcategory_id` 才是項目，
    而記帳頁的 `_select_category()` 要的是項目 id。以前餵的是父層，比對必然落空，
    結果類別對了、項目卻被靜靜換成第一個 —— 而 README 明寫會帶入「類別/項目」。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    controller = window.controller

    created = controller.create_category("早餐", "cat_food")
    assert created.success, created.message
    breakfast_id = str(created.details["category_id"])
    window.entry.reload_options()

    # 「7-11」是種子資料、`sort_order` 10；新建的項目是 100，所以第一個子項目是 7-11。
    # 這條測試要有意義，原本選的就必須**不是**第一個。
    children = controller.category_options("cat_food")
    assert [str(item["category_id"]) for item in children][0] != breakfast_id

    window.entry.select_entry_type("expense")
    window.entry._select_category(breakfast_id)
    window.entry.amount.setText("85")
    window.entry.submit()

    # **表單要先離開「早餐」，否則這條測試會假性通過。** `clear_form()` 不動下拉，
    # 所以存完之後項目還停在早餐；不先切走的話，就算 `apply_draft` 什麼都沒選對，
    # 畫面上看起來也是對的。切到同一個類別底下的另一個項目，才驗得到「有沒有選回來」。
    window.entry._select_category(str(children[0]["category_id"]))
    assert str(window.entry.detail.currentData()) != breakfast_id

    page = window.transactions
    page.first_page()
    page.table.selectRow(0)
    page.duplicate_selected()

    assert window.pages.currentWidget() is window.entry
    assert str(window.entry.detail.currentData()) == breakfast_id, (
        "項目被換掉了 —— 複製到記帳送的是父類別 id 而不是項目 id"
    )
    assert str(window.entry.category.currentData()) == "cat_food"
