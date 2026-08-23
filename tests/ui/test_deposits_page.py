"""定存頁：合約清單、期、到期流進待確認，以及編輯合約的欄位可見性。

三張對話框在 `ui/widgets/deposit_dialog.py`（v0.24.0 從頁面搬出去），所以
monkeypatch 的目標也在那個模組 —— patch 頁面模組的 `ask_form` 會 `AttributeError`。
"""

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QMessageBox

from tagcor_ledger.ui.widgets.deposit_dialog import DepositContractDialog
from tagcor_ledger.ui.widgets.forms import select_data


def test_deposits_tab_and_pending_deposit_section_exist(window) -> None:
    """定存有自己的分頁，但到期處理一律在「待確認」頁 —— 不要有第二個入帳入口。"""

    deposits = window.operation_settings.deposits
    assert deposits.contract_model.rowCount() == 0
    assert deposits.term_model.rowCount() == 0

    # 待確認頁一開始是空的，而且顯示的是說明而不是一張空表格。
    #
    # **用 `isVisibleTo(頁面)` 而不是 `isVisible()`。** 待確認不是目前那一頁
    # （啟動停在資產總覽），而 `QStackedWidget` 底下非當前的頁一律回報
    # `isVisible() == False` —— 那會讓這條斷言永遠失敗。`isVisibleTo` 問的是
    # 「如果這一頁顯示出來，它看得到嗎」，正是這裡要問的事。
    page = window.inbox
    assert page.model.rowCount() == 0
    assert page.empty.isVisibleTo(page)
    assert not page.table.isVisibleTo(page)
    assert not page.confirm_button.isVisibleTo(page)


def test_deposit_contract_flows_into_pending_inbox(window, make_deposit, monkeypatch) -> None:
    controller = window.controller
    make_deposit(controller, generate=False)

    window.operation_settings.deposits.refresh()
    assert window.operation_settings.deposits.contract_model.rowCount() == 1

    # 起存日在過去，所以一按「產生」就會出現到期項目。
    # **走真正的按鈕**，不是直接呼叫 controller —— 那顆按鈕在 v0.23.0 才補上
    # （README 早就寫著它存在，程式裡卻沒有），走它才測得到有沒有接線。
    page = window.operation_settings.deposits
    told: list[str] = []
    monkeypatch.setattr(
        "tagcor_ledger.ui.pages.deposits.QMessageBox.information",
        lambda parent, title, text: told.append(text),
    )
    page.generate_button.click()
    assert told and "不會自動入帳" in told[0], told

    contracts = [
        str(window.inbox.model.items[row]["contract_name"])
        for row in range(window.inbox.model.rowCount())
    ]
    assert "郵局定存" in contracts, contracts


def test_adding_an_account_that_already_exists_just_selects_it(window, qtbot, monkeypatch) -> None:
    """定存對話框的「新增帳戶…」打到既有名字時，要把它選起來而不是丟錯誤。

    預設值是「郵局定存」，也就是最可能已經開過的名字 —— 第二次按必然撞名。
    舊版丟一個警告框，內容還帶著 `UNIQUE constraint failed: accounts.name`。
    """
    assert window.controller.create_account("郵局定存", "100000").success

    dialog = DepositContractDialog(window.controller, window)
    qtbot.addWidget(dialog)

    warnings: list[str] = []
    infos: list[str] = []
    monkeypatch.setattr(
        "tagcor_ledger.ui.widgets.deposit_dialog.ask_form",
        lambda *a, **k: {"name": "郵局定存", "balance": "0"},
    )
    monkeypatch.setattr(
        "tagcor_ledger.ui.widgets.deposit_dialog.QMessageBox.warning",
        staticmethod(lambda parent, title, text, *a, **k: warnings.append(text)),
    )
    monkeypatch.setattr(
        "tagcor_ledger.ui.widgets.deposit_dialog.QMessageBox.information",
        staticmethod(lambda parent, title, text, *a, **k: infos.append(text)),
    )

    dialog.add_account()

    assert not warnings, f"不該出現錯誤框：{warnings}"
    assert infos and "郵局定存" in infos[0]
    assert dialog.account.currentText() == "郵局定存", "沒有把既有的那個帳戶選起來"


