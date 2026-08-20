import ast
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QPushButton

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.infrastructure.clock import TAIPEI
from tagcor_ledger.ui import colors
from tagcor_ledger.ui.main_window import MainWindow
from tagcor_ledger.ui.navigation import DAILY_PAGES, SETTINGS_PAGES, PageId
from tagcor_ledger.ui.widgets.forms import date_field, iso_from_date
from tagcor_ledger.ui.widgets.sidebar import BADGE_ROLE


def test_sidebar_lists_every_page_and_keeps_the_stack_in_step(qtbot, tmp_path: Path) -> None:
    """側邊欄的順序與頁面堆疊必須一一對應。

    導覽 key 是 `PageId` 不是顯示文字 —— 所以這裡改標籤不會讓測試失效，
    改對應關係才會。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()

    assert [item.text() for item in window.sidebar.all_items()] == [
        "資產總覽",
        "記帳",
        "待確認",
        "交易紀錄",
        "餘額盤點",
        "法規參考",
        "操作設定",
        "系統設定",
    ]

    for page, widget in (
        (PageId.OVERVIEW, window.overview),
        (PageId.ENTRY, window.quick),
        (PageId.INBOX, window.pending),
        (PageId.TRANSACTIONS, window.transactions),
        (PageId.BALANCE, window.balance),
        (PageId.REFERENCE, window.reference),
        (PageId.OPERATION_SETTINGS, window.operation_settings),
        (PageId.SYSTEM_SETTINGS, window.system_settings),
    ):
        window.show_page(page)
        assert window.pages.currentWidget() is widget, page

    assert window.windowTitle() == "TagCor Ledger"


def test_every_sidebar_row_can_be_clicked(qtbot, tmp_path: Path) -> None:
    """**側邊欄裡不得有任何點不動的東西。**

    分組標題失敗過兩次 —— 第一版只是顏色淡一點，第二版縮小加字距。兩次使用者的第一個
    反應都是「這是什麼？為什麼點不動？」。第三次的做法是把標籤整個拿掉，分組改用位置
    表達（日常在上、設定沉底），這條測試就是不讓它再長回來。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()

    items = window.sidebar.all_items()
    assert items
    for item in items:
        assert item.flags() & Qt.ItemFlag.ItemIsSelectable, item.text()
        assert item.flags() & Qt.ItemFlag.ItemIsEnabled, item.text()


def test_selecting_one_group_clears_the_other(qtbot, tmp_path: Path) -> None:
    """兩個清單各有 current row，選了一邊必須清掉另一邊。

    這段最容易寫成無窮遞迴：清掉對方會觸發對方的 `currentRowChanged`。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()

    window.show_page(PageId.ENTRY)
    assert window.sidebar.daily.currentRow() == DAILY_PAGES.index(PageId.ENTRY)
    assert window.sidebar.settings.currentRow() == -1

    window.show_page(PageId.SYSTEM_SETTINGS)
    assert window.sidebar.daily.currentRow() == -1
    assert window.sidebar.settings.currentRow() == SETTINGS_PAGES.index(
        PageId.SYSTEM_SETTINGS
    )
    assert window.sidebar.current_page() is PageId.SYSTEM_SETTINGS
    assert window.pages.currentWidget() is window.system_settings


def test_settings_group_sits_at_the_bottom_of_the_rail(qtbot, tmp_path: Path) -> None:
    """設定要**沉底**，中間的留白會隨視窗長高。

    如果兩個清單都用預設的 Expanding size policy，它們會各分一半空間，
    設定那一組就浮在中間 —— 分組靠位置表達的做法也就失效了。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.resize(1280, 900)
    window.show()
    qtbot.waitExposed(window)

    rail = window.sidebar
    row_height = rail.daily.sizeHintForRow(0)
    assert row_height > 0

    # 兩個清單的高度剛好等於內容 —— 沒有這一點，它們會各自長高把留白吃光。
    assert rail.daily.height() == row_height * len(DAILY_PAGES)
    assert rail.settings.height() == row_height * len(SETTINGS_PAGES)

    # 設定那一組貼在底部（只剩版面外距），而且離日常那一組有一段真正的留白。
    assert rail.height() - rail.settings.geometry().bottom() < 40
    assert rail.settings.geometry().top() - rail.daily.geometry().bottom() > 80


