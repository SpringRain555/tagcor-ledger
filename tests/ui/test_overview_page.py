"""資產總覽：總資產怎麼算、什麼時候重算、沒話說的區塊要收起來。

**這一頁是「切過去就重算」，不接跨頁連動的訊號** —— 理由在 `pages/overview.py`。
"""



from tagcor_ledger.ui.navigation import PageId
from tagcor_ledger.ui.widgets.sidebar import BADGE_ROLE


def test_overview_total_is_the_sum_of_active_accounts(window) -> None:
    """總資產 = 各帳戶餘額相加，而且**封存的不算進去、但要講出來**。

    封存的意思是不再出現在選單，不是錢消失了 —— 默默把它漏掉，使用者拿這個數字去對
    存摺就會對不起來，而且找不到差在哪。
    """
    controller = window.controller

    assert controller.create_account("郵局活儲", "1000").success
    assert controller.create_account("撲滿", "250").success
    window.show_page(PageId.OVERVIEW)

    page = window.overview
    # 列的順序歸 `list_accounts` 管（sort_order 再 name），這一頁只負責顯示，
    # 所以比對名稱對餘額的對應，不比對順序。
    rows = {
        page.model.index(row, 0).data(): page.model.index(row, 1).data()
        for row in range(page.model.rowCount())
    }
    assert page.total.text() == "1,250"
    assert rows == {"現金": "0", "郵局活儲": "1,000", "撲滿": "250"}
    assert not page.archived_note.isVisible()

    # 封存有餘額的帳戶：總資產要掉下來，而且畫面要交代那筆錢去哪了。
    archived = next(
        item
        for item in controller.account_options()
        if item["name"] == "郵局活儲"
    )
    assert controller.archive_account(str(archived["account_id"])).success
    window.show_page(PageId.ENTRY)
    window.show_page(PageId.OVERVIEW)

    assert page.total.text() == "250"
    assert page.archived_note.isVisible()
    assert "郵局活儲" in page.archived_note.text()
    assert "1,000" in page.archived_note.text()


def test_overview_recomputes_when_you_come_back_to_it(window) -> None:
    """在別頁改了資料，切回總覽必須是新的數字。

    這條守的是「切過去就重算」那個機制。改成在 `main_window` 的每個 `_..._changed`
    各記一筆的話，總有一天會漏掉一項，而漏掉的症狀是總資產停在舊數字 ——
    看起來像算錯帳，不像忘記重新整理。
    """

    window.show_page(PageId.OVERVIEW)
    assert window.overview.total.text() == "0"

    window.show_page(PageId.ENTRY)
    window.entry.amount.setText("85")
    window.entry.submit()

    window.show_page(PageId.OVERVIEW)
    assert window.overview.total.text() == "-85"


def test_the_inbox_number_is_the_same_everywhere(window, make_deposit) -> None:
    """側邊欄的數字與總覽的數字走同一個來源。

    兩邊各自算就會出現「側邊欄說 2、總覽說 3」，使用者沒有辦法知道哪一個才對。
    v0.23.0 之前這條還要守「定存也算在內」—— 定期收支移除之後只剩一個來源了。
    """
    controller = window.controller

    make_deposit(controller)
    window.refresh_pending_badge()
    window.show_page(PageId.OVERVIEW)

    count = controller.inbox_count()
    assert count >= 1, "測試資料沒有產生待確認項目，這條測試等於沒作用"
    assert count == len(controller.list_deposit_pending())
    assert window.sidebar.item_for(PageId.INBOX).data(BADGE_ROLE) == count
    assert f"{count} 筆" in window.overview.inbox_note.text()

    # 定存區塊要出現，而且說得出哪一份合約、什麼時候到期。
    assert window.overview.deposit_note.isVisible()
    assert "郵局定存" in window.overview.deposit_note.text()
    assert "2021/01/15" in window.overview.deposit_note.text()


def test_overview_hides_what_it_has_nothing_to_say_about(window) -> None:
    """空的區塊要整段消失。**留一個沒有內容的標題看起來像壞掉或還沒載入。**"""
    window.show_page(PageId.OVERVIEW)

    page = window.overview
    assert not page.deposit_caption.isVisible()
    assert not page.deposit_note.isVisible()
    assert not page.archived_note.isVisible()
    assert not page.negative_note.isVisible()
    assert not page.gap_note.isVisible()
    assert page.inbox_note.text() == "沒有待確認項目。"
    assert not page.inbox_button.isVisible()
    # 全新的帳本只有一個餘額 0 的「現金」—— 一片都畫不出來，圓環整塊收起來。
    # 一個空的圓框跟一個沒有內容的標題是同一種壞法。
    assert not page.chart.isVisible()


