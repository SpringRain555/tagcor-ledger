"""定存頁：合約清單、期、到期流進待確認，以及編輯合約的欄位可見性。"""



from tagcor_ledger.ui.pages.deposits import DepositContractDialog


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


def test_deposit_contract_flows_into_pending_inbox(window) -> None:
    controller = window.controller

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

    window.operation_settings.deposits.refresh()
    assert window.operation_settings.deposits.contract_model.rowCount() == 1

    # 起存日在過去，所以一按「產生」就會出現到期項目。
    assert controller.generate_due().success
    window.inbox.refresh()
    sources = [
        window.inbox.model.items[row]["source"]
        for row in range(window.inbox.model.rowCount())
    ]
    assert "deposit" in sources


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
        "tagcor_ledger.ui.pages.deposits.ask_form",
        lambda *a, **k: {"name": "郵局定存", "balance": "0"},
    )
    monkeypatch.setattr(
        "tagcor_ledger.ui.pages.deposits.QMessageBox.warning",
        staticmethod(lambda parent, title, text, *a, **k: warnings.append(text)),
    )
    monkeypatch.setattr(
        "tagcor_ledger.ui.pages.deposits.QMessageBox.information",
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
        start_date="2026-01-01",
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
    }
    editing = DepositContractDialog(controller, window, current=contract)
    qtbot.addWidget(editing)
    creating = DepositContractDialog(controller, window)
    qtbot.addWidget(creating)

    for widget, name in (
        (editing.start_date, "起存日"),
        (editing.principal, "本金"),
        (editing.annual_rate, "年利率"),
    ):
        assert editing.form.isRowVisible(widget) is False, (
            f"修改合約時還看得到「{name}」，而那一格的值是建立用的預設值"
        )
    assert editing.term_hint.isVisible() or editing.term_hint.text(), (
        "把欄位收起來就要說去哪裡改，否則使用者只會覺得功能不見了"
    )
    # 陽性對照：新增時那幾格本來就該在，否則上面那三條可能只是抓錯 widget。
    for widget, name in (
        (creating.start_date, "起存日"),
        (creating.principal, "本金"),
        (creating.annual_rate, "年利率"),
    ):
        assert creating.form.isRowVisible(widget) is True, f"新增合約時「{name}」不見了"