def test_pending_badge_is_drawn_beside_the_label_not_inside_it(qtbot, tmp_path: Path) -> None:
    """數字放在項目資料裡，**不寫進標籤文字**。

    舊做法是把文字改寫成「待確認（2）」，標籤長度會隨數字跳動 —— 而側邊欄的項目
    應該是固定不動的錨點。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()

    item = window.sidebar.item_for(PageId.INBOX)
    assert item is not None
    assert item.text() == "待確認"
    assert item.data(BADGE_ROLE) is None

    controller = window.controller
    schedule = controller.save_schedule(
        controller.new_schedule(
            name="排程",
            entry_type="expense",
            account_id="acct_cash",
            destination_account_id=None,
            category_id="cat_food_711",
            amount_minor=5000,
            description="",
            frequency="monthly",
            interval_count=1,
            start_date="2026-01-01",
            end_date=None,
        )
    )
    assert schedule.success
    assert controller.generate_due().success
    window.refresh_pending_badge()
    assert item.text() == "待確認"  # 文字不動
    assert item.data(BADGE_ROLE) == len(controller.list_pending())


def test_main_window_applies_scoped_dark_theme(qtbot, tmp_path: Path) -> None:
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()

    app = QApplication.instance()
    assert app is not None
    styles = app.styleSheet()
    assert window.sidebar.objectName() == "sidebarRail"
    assert window.sidebar.daily.objectName() == "sidebarNavigation"
    assert window.sidebar.settings.objectName() == "sidebarNavigation"
    assert window.pages.objectName() == "contentStack"
    assert window.system_settings.maintenance.list.objectName() == "backupList"
    assert "QTabBar::tab" in styles
    assert "QFrame#sidebarRail" in styles
    assert "QListWidget#sidebarNavigation" in styles
    assert "QListWidget#backupList" in styles
    assert colors.BG in styles


def test_quick_entry_switches_transfer_fields_and_saves(qtbot, tmp_path: Path) -> None:
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    page = window.quick

    page.select_entry_type("transfer")
    assert page.destination.isHidden() is False
    assert page.category.isHidden() is True

    page.select_entry_type("expense")
    page.amount.setText("85")
    page.description.setText("早餐")
    page.submit()

    result = window.controller.list_transactions()
    assert result.success
    transaction = result.details["transactions"][0]
    assert transaction["description"] == "早餐"
    assert "payee_name" not in transaction


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


def test_quick_entry_hides_the_label_together_with_the_field(qtbot, tmp_path: Path) -> None:
    """QFormLayout 的標籤是獨立 widget，只藏欄位會留下孤兒標籤（2026-08-18 實機發現）。"""
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    page = window.quick

    page.select_entry_type("expense")
    assert page.form.labelForField(page.destination).isHidden() is True
    assert page.form.labelForField(page.category).isHidden() is False
    assert page.form.labelForField(page.detail).isHidden() is False

    page.select_entry_type("transfer")
    assert page.form.labelForField(page.destination).isHidden() is False
    assert page.form.labelForField(page.category).isHidden() is True
    assert page.form.labelForField(page.detail).isHidden() is True


def test_quick_entry_reports_success_without_the_error_colour(qtbot, tmp_path: Path) -> None:
    """成功不能長得像失敗。

    舊版把「交易已儲存。」寫進紅色的 `errorLabel` —— 每天最常做的動作，回饋是紅的。
    現在用同一個標籤但帶 `state` 屬性，成功綠、失敗紅。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    page = window.quick

    page.select_entry_type("expense")
    page.amount.setText("85")
    page.submit()
    assert page.status.text() == "交易已儲存。"
    assert page.status.property("state") == "ok"

    page.amount.setText("這不是金額")
    page.submit()
    assert page.status.property("state") == "error"


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


def test_reset_confirmation_names_what_will_be_lost(qtbot, tmp_path: Path) -> None:
    """不可逆的操作要講得出「會失去什麼」，不能只說「這會清空資料」。"""
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
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


