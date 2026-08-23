"""模板：封存要真的可逆，刪除要有界線。

## 這一份守的是什麼

v0.22.0 之前模板頁的「封存」**等於刪除**：`refresh()` 沒有帶 `include_archived`，
而 store／application／controller 三層都沒有 `restore_template`。按下去那一列就永遠
消失了。

代價不只是「少一顆恢復按鈕」—— `delete_account()` 的引用檢查涵蓋
`transaction_templates`，所以**一個看不見的封存模板會讓它引用的帳戶與類別永遠
刪不掉**，而使用者連是什麼東西擋著都不知道。
`test_an_archived_template_no_longer_traps_its_account` 走的就是那一整條路。

**不併進 `test_catalog_pages.py`**：那個檔案講的是 `CatalogPage` 的三個子類，
而模板不是它的子類（按鈕列與資料形狀都不同）。
"""

from typing import Any

from PySide6.QtWidgets import QMessageBox

from tagcor_ledger.ui.main_window import MainWindow


def make_template(window: MainWindow, name: str) -> str:
    """建一個引用預設帳戶與預設項目的模板，回傳它的 id。"""
    controller = window.controller
    template = controller.new_template(
        name=name,
        entry_type="expense",
        account_id="acct_cash",
        destination_account_id=None,
        category_id="cat_food_711",
        amount_minor=85,
        description="",
    )
    assert controller.save_template(template).success
    return str(template.template_id)


def row_of(page: Any, identifier_field: str, identifier: str) -> int:
    ids = [str(item[identifier_field]) for item in page.model.items]
    assert identifier in ids, f"清單裡沒有這一列：{identifier}／現有 {ids}"
    return ids.index(identifier)


def status_column(page: Any, row: int) -> str:
    return str(page.model.index(row, page.model.columnCount() - 1).data())


def always_yes(monkeypatch: Any) -> list[str]:
    """把確認框換成「是」，並把問過的話留下來給斷言用。"""
    asked: list[str] = []

    def confirm(*args: Any, **kwargs: Any) -> QMessageBox.StandardButton:
        asked.append(str(args[2]))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", staticmethod(confirm))
    return asked


def test_archiving_a_template_keeps_it_on_the_page(window) -> None:
    """**封存之後那一列還在**，狀態欄寫「已封存」，再按一次就回來。

    以前它會直接從畫面上消失 —— 而「消失」與「刪除」在使用者眼裡是同一件事，
    所以這一頁的封存從來沒有人真的用過第二次。
    """
    page = window.operation_settings.templates
    template_id = make_template(window, "早餐")
    page.refresh()

    row = row_of(page, "template_id", template_id)
    assert status_column(page, row) == "使用中"

    page.table.selectRow(row)
    page.toggle_selected()

    row = row_of(page, "template_id", template_id)
    assert status_column(page, row) == "已封存", "封存之後那一列不該消失"

    page.table.selectRow(row)
    page.toggle_selected()
    assert status_column(page, row_of(page, "template_id", template_id)) == "使用中"


def test_editing_an_archived_template_does_not_quietly_revive_it(window, monkeypatch) -> None:
    """**編輯不該把封存的東西變回使用中。**

    `new_template()` 把 `status` 寫死成 `"active"`，而 `save_template()` 是 UPSERT
    且會寫 `status = excluded.status` —— `DraftDialog.save()` 少帶一個欄位，
    「改個備註」就會順手把它復活。這條路在封存的列被列出來之前走不到，
    列出來的那一刻它就成立了。
    """
    page = window.operation_settings.templates
    template_id = make_template(window, "早餐")
    page.refresh()
    page.table.selectRow(row_of(page, "template_id", template_id))
    page.toggle_selected()
    assert status_column(page, row_of(page, "template_id", template_id)) == "已封存"

    # 走真正的編輯路徑：開對話框、改備註、按確定。
    item = page.model.items[row_of(page, "template_id", template_id)]
    from tagcor_ledger.ui.widgets.template_dialog import TemplateDialog

    dialog = TemplateDialog(window.controller, current=item, parent=page)
    dialog.description.setText("改過的備註")
    dialog.save()
    assert window.controller.save_template(dialog.saved_value).success
    page.refresh()

    row = row_of(page, "template_id", template_id)
    assert page.model.items[row]["description"] == "改過的備註", "編輯本身要生效"
    assert status_column(page, row) == "已封存", "編輯把封存的模板復活了"