def test_editing_a_deposit_contract_keeps_its_note(window) -> None:
    """修改定存合約**不可以動到備註**。

    對話框沒有備註欄位，以前卻永遠送 `note=""` 進去，而 store 無條件寫
    `note = ?` —— 使用者沒有任何機會發現備註被洗掉了。
    """
    controller = window.controller

    assert controller.create_account("郵局", "0").success
    account_id = next(
        str(item["account_id"])
        for item in controller.account_options()
        if item["name"] == "郵局"
    )
    created = controller.create_deposit_contract(
        account_id=account_id,
        name="郵局定存",
        interest_method="lump_sum",
        maturity_action="none",
        interest_destination_account_id="acct_cash",
        term_months=12,
        opened_on="2026-01-01",
        principal="100000",
        annual_rate_ppm=16000,
        note="分行 001，單號 12345",
    )
    assert created.success, created.message
    contract = controller.list_deposit_contracts()[0]
    assert contract["note"] == "分行 001，單號 12345"

    result = controller.update_deposit_contract(
        str(contract["contract_id"]),
        name="郵局定存（改名）",
        maturity_action="none",
        interest_destination_account_id="acct_cash",
    )
    assert result.success, result.message

    after = controller.list_deposit_contracts()[0]
    assert after["name"] == "郵局定存（改名）"
    assert after["note"] == "分行 001，單號 12345", "改個名字把備註洗掉了"


def test_editing_a_deposit_contract_hides_the_term_only_fields(window, qtbot) -> None:
    """修改合約時不顯示起存日與本金 —— 它們是「期」的欄位，這裡沒有值可以回填。

    以前那幾格是停用但**仍然顯示建立用的預設值**：起存日＝今天、本金＝空白。
    一個灰掉卻寫著今天的「起存日」比沒有那一列更糟，它看起來像事實。
    """
    controller = window.controller

    contract = {
        "contract_id": "dep_x",
        "account_id": "acct_cash",
        "name": "郵局定存",
        "interest_method": "lump_sum",
        "maturity_action": "none",
        "interest_destination_account_id": "acct_cash",
        "term_months": 12,
        "status": "active",
        "note": "",
        "rate_type": "fixed",
        "opened_on": "2023-11-15",
    }
    editing = DepositContractDialog(controller, window, current=contract)
    qtbot.addWidget(editing)
    creating = DepositContractDialog(controller, window)
    qtbot.addWidget(creating)

    for widget, name in (
        (editing.principal, "本金"),
        (editing.annual_rate, "年利率"),
    ):
        assert editing.form.isRowVisible(widget) is False, (
            f"修改合約時還看得到「{name}」，而那一格的值是建立用的預設值"
        )
    # **首次起存日是例外：看得到，但改不了。** 它現在是合約自己的欄位，回填得出來，
    # 而它正是使用者對得回存單的那個數字 —— 藏起來等於把那份對照弄丟。
    assert editing.form.isRowVisible(editing.opened_on) is True
    assert editing.opened_on.isEnabled() is False, "改它會讓期序與實際滾過的輪數對不上"
    assert editing.opened_on.date().toString("yyyy-MM-dd") == "2023-11-15"
    assert editing.term_hint.isVisible() or editing.term_hint.text(), (
        "把欄位收起來就要說去哪裡改，否則使用者只會覺得功能不見了"
    )
    # 陽性對照：新增時那幾格本來就該在，否則上面那三條可能只是抓錯 widget。
    for widget, name in (
        (creating.opened_on, "首次起存日"),
        (creating.principal, "本金"),
        (creating.annual_rate, "年利率"),
    ):
        assert creating.form.isRowVisible(widget) is True, f"新增合約時「{name}」不見了"


# --- 首次起存日與「會建立哪一期」（v0.24.0）-----------------------------------


def test_the_dialog_resolves_the_passbook_date_to_the_current_term(window, qtbot) -> None:
    """**這條守的是使用者照存單抄日期的那一刻。**

    存單印的是最初那一期（112/11/15 存入、113/11/15 到期），而勾了「無限次數自動
    轉期續存」的話郵局早就滾過好幾輪。使用者填的就是紙上那個數字，程式負責說出
    「所以會建立 114/11/15 那一期，而它是第 3 期」。

    第一版是反過來的：欄位問「起存日」＝目前那一期，填錯才警告 —— 於是那個欄位的
    正確值不是使用者手上那張紙印的數字。
    """
    dialog = DepositContractDialog(window.controller, window)
    qtbot.addWidget(dialog)
    select_data(dialog.maturity_action, "renew_principal_only")
    dialog.term_months.setValue(12)
    dialog.opened_on.setDate(QDate(2024, 2, 15))

    assert dialog.resolved_term() == ("2026-02-15", 3)
    assert dialog.values.get("opened_on") is None, "還沒按建立就不該有值"

    text = dialog.resolved_note.text()
    assert dialog.resolved_note.isVisibleTo(dialog)
    assert "第 3 期" in text, f"期序要講出來：{text!r}"
    assert "2026/02/15" in text and "2027/02/15" in text, text
    assert "不會補紀錄" in text, "要說清楚中間那幾期為什麼不存在"

    # 存進去的是**紙上那個數字**，不是算出來的那一期。
    dialog.save()
    assert dialog.values["opened_on"] == "2023-11-15"