def test_date_field_stores_a_timestamp_that_preserves_ordering(qtbot) -> None:
    """畫面只問日期，資料庫仍然存完整時間戳。

    時分秒是**同一天多筆交易唯一的排序依據** —— 全部塞 00:00 的話，
    當天的順序就只能靠 id，看起來會像隨機的。
    """
    widget = date_field(QDate(2026, 8, 19))
    qtbot.addWidget(widget)

    stamped = datetime.fromisoformat(iso_from_date(widget))
    assert stamped.date() == date(2026, 8, 19)

    # 時分秒應該是「現在」，不是午夜。
    now = datetime.now(TAIPEI)
    reference = datetime.combine(stamped.date(), now.time(), tzinfo=TAIPEI)
    assert abs((stamped - reference).total_seconds()) < 5


def test_editing_keeps_the_original_time_of_day(qtbot) -> None:
    """只改備註不該讓那筆跳到當天最後一筆。"""
    widget = date_field(QDate(2026, 8, 19))
    qtbot.addWidget(widget)

    assert iso_from_date(widget, keep_time_from="2026-08-19T07:15:30+08:00") == (
        "2026-08-19T07:15:30+08:00"
    )

    # 連日期一起改時，時分秒照樣沿用。
    widget.setDate(QDate(2026, 8, 1))
    assert iso_from_date(widget, keep_time_from="2026-08-19T07:15:30+08:00") == (
        "2026-08-01T07:15:30+08:00"
    )


def test_lists_show_the_date_without_a_made_up_time(qtbot, tmp_path: Path) -> None:
    """時分秒是程式補的，印出來會讓人以為那是真的記錄時間。"""
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    window.controller.submit(
        occurred_at="2026-08-19T13:45:00+08:00",
        entry_type="expense",
        amount="85",
        account_id="acct_cash",
        destination_account_id=None,
        category_id="cat_food_711",
        description="午餐",
    )
    window.transactions.first_page()

    model = window.transactions.model
    assert model.headerData(0, Qt.Orientation.Horizontal) == "日期"
    assert model.index(0, 0).data() == "2026/08/19"


def test_navigation_labels_are_not_used_as_lookup_keys() -> None:
    """導覽查表不得以中文字串當 key。

    以前是 `show_page("快速記帳")`、`_page_rows["待確認"]` —— 改一個字就是
    執行時的 `KeyError`。身分是 `PageId`，顯示文字只從 `LABELS` 查出來。
    """
    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "tagcor_ledger"
        / "ui"
        / "main_window.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)

    offenders = [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
        and any("一" <= char <= "鿿" for char in node.slice.value)
    ]
    assert not offenders, f"這些查表用中文字串當 key：{offenders}"


def test_deposits_tab_and_pending_deposit_section_exist(qtbot, tmp_path: Path) -> None:
    """定存有自己的分頁，但到期處理一律在「待確認」頁 —— 不要有第二個入帳入口。"""
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()

    deposits = window.operation_settings.deposits
    assert deposits.contract_model.rowCount() == 0
    assert deposits.term_model.rowCount() == 0

    # 待確認頁要有定存區塊，而且一開始是空的。
    assert window.pending.deposit_model.rowCount() == 0


def test_deposit_contract_flows_into_pending_inbox(qtbot, tmp_path: Path) -> None:
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
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
    window.pending.refresh()
    assert window.pending.deposit_model.rowCount() >= 1


def test_the_app_opens_on_the_overview(qtbot, tmp_path: Path) -> None:
    """開啟程式停在資產總覽，而且它是側邊欄第一項。

    記帳是「我要做一件事」，總覽回答的是「我現在是什麼狀況」—— 打開程式的當下多半
    還沒決定要做什麼。真的要記帳，`Ctrl+N` 一鍵就到。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()

    assert DAILY_PAGES[0] is PageId.OVERVIEW
    assert window.pages.currentWidget() is window.overview
    assert window.sidebar.current_page() is PageId.OVERVIEW


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
    window.quick.amount.setText("85")
    window.quick.submit()

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
