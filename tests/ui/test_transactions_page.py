"""交易紀錄頁：選取連動、金額的正負號與紅綠、從一筆交易建立模板。

**顏色由 model 的 `ForegroundRole` 決定，QSS 不得設 `color`** ——
那會把紅綠壓成同一個白，而這裡就是抓那件事的地方。
"""


import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QMessageBox,
    QPushButton,
)

from tagcor_ledger.ui import colors
from tagcor_ledger.ui.navigation import PageId
from tagcor_ledger.ui.widgets.template_dialog import TemplateDialog

ACTION_LABELS = ["編輯", "刪除", "建立模板"]
"""三顆動作按鈕，**由左到右**。順序是使用者指定的，下面有一條量 x 座標守著。"""


def _action_buttons(window) -> dict[str, QPushButton]:
    found = {
        button.text(): button
        for button in window.transactions.findChildren(QPushButton)
        if button.text() in ACTION_LABELS
    }
    assert sorted(found) == sorted(ACTION_LABELS), sorted(found)
    return found


def _record_lunch(window) -> None:
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


def test_action_buttons_are_disabled_until_a_row_is_selected(window) -> None:
    """沒選取就按按鈕，以前是**完全沒有反應** —— 沒有訊息、沒有變化，像當掉。"""

    buttons = _action_buttons(window)
    assert all(not button.isEnabled() for button in buttons.values())

    _record_lunch(window)
    window.transactions.table.selectRow(0)
    assert all(button.isEnabled() for button in buttons.values())


def test_action_buttons_sit_left_to_right_in_the_agreed_order(window) -> None:
    """編輯、刪除、建立模板 —— 量的是版面上的 x 座標，不是 `addWidget` 的順序。"""
    window.show_page(PageId.TRANSACTIONS)
    QApplication.processEvents()
    buttons = _action_buttons(window)
    by_position = sorted(buttons.values(), key=lambda button: button.x())
    assert [button.text() for button in by_position] == ACTION_LABELS
    assert len({button.x() for button in by_position}) == 3, "有兩顆疊在同一個 x，版面沒跑"


def test_delete_names_the_transaction_and_then_removes_it_for_real(
    window, monkeypatch
) -> None:
    """「刪除」**真的刪掉**（v13 起，ADR-0017）。

    確認框念出是哪一筆、講找不回來；答「否」什麼都不動（陽性對照），答「是」那一列就不見了 ——
    而且沒有「已刪除」篩選可以把它找回來：那個篩選與「狀態」欄一起拿掉了。
    """
    _record_lunch(window)
    page = window.transactions
    answers = [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]
    asked: list[str] = []

    def answer(*args, **kwargs) -> QMessageBox.StandardButton:
        asked.append(str(args[2]))
        return answers[len(asked) - 1]

    monkeypatch.setattr(QMessageBox, "question", staticmethod(answer))
    page.table.selectRow(0)
    page.delete_selected()
    assert page.model.rowCount() == 1, "答「否」不該刪"

    page.table.selectRow(0)
    page.delete_selected()

    assert page.model.rowCount() == 0
    assert window.controller.list_transactions().details["transactions"] == []
    assert "午餐" in asked[0] and "2026/08/19" in asked[0], f"要念出是哪一筆：{asked[0]}"
    assert "找不回來" in asked[0], asked[0]
    assert "定存" not in asked[0], "手打的交易不該講定存那一句"
    headers = [
        page.model.headerData(column, Qt.Orientation.Horizontal)
        for column in range(page.model.columnCount())
    ]
    assert "狀態" not in headers, "沒有已刪除的交易了，狀態欄每一列都會是同一個值"
    assert not hasattr(page, "status"), "「狀態」篩選拿掉了"


def test_deleting_a_deposit_posting_says_the_draft_will_not_come_back(
    window, make_deposit, monkeypatch
) -> None:
    """定存確認入帳產生的那一筆，刪掉之後那一筆待確認**不會回來**（它已經是「已確認」）——
    使用者會以為刪掉就能重新確認一次，所以確認框要先講。"""
    controller = window.controller
    make_deposit(controller)
    event = controller.list_inbox()[0]
    assert controller.confirm_deposit_event(
        str(event["event_id"]), actual_amount_minor=1_600, occurred_on=str(event["due_date"])
    ).success
    page = window.transactions
    page.first_page()
    row = next(
        index
        for index, item in enumerate(page.model.items)
        if item.get("source") == "deposit"
    )
    asked: list[str] = []

    def answer(*args, **kwargs) -> QMessageBox.StandardButton:
        asked.append(str(args[2]))
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(answer))
    page.table.selectRow(row)
    page.delete_selected()

    assert "定存確認入帳產生的" in asked[0], asked[0]
    assert "不會再回來" in asked[0], asked[0]