def test_the_share_ring_and_its_legend_agree_with_the_table(window) -> None:
    """圓環的圖例與帳戶表講的是同一份資料，只是排法不同。

    表格照使用者的自訂順序，圓環照金額由大到小 —— 兩種讀法各有用處，所以並排。
    要守的是**兩邊的數字一致**：圖例上的金額必須就是表上的那一個。
    """
    controller = window.controller
    assert controller.create_account("郵局活儲", "1000").success
    assert controller.create_account("撲滿", "250").success
    window.show_page(PageId.OVERVIEW)

    page = window.overview
    assert page.chart.isVisible()

    # 餘額 0 的「現金」不進圖例 —— 一行「0.0%」是空話。
    legend = [
        (name.text(), amount.text(), ratio.text())
        for name, amount, ratio in page.chart.legend.rows
    ]
    assert legend == [("郵局活儲", "1,000", "80.0%"), ("撲滿", "250", "20.0%")]

    table = {
        page.model.index(row, 0).data(): page.model.index(row, 1).data()
        for row in range(page.model.rowCount())
    }
    for name, amount, _ratio in legend:
        assert table[name] == amount, "圖例與表格對同一個帳戶講了不同的金額"

    # 沒有負餘額帳戶時分母就是總資產，圖例底下那句話是多餘的。
    assert not page.chart.caption.isVisible()
    assert not page.negative_note.isVisible()


def test_a_negative_balance_is_named_instead_of_being_drawn(window) -> None:
    """**圓餅對負數沒有意義**，所以那個帳戶不畫 —— 但一定要講出來。

    取絕對值畫的話，一個把錢吃掉的帳戶會看起來像一份資產。默默漏掉則會讓使用者
    拿百分比去乘總資產然後對不起來 —— 所以分母也要寫出來。
    """
    controller = window.controller
    assert controller.create_account("郵局活儲", "1000").success
    assert controller.create_account("撲滿", "250").success
    assert controller.create_account("信用卡", "0").success
    card = next(
        str(item["account_id"])
        for item in controller.account_options()
        if item["name"] == "信用卡"
    )
    assert controller.submit(
        occurred_at="2026-08-19T10:00:00+08:00",
        entry_type="expense",
        amount="3000",
        account_id=card,
        destination_account_id=None,
        category_id="cat_food_711",
        description="刷卡",
    ).success
    window.show_page(PageId.OVERVIEW)

    page = window.overview
    names = [name.text() for name, _amount, _ratio in page.chart.legend.rows]
    assert names == ["郵局活儲", "撲滿"], "負餘額帳戶不該出現在圓環上"

    assert page.negative_note.isVisible()
    assert "信用卡" in page.negative_note.text()
    assert "-3,000" in page.negative_note.text()

    # 分母是正餘額合計 1,250，不是總資產 -1,750 —— 那句話要在畫面上。
    assert page.chart.caption.isVisible()
    assert "1,250" in page.chart.caption.text()
    assert page.total.text() == "-1,750"


def test_the_snapshot_reminder_lives_on_the_page_not_the_status_bar(window) -> None:
    """盤點提醒是**頁面上的一行字加一顆按鈕**，不是 10 秒就消失的狀態列訊息。

    去泡杯茶回來就看不到的提醒等於沒有提醒。按下「去盤點」要真的跳到餘額盤點頁。
    """
    window.show_page(PageId.OVERVIEW)

    page = window.overview
    assert page.snapshot_note.isVisible()
    assert page.snapshot_button.isVisible()
    assert "現金" in page.snapshot_note.text()
    assert window.statusBar().currentMessage() == ""

    page.snapshot_button.click()
    assert window.pages.currentWidget() is window.balance

    # 盤點完，提醒就該消失 —— 這是「現算」而不是讀啟動時算好的快取值。
    window.balance.amount.setText("0")
    window.balance.create_snapshot()
    window.show_page(PageId.OVERVIEW)
    assert not page.snapshot_note.isVisible()
    assert not page.snapshot_button.isVisible()