def test_deleting_a_template_says_the_transactions_are_safe(window, monkeypatch) -> None:
    """模板沒有「未使用」這個條件 —— 沒有任何一張表引用得到它。

    確認框必須講出這件事，否則使用者會以為刪模板會連帶影響已經記過的帳。
    """
    page = window.operation_settings.templates
    template_id = make_template(window, "早餐")
    page.refresh()
    asked = always_yes(monkeypatch)

    page.table.selectRow(row_of(page, "template_id", template_id))
    page.delete_selected()

    remaining = [
        str(item["template_id"])
        for item in window.controller.list_templates(include_archived=True)
    ]
    assert template_id not in remaining, "刪除要真的把那一列從資料庫拿掉"
    assert "早餐" in asked[0], "確認框要念出刪的是哪一個"
    assert "不受影響" in asked[0], asked[0]
    assert "封存" in asked[0], "要提供「其實你想要的是封存」這條路"


def test_an_archived_template_no_longer_traps_its_account(window, monkeypatch) -> None:
    """**這條是整次改動存在的理由。**

    `delete_account()` 的引用檢查涵蓋 `transaction_templates`，所以一個封存的模板
    會擋住它引用的帳戶被刪除。改動之前那個模板在畫面上根本不存在，於是使用者面對的
    是一個「這個帳戶已經有交易紀錄」的訊息 —— 而那個帳戶一筆交易也沒有。
    """
    controller = window.controller
    page = window.operation_settings.templates
    assert controller.create_account("零用金", "0").success
    account_id = next(
        str(item["account_id"])
        for item in controller.account_options()
        if item["name"] == "零用金"
    )
    template = controller.new_template(
        name="零用金支出",
        entry_type="expense",
        account_id=account_id,
        destination_account_id=None,
        category_id="cat_food_711",
        amount_minor=None,
        description="",
    )
    assert controller.save_template(template).success

    # 封存模板之後，帳戶仍然刪不掉 —— 那是對的，引用還在。
    assert controller.archive_template(str(template.template_id)).success
    blocked = controller.delete_account(account_id)
    assert not blocked.success
    assert blocked.error_code == "ACCOUNT_IN_USE"

    # 但現在使用者看得見那個模板，也刪得掉它。
    page.refresh()
    row = row_of(page, "template_id", str(template.template_id))
    assert status_column(page, row) == "已封存"
    always_yes(monkeypatch)
    page.table.selectRow(row)
    page.delete_selected()

    assert controller.delete_account(account_id).success, "擋路的東西清掉了，帳戶就該刪得掉"


def test_restoring_a_template_refuses_to_collide_with_an_active_name(window) -> None:
    """schema 有「使用中同名唯一」的部分索引，恢復必須自己先問一次。

    少了那一步，使用者看到的會是 SQLite 的英文原文 —— 而他做的事只是「把封存的
    東西拿回來」。
    """
    controller = window.controller
    template_id = make_template(window, "早餐")
    assert controller.archive_template(template_id).success
    make_template(window, "早餐")  # 同名，但這一個是使用中的

    result = controller.restore_template(template_id)
    assert not result.success
    assert result.error_code == "TEMPLATE_ACTIVE_NAME_CONFLICT"
    assert "模板" in result.message
    assert "TEMPLATE_" not in result.message, f"錯誤碼漏到畫面上了：{result.message}"