@pytest.mark.geometry
def test_transaction_amounts_are_signed_right_aligned_and_coloured(window) -> None:
    """金額欄是整個帳本最常被掃的一欄。

    QSS 的 `color` / `selection-color` 會蓋掉 model 的 `ForegroundRole`，
    所以這裡連**選取狀態**都要驗 —— 2026-08-19 截圖比對時就是這樣發現紅綠沒出現的。
    """
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


def test_amount_colours_survive_the_stylesheet(window, qtbot) -> None:
    """**這條要看畫出來的像素，不能只看 model。**

    QSS 的 `QTableView::item { color: ... }` 會蓋掉 model 的 `ForegroundRole`：
    model 照樣回報紅色，畫面上卻是白的。只驗 model 的測試在那個 bug 下**照樣通過** ——
    2026-08-19 實際注入驗證過。所以這裡把儲存格畫出來取像素。
    """
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


def test_creating_a_template_from_a_transaction_keeps_the_original_item(
    window, monkeypatch
) -> None:
    """「建立模板」跳到操作設定的模板分頁、開一張**已經填好**的新增視窗，而且帶的是
    **原本那個項目**，不是該類別的第一個。

    交易的 dict 裡 `category_id` 是類別（第一層）、`subcategory_id` 才是項目，而
    `TemplateDialog._select_category()` 要的是項目 id。餵父層進去比對必然落空，
    項目會被靜靜換成第一個 —— 以前「複製到記帳」就是這樣帶錯的。

    視窗是 modal 的，所以把 `exec()` 換成一段「檢查欄位、填名稱、按儲存」的假貨；
    走的仍然是 `TemplatesPage.edit()` → `save_template()` 那條真實路徑。
    """
    controller = window.controller
    created = controller.create_category("早餐", "cat_food")
    assert created.success, created.message
    breakfast_id = str(created.details["category_id"])

    # 「7-11」是種子資料、`sort_order` 10；新建的項目是 100，所以第一個子項目是 7-11。
    # 這條測試要有意義，原本記的就必須**不是**第一個。
    children = controller.category_options("cat_food")
    assert [str(item["category_id"]) for item in children][0] != breakfast_id
    controller.submit(
        occurred_at="2026-08-19T10:00:00+08:00",
        entry_type="expense",
        amount="85",
        account_id="acct_cash",
        destination_account_id=None,
        category_id=breakfast_id,
        description="早餐店",
    )

    opened: list[TemplateDialog] = []

    def fake_exec(dialog: TemplateDialog) -> int:
        opened.append(dialog)
        assert dialog.current is None, "從交易建的是新模板，不是編輯既有的"
        assert dialog.name.text() == "", "名稱要留白讓使用者取"
        assert str(dialog.flow.currentData()) == "expense"
        assert str(dialog.account.currentData()) == "acct_cash"
        assert str(dialog.category.currentData()) == "cat_food"
        assert str(dialog.detail.currentData()) == breakfast_id, (
            "項目被換掉了 —— 帶進來的是父類別 id 而不是項目 id"
        )
        assert dialog.amount.text() == "85"
        assert dialog.description.text() == "早餐店"
        assert not dialog.buttons.button(dialog.buttons.StandardButton.Save).isEnabled(), (
            "名稱還空著，「儲存」就不該按得下去"
        )
        dialog.name.setText("早餐")
        dialog.save()
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(TemplateDialog, "exec", fake_exec)

    page = window.transactions
    page.first_page()
    page.table.selectRow(0)
    page.create_template_from_selected()

    assert len(opened) == 1, "視窗要開，而且只開一次"
    settings = window.operation_settings
    assert window.current_page_widget() is settings
    assert settings.tabs.currentWidget() is settings.templates, "要停在模板分頁"
    saved = [row for row in controller.list_templates() if row["name"] == "早餐"]
    assert len(saved) == 1, "使用者按了儲存，模板要真的存進去"
    assert str(saved[0]["category_id"]) == breakfast_id
    assert saved[0]["amount_minor"] == 85