def test_full_renewal_is_told_to_use_the_passbook_balance(window, qtbot) -> None:
    """本息續存的本金每一期都含前一期的利息 —— 滾過幾輪之後早就不是存單上那個數字。

    而程式**算不出來**（各期實際利息不在帳本裡），所以只能提醒。
    """
    dialog = DepositContractDialog(window.controller, window)
    qtbot.addWidget(dialog)
    select_data(dialog.maturity_action, "renew_principal_and_interest")
    dialog.term_months.setValue(12)
    dialog.opened_on.setDate(QDate(2024, 2, 15))

    assert "目前存摺上" in dialog.resolved_note.text(), dialog.resolved_note.text()


def test_a_non_renewing_deposit_is_simply_over(window, qtbot) -> None:
    """不自動轉存的定存到期就結束了，**沒有「目前這一期」可以滾過去**。

    替它算一個等於捏造一份不存在的定存，所以期序永遠是 1，而說明講的是「已經結束」。
    """
    dialog = DepositContractDialog(window.controller, window)
    qtbot.addWidget(dialog)
    select_data(dialog.maturity_action, "none")
    dialog.term_months.setValue(12)
    dialog.opened_on.setDate(QDate(2024, 2, 15))

    assert dialog.resolved_term() == ("2023-11-15", 1)
    text = dialog.resolved_note.text()
    assert "已經結束" in text, text
    assert "第 2 期" not in text and "第 3 期" not in text, text


def test_a_fresh_deposit_still_says_which_term_it_will_create(window, qtbot) -> None:
    """**沒有滾期也要說。** 它回答的是「按下建立會發生什麼」，不是只在填錯時才出現。

    期長 24 個月時到期日不是一眼看得出來的，而那正是使用者要對照存單的東西。
    """
    dialog = DepositContractDialog(window.controller, window)
    qtbot.addWidget(dialog)
    select_data(dialog.maturity_action, "renew_principal_only")
    dialog.term_months.setValue(24)
    dialog.opened_on.setDate(QDate.currentDate().addMonths(-3))

    assert dialog.resolved_note.isVisibleTo(dialog)
    text = dialog.resolved_note.text()
    assert "第 1 期" in text, text
    assert "到期了" not in text, f"沒到期就不該講到期：{text!r}"


# --- 結束合約與中途解約（v0.24.0）--------------------------------------------


def test_closing_a_contract_hides_it_until_you_ask_to_see_it(window, make_deposit) -> None:
    """結束之後預設收起來，勾「顯示已結束的合約」才看得到。

    **看不見但還在**是這個專案吃過虧的形狀（v0.22.0 的封存模板擋住帳戶刪除），
    所以那個核取方塊跟按鈕一起加，不是之後再說。
    """
    controller = window.controller
    contract_id = make_deposit(controller, generate=False)
    # 中途解約會把那一期收掉並順手結束合約 —— 這一頁唯一會動到錢的動作。
    term = controller.list_deposit_terms(contract_id)[0]
    assert controller.terminate_deposit_term(
        str(term["term_id"]),
        occurred_on="2021-01-15",
        principal_minor=100_000,
        interest_minor=0,
    ).success

    page = window.operation_settings.deposits
    page.refresh()
    assert page.contract_model.rowCount() == 0, "結束的合約預設不該出現"

    page.show_closed.setChecked(True)
    assert page.contract_model.rowCount() == 1
    assert page.contract_model.items[0]["status"] == "closed"


def test_closing_a_contract_with_a_live_term_says_what_to_do_instead(
    window, make_deposit, monkeypatch
) -> None:
    """擋下來的時候要指出「中途解約」，不能只說不行。"""
    controller = window.controller
    make_deposit(controller)
    page = window.operation_settings.deposits
    page.refresh()
    page.contracts.selectRow(0)

    monkeypatch.setattr(
        "tagcor_ledger.ui.pages.deposits.QMessageBox.question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    warnings: list[str] = []
    monkeypatch.setattr(
        "tagcor_ledger.ui.pages.deposits.QMessageBox.warning",
        staticmethod(lambda parent, title, text, *a, **k: warnings.append(text)),
    )

    page.close_button.click()

    assert warnings, "還有存續中的期卻讓它關掉了"
    assert "中途解約" in warnings[0], warnings[0]
    assert "DEPOSIT_" not in warnings[0], f"錯誤碼漏到畫面上了：{warnings[0]}"
