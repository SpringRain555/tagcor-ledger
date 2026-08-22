"""資產總覽：總資產怎麼算、什麼時候重算、沒話說的區塊要收起來。

**這一頁是「切過去就重算」，不接跨頁連動的訊號** —— 理由在 `pages/overview.py`。
"""

from pathlib import Path


from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.ui.main_window import MainWindow
from tagcor_ledger.ui.navigation import PageId
from tagcor_ledger.ui.widgets.sidebar import BADGE_ROLE


def test_overview_total_is_the_sum_of_active_accounts(qtbot, tmp_path: Path) -> None:
    """總資產 = 各帳戶餘額相加，而且**封存的不算進去、但要講出來**。

    封存的意思是不再出現在選單，不是錢消失了 —— 默默把它漏掉，使用者拿這個數字去對
    存摺就會對不起來，而且找不到差在哪。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
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


def test_overview_recomputes_when_you_come_back_to_it(qtbot, tmp_path: Path) -> None:
    """在別頁改了資料，切回總覽必須是新的數字。

    這條守的是「切過去就重算」那個機制。改成在 `main_window` 的每個 `_..._changed`
    各記一筆的話，總有一天會漏掉一項，而漏掉的症狀是總資產停在舊數字 ——
    看起來像算錯帳，不像忘記重新整理。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()

    window.show_page(PageId.OVERVIEW)
    assert window.overview.total.text() == "0"

    window.show_page(PageId.ENTRY)
    window.entry.amount.setText("85")
    window.entry.submit()

    window.show_page(PageId.OVERVIEW)
    assert window.overview.total.text() == "-85"


def test_the_inbox_number_is_the_same_everywhere(qtbot, tmp_path: Path) -> None:
    """側邊欄的數字與總覽的數字走同一個來源，而且**定存也算在內**。

    兩邊各自算就會出現「側邊欄說 2、總覽說 3」，使用者沒有辦法知道哪一個才對。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    controller = window.controller

    account_id = str(controller.account_options()[0]["account_id"])
    assert controller.create_deposit_contract(
        account_id=account_id,
        name="郵局定存",
        interest_method="lump_sum",
        maturity_action="renew_principal_only",
        interest_destination_account_id=account_id,
        term_months=12,
        start_date="2020-01-15",
        principal="100000",
        annual_rate_ppm=16_000,
    ).success
    assert controller.generate_due().success
    window.refresh_pending_badge()
    window.show_page(PageId.OVERVIEW)

    count = controller.inbox_count()
    assert count >= 1, "測試資料沒有產生待確認項目，這條測試等於沒作用"
    assert count == len(controller.list_pending()) + len(controller.list_deposit_pending())
    assert window.sidebar.item_for(PageId.INBOX).data(BADGE_ROLE) == count
    assert f"{count} 筆" in window.overview.inbox_note.text()

    # 定存區塊要出現，而且說得出哪一份合約、什麼時候到期。
    assert window.overview.deposit_note.isVisible()
    assert "郵局定存" in window.overview.deposit_note.text()
    assert "2021/01/15" in window.overview.deposit_note.text()


def test_overview_hides_what_it_has_nothing_to_say_about(qtbot, tmp_path: Path) -> None:
    """空的區塊要整段消失。**留一個沒有內容的標題看起來像壞掉或還沒載入。**"""
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    window.show_page(PageId.OVERVIEW)

    page = window.overview
    assert not page.deposit_caption.isVisible()
    assert not page.deposit_note.isVisible()
    assert not page.archived_note.isVisible()
    assert not page.gap_note.isVisible()
    assert page.inbox_note.text() == "沒有待確認項目。"
    assert not page.inbox_button.isVisible()


def test_the_snapshot_reminder_lives_on_the_page_not_the_status_bar(
    qtbot, tmp_path: Path
) -> None:
    """盤點提醒是**頁面上的一行字加一顆按鈕**，不是 10 秒就消失的狀態列訊息。

    去泡杯茶回來就看不到的提醒等於沒有提醒。按下「去盤點」要真的跳到餘額盤點頁。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
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
