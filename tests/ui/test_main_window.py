import ast
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QDateTimeEdit,
    QDialogButtonBox,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyleOptionViewItem,
    QTableView,
    QTabWidget,
)

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.infrastructure.clock import TAIPEI
from tagcor_ledger.ui import colors
from tagcor_ledger.ui.main_window import MainWindow
from tagcor_ledger.ui.navigation import DAILY_PAGES, LABELS, SETTINGS_PAGES, PageId
from tagcor_ledger.ui.theme import apply_dark_theme
from tagcor_ledger.ui.pages.deposits import DepositContractDialog
from tagcor_ledger.ui.widgets import forms
from tagcor_ledger.ui.widgets.forms import date_field, iso_from_date
from tagcor_ledger.ui.widgets.sidebar import BADGE_ROLE
from tagcor_ledger.ui.widgets.simple_form import SimpleFormDialog, TextField


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
        (PageId.ENTRY, window.entry),
        (PageId.INBOX, window.inbox),
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
    """兩個清單各自有選取狀態，任何時候**只有一列是選取的**。

    這段最容易寫成無窮遞迴：清掉對方會觸發對方的 `currentRowChanged`。

    量的是**選取**不是 current row。current row 是鍵盤游標的位置，兩個清單都會有一個
    （而且必須有 —— 見 `test_focus_landing_on_the_sidebar_does_not_navigate`）。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()

    def selected() -> list[str]:
        return [
            item.text()
            for lst in (window.sidebar.daily, window.sidebar.settings)
            for item in lst.selectedItems()
        ]

    window.show_page(PageId.ENTRY)
    assert selected() == [LABELS[PageId.ENTRY]]
    assert window.sidebar.current_page() is PageId.ENTRY

    window.show_page(PageId.SYSTEM_SETTINGS)
    assert selected() == [LABELS[PageId.SYSTEM_SETTINGS]]
    assert window.sidebar.current_page() is PageId.SYSTEM_SETTINGS
    assert window.pages.currentWidget() is window.system_settings


def test_focus_landing_on_the_sidebar_does_not_navigate(qtbot, tmp_path: Path) -> None:
    """焦點落到側邊欄**不等於**使用者選了一頁。

    `QAbstractItemView::focusInEvent` 在 current index 無效時會自動把它設成第一列。
    舊做法把非作用中那組的 current row 設成 -1，於是焦點一碰到「日常」那組，
    Qt 就把它設成第 0 列（資產總覽）並發出 `currentRowChanged(0)` —— 畫面就跳走了。

    使用者回報的症狀是「在操作設定裡做任何事都有機會跳回資產總覽」，因為讓焦點移動的
    事情太多了：關掉對話框、按鈕被停用、Tab。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()

    # **剛開程式、還沒點過任何一頁**時，「設定」那一組從來沒有被選過。
    # 它的 current row 若是無效的，焦點一碰就會跳到法規參考。
    for widget in (window.sidebar.daily, window.sidebar.settings):
        widget.setFocus(Qt.FocusReason.TabFocusReason)
        QApplication.processEvents()
        assert window.pages.currentWidget() is window.overview, (
            "啟動後焦點碰到側邊欄就離開了首頁"
        )
        widget.clearFocus()

    for reason in (
        Qt.FocusReason.TabFocusReason,
        Qt.FocusReason.OtherFocusReason,
        Qt.FocusReason.ActiveWindowFocusReason,
        Qt.FocusReason.PopupFocusReason,
    ):
        window.show_page(PageId.OPERATION_SETTINGS)
        for widget in (window.sidebar.daily, window.sidebar.settings):
            widget.clearFocus()
            widget.setFocus(reason)
            # focusInEvent 是**送出去**的，不處理事件佇列就等於沒有發生 ——
            # 少了這一行，這條測試在壞掉的版本上照樣是綠的。
            QApplication.processEvents()
            assert window.pages.currentWidget() is window.operation_settings, (
                f"焦點以 {reason.name} 落到側邊欄就把畫面帶走了 —— "
                f"現在停在 {window.pages.currentWidget()}"
            )
            assert window.sidebar.current_page() is PageId.OPERATION_SETTINGS


def test_tabbing_through_a_settings_tab_never_changes_the_page(
    qtbot, tmp_path: Path
) -> None:
    """在一頁裡按 Tab 只該在那一頁裡繞，不該換頁。

    實測舊版按第 4 次 Tab 就跳走：焦點鏈是
    `QTabBar → QPushButton → QTableView → 側邊欄清單`。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    window.show_page(PageId.OPERATION_SETTINGS)
    window.operation_settings.setFocus(Qt.FocusReason.OtherFocusReason)

    for step in range(40):
        window.focusNextPrevChild(True)
        QApplication.processEvents()
        assert window.pages.currentWidget() is window.operation_settings, (
            f"按了 {step + 1} 次 Tab 就換頁了"
        )


def test_clicking_the_current_page_again_still_works(qtbot, tmp_path: Path) -> None:
    """點一列就是選那一頁，**不管它是不是已經是 current row**。

    修焦點問題時兩個清單都保有 current row，所以「點自己那一組裡 current 的那一列」
    不會觸發 `currentRowChanged`。少了 `itemClicked` 這條路，那一列會變成點不動的 ——
    而側邊欄裡不該有任何點不動的東西。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()

    # 先讓「日常」那組的 current row 停在資產總覽，再切去設定那組。
    window.show_page(PageId.OVERVIEW)
    window.show_page(PageId.SYSTEM_SETTINGS)
    assert window.sidebar.daily.currentRow() == DAILY_PAGES.index(PageId.OVERVIEW)

    item = window.sidebar.item_for(PageId.OVERVIEW)
    assert item is not None
    window.sidebar.daily.itemClicked.emit(item)

    assert window.pages.currentWidget() is window.overview
    assert window.sidebar.current_page() is PageId.OVERVIEW


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


def test_entry_page_switches_transfer_fields_and_saves(qtbot, tmp_path: Path) -> None:
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    page = window.entry

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


def test_entry_page_hides_the_label_together_with_the_field(qtbot, tmp_path: Path) -> None:
    """QFormLayout 的標籤是獨立 widget，只藏欄位會留下孤兒標籤（2026-08-18 實機發現）。"""
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    page = window.entry

    page.select_entry_type("expense")
    assert page.form.labelForField(page.destination).isHidden() is True
    assert page.form.labelForField(page.category).isHidden() is False
    assert page.form.labelForField(page.detail).isHidden() is False

    page.select_entry_type("transfer")
    assert page.form.labelForField(page.destination).isHidden() is False
    assert page.form.labelForField(page.category).isHidden() is True
    assert page.form.labelForField(page.detail).isHidden() is True


def test_entry_page_reports_success_without_the_error_colour(qtbot, tmp_path: Path) -> None:
    """成功不能長得像失敗。

    舊版把「交易已儲存。」寫進紅色的 `errorLabel` —— 每天最常做的動作，回饋是紅的。
    現在用同一個標籤但帶 `state` 屬性，成功綠、失敗紅。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    page = window.entry

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


def test_adding_an_account_that_already_exists_just_selects_it(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    """定存對話框的「新增帳戶…」打到既有名字時，要把它選起來而不是丟錯誤。

    預設值是「郵局定存」，也就是最可能已經開過的名字 —— 第二次按必然撞名。
    舊版丟一個警告框，內容還帶著 `UNIQUE constraint failed: accounts.name`。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
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


def test_deposits_tab_and_pending_deposit_section_exist(qtbot, tmp_path: Path) -> None:
    """定存有自己的分頁，但到期處理一律在「待確認」頁 —— 不要有第二個入帳入口。"""
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()

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
    window.inbox.refresh()
    sources = [
        window.inbox.model.items[row]["source"]
        for row in range(window.inbox.model.rowCount())
    ]
    assert "deposit" in sources


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


def test_a_category_with_items_can_be_selected_and_renamed(qtbot, tmp_path: Path, monkeypatch) -> None:
    """**有子項目的類別必須有自己的一列。**

    舊的 `CatalogPage` 只在類別「沒有」子項目時才把它自己加成一列，所以「伙食」永遠
    不會出現 —— 畫面上看到的那個「伙食」是項目那一列的第一欄。於是改名、封存、刪除
    對類別**全部失效**：你選到的一直是項目。

    這裡不能只斷言「畫面上有『伙食』兩個字」—— 那在壞掉的版本裡照樣成立。
    要比對的是**那一列的 category_id**。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    controller = window.controller

    page = window.operation_settings.categories
    page.refresh()
    rows = [page.model.items[index] for index in range(page.model.rowCount())]
    ids = [str(row["category_id"]) for row in rows]
    assert "cat_food" in ids, f"「伙食」有子項目，但列表裡沒有它自己的列：{ids}"

    # 選到它，改名，然後確認改的是類別而不是項目。
    row_index = ids.index("cat_food")
    page.table.selectRow(row_index)
    monkeypatch.setattr(
        "tagcor_ledger.ui.pages.catalog.ask_form",
        lambda *args, **kwargs: {"name": "伙食費"},
    )
    page.rename_selected()

    names = {
        str(item["category_id"]): str(item["name"])
        for item in controller.category_options()
    }
    assert names["cat_food"] == "伙食費"
    assert names.get("cat_food_711") is None  # 項目不在第一層
    children = {
        str(item["category_id"]): str(item["name"])
        for item in controller.category_options("cat_food")
    }
    assert children["cat_food_711"] == "7-11", "改到的是項目，不是類別"

    # 舊交易要跟著顯示新名字。
    controller.submit(
        occurred_at="2026-08-19T10:00:00+08:00",
        entry_type="expense",
        amount="85",
        account_id="acct_cash",
        destination_account_id=None,
        category_id="cat_food_711",
        description="午餐",
    )
    window.transactions.first_page()
    assert window.transactions.model.index(0, 3).data() == "伙食費 / 7-11"


def test_operation_settings_has_six_tabs_in_the_agreed_order(qtbot, tmp_path: Path) -> None:
    """**順序本身就是分組**：前四個是記帳會用到的名冊，後兩個是會自己到期的東西。

    所以這裡連順序一起釘住，不只是「有沒有這六個」。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()

    tabs = window.operation_settings.findChild(QTabWidget, "settingsTabs")
    assert tabs is not None
    assert [tabs.tabText(index) for index in range(tabs.count())] == [
        "帳戶",
        "類別",
        "項目",
        "模板",
        "定期收支",
        "定存",
    ]
    # 分頁與屬性必須是同一個物件，不然 refresh() 會刷到沒有顯示出來的那一份。
    page = window.operation_settings
    assert [tabs.widget(index) for index in range(tabs.count())] == [
        page.accounts,
        page.categories,
        page.items,
        page.templates,
        page.recurring,
        page.deposits,
    ]


def test_the_word_schedule_no_longer_appears_in_the_ui(qtbot, tmp_path: Path) -> None:
    """「週期排程」是實作的名字，使用者想的是「每個月會自動扣款的那些」。

    程式識別字 `recurring_schedules` / `schedule_id` **不動** —— 那是 schema，
    改它要 migration，而使用者看不到它。這條只掃畫面上的字。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()

    texts = [
        button.text() for button in window.operation_settings.findChildren(QPushButton)
    ]
    tabs = window.operation_settings.findChild(QTabWidget, "settingsTabs")
    assert tabs is not None
    texts += [tabs.tabText(index) for index in range(tabs.count())]

    assert "定期收支" in texts
    offenders = [text for text in texts if "排程" in text]
    assert not offenders, f"畫面上還有「排程」：{offenders}"


def test_items_page_filters_by_category(qtbot, tmp_path: Path) -> None:
    """項目一多就找不到自己要的那一個，所以「項目」分頁上方有類別篩選。"""
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    controller = window.controller

    transport = controller.create_category("交通")
    assert transport.success
    transport_id = str(transport.details["category_id"])
    assert controller.create_category("電子票證儲值", transport_id).success
    assert controller.create_category("早餐店", "cat_food").success

    page = window.operation_settings.items
    page.refresh()
    assert {page.model.index(row, 1).data() for row in range(page.model.rowCount())} == {
        "7-11",
        "早餐店",
        "電子票證儲值",
    }

    index = page.parent_filter.findData(transport_id)
    assert index > 0, "篩選下拉裡沒有「交通」"
    page.parent_filter.setCurrentIndex(index)
    rows = [
        (page.model.index(row, 0).data(), page.model.index(row, 1).data())
        for row in range(page.model.rowCount())
    ]
    assert rows == [("交通", "電子票證儲值")]

    # 篩選在重新整理之後要保住 —— 新增一個項目不該把畫面跳回「全部」。
    assert controller.create_category("加油", transport_id).success
    page.refresh()
    assert page.parent_filter.currentData() == transport_id
    assert page.model.rowCount() == 2


def test_categories_page_counts_its_items(qtbot, tmp_path: Path) -> None:
    """「項目數」是一起查出來的，不是每個類別再查一次。"""
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    assert window.controller.create_category("早餐店", "cat_food").success
    assert window.controller.create_category("交通").success

    page = window.operation_settings.categories
    page.refresh()
    counts = {
        page.model.index(row, 0).data(): page.model.index(row, 1).data()
        for row in range(page.model.rowCount())
    }
    assert counts["伙食"] == "2 項"
    assert counts["交通"] == "0 項"


def _inbox_rows(window: MainWindow) -> list[list[str]]:
    model = window.inbox.model
    return [
        [model.index(row, column).data() for column in range(model.columnCount())]
        for row in range(model.rowCount())
    ]


def _make_schedule(controller, name: str, start_date: str) -> None:
    result = controller.save_schedule(
        controller.new_schedule(
            name=name,
            entry_type="expense",
            account_id="acct_cash",
            destination_account_id=None,
            category_id="cat_food_711",
            amount_minor=1200000,
            description="",
            frequency="monthly",
            interval_count=1,
            start_date=start_date,
            end_date=None,
        )
    )
    assert result.success, result.message


def _make_deposit(controller) -> None:
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


def test_the_inbox_is_one_table_with_a_source_column(qtbot, tmp_path: Path) -> None:
    """定期收支與定存**在同一張表**，靠「來源」欄分辨。

    以前是上下兩張表加六顆按鈕：「我還有幾件事要處理」要自己把兩個數字加起來，
    按按鈕之前還得先想清楚哪三顆是對上面那張表的。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    controller = window.controller

    _make_schedule(controller, "房租", "2026-06-01")
    _make_deposit(controller)
    assert controller.generate_due().success
    window.inbox.refresh()

    model = window.inbox.model
    assert [
        model.headerData(column, Qt.Orientation.Horizontal)
        for column in range(model.columnCount())
    ] == ["到期日", "來源", "名稱", "類型", "金額（TWD）", "狀態說明"]

    sources = {row[1] for row in _inbox_rows(window)}
    assert sources == {"定期", "定存"}, sources
    # 一張表，不是兩張。
    assert len(window.inbox.findChildren(QTableView)) == 1

    # 依到期日排序，而且是顯示用的斜線格式，不是資料庫的 ISO 字串。
    dates = [row[0] for row in _inbox_rows(window)]
    assert dates == sorted(dates)
    assert all("/" in date_text for date_text in dates), dates


def test_the_inbox_explains_itself_when_it_is_empty(qtbot, tmp_path: Path) -> None:
    """**這一段文字就是「我忘記這頁是做什麼的」的正解。**

    空表格加三顆停用的按鈕說不出任何事情。沒有項目時整組操作收起來，換成說明。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    window.show_page(PageId.INBOX)

    page = window.inbox
    assert page.model.rowCount() == 0
    assert page.empty.isVisibleTo(page)
    assert not page.table.isVisibleTo(page)
    for button in (page.confirm_button, page.skip_button, page.confirm_all_button):
        assert not button.isVisibleTo(page)

    text = page.empty.text()
    assert "定期收支" in text
    assert "定存" in text
    assert "確認之後才會變成交易" in text
    assert "操作設定 → 定期收支" in text

    # 有東西之後就換回表格。
    _make_schedule(window.controller, "房租", "2026-06-01")
    assert window.controller.generate_due().success
    page.refresh()
    assert page.table.isVisibleTo(page)
    assert not page.empty.isVisibleTo(page)
    assert page.confirm_button.isVisibleTo(page)


def test_confirming_dispatches_by_source(qtbot, tmp_path: Path, monkeypatch) -> None:
    """「確認入帳」對定期收支開修改對話框，對定存問實際金額。

    兩種來源在同一張表裡，所以分派錯了不會有任何錯誤訊息 —— 只會開錯一個視窗。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    controller = window.controller
    _make_deposit(controller)
    assert controller.generate_due().success
    window.inbox.refresh()

    rows = [
        index
        for index in range(window.inbox.model.rowCount())
        if window.inbox.model.items[index]["source"] == "deposit"
    ]
    assert rows, "沒有定存項目，這條測試等於沒作用"
    window.inbox.table.selectRow(rows[0])

    asked: list[str] = []

    def fake_get_text(*args: object, **kwargs: object) -> tuple[str, bool]:
        asked.append(str(args[2]) if len(args) > 2 else "")
        return ("842", True)

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", fake_get_text)
    before = controller.inbox_count()
    window.inbox.confirm_selected()

    assert asked, "定存項目沒有問實際金額"
    assert "存摺" in asked[0], asked[0]
    assert controller.inbox_count() == before - 1


def test_confirm_all_leaves_deposits_alone_and_says_so(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    """**「全部確認」不碰定存。**

    定存的權威金額在存摺上，建議值只是試算 —— 批次套用試算值等於替使用者決定了一個
    他沒看過的數字。但也不能默默跳過，訊息要講清楚還剩幾件。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    controller = window.controller
    _make_schedule(controller, "房租", "2026-06-01")
    _make_deposit(controller)
    assert controller.generate_due().success
    window.inbox.refresh()

    shown: list[str] = []
    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.information",
        lambda *args, **kwargs: shown.append(str(args[2])),
    )
    window.inbox.confirm_all()

    assert shown and "定存" in shown[0], shown
    remaining = {item["source"] for item in controller.list_inbox()}
    assert remaining == {"deposit"}, f"定存不該被批次確認掉：{remaining}"


def test_generate_button_only_shows_up_when_there_is_more_to_generate(
    qtbot, tmp_path: Path
) -> None:
    """「繼續產生」平常不出現。

    啟動時本來就會產生一次，所以平常按它什麼都不會發生 —— **一顆按了沒反應的按鈕
    比沒有按鈕更糟**。只有真的還有漏期時才浮出一行提示與一顆行內按鈕。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    page = window.inbox

    assert not window.controller.generation_has_more
    assert not page.more_button.isVisibleTo(page)
    assert not page.more_hint.isVisibleTo(page)

    window.controller.generation_has_more = True
    page.refresh()
    assert page.more_button.isVisibleTo(page)
    assert "漏期" in page.more_hint.text()


# --- 跨頁連動：改動帳務的動作必須讓餘額盤點重算 ---------------------------------
#
# 這一組守的是 2026-08-21 找到的三個缺口。它們的共通點是「動作做了、資料庫也對了，
# 但畫面上另一頁還停在舊數字」—— 分層測試與整合測試全部都是綠的，因為**少接一條
# 訊號線不會讓任何一層失敗**。所以守門只能寫在這一層。


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


def test_confirming_an_inbox_item_refreshes_the_transaction_list(
    qtbot, tmp_path: Path
) -> None:
    """待確認按下確認入帳會建立**真的交易**，所以交易紀錄與側邊欄數字都要跟著動。

    以前 `inbox.changed` 只接到側邊欄徽章，於是確認完房租切到交易紀錄，那一筆不在那裡。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    controller = window.controller

    schedule = controller.new_schedule(
        name="房租",
        entry_type="expense",
        account_id="acct_cash",
        destination_account_id=None,
        category_id="cat_food_711",
        amount_minor=12_000,
        description="每月房租",
        frequency="yearly",
        interval_count=1,
        start_date="2026-01-01",
        end_date="2026-01-01",
    )
    assert controller.save_schedule(schedule).success
    assert controller.generate_due().success
    window.inbox.refresh()

    occurrence = controller.list_pending()[0]
    badge_before = window.sidebar.item_for(PageId.INBOX).data(BADGE_ROLE)
    assert badge_before, "先要有一件待確認，否則這條測試什麼都沒驗到"
    assert window.transactions.model.rowCount() == 0

    assert controller.confirm_occurrence(str(occurrence["occurrence_id"])).success
    window.inbox.refresh()

    assert window.transactions.model.rowCount() == 1, (
        "確認入帳會建立交易，交易紀錄必須重載 —— 沒有就代表 inbox 只通知了徽章"
    )
    assert not window.sidebar.item_for(PageId.INBOX).data(BADGE_ROLE)


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


# --- 日期欄與日曆彈出視窗 -------------------------------------------------------


def test_clicking_inside_the_date_field_never_changes_the_year(qtbot) -> None:
    """**點日期欄的任何一處都不該改到日期。**

    `QStyle::SubControl` 有兩組列舉值是同一個數字：`SC_ComboBoxFrame == SC_SpinBoxUp`
    （0x1）、`SC_ComboBoxEditField == SC_SpinBoxDown`（0x2）。`QDateTimeEdit` 在
    `calendarPopup` 模式下用 CC_ComboBox 命中測試，非箭頭的結果會轉給
    `QAbstractSpinBox::mousePressEvent`，而它拿同一個數字去比 spinbox 的上下鍵。

    平常那圈框線只有 1 px，但本專案的 QSS 給輸入欄 `padding: 7px 10px` —— 那圈變成
    7～10 px，正好在使用者伸手去點右邊箭頭的路徑上。而 `displayFormat` 以 `yyyy`
    開頭，所以動到的是**年份**：點內距 +1，點文字 −1。

    這裡量的是行為不是設定值：真的送滑鼠事件進去，看日期有沒有變。
    """
    field = date_field()
    qtbot.addWidget(field)
    field.show()
    original = field.date()
    rect = field.rect()

    checked = 0
    for name, point in (
        ("上緣內距", QPoint(60, 3)),
        ("下緣內距", QPoint(60, rect.height() - 4)),
        ("左緣內距", QPoint(3, rect.height() // 2)),
        ("文字正中", QPoint(60, rect.height() // 2)),
    ):
        qtbot.mouseClick(field, Qt.MouseButton.LeftButton, pos=point)
        assert field.date() == original, (
            f"點「{name}」把日期改成了 {field.date().toString('yyyy/MM/dd')}"
            f"（原本 {original.toString('yyyy/MM/dd')}）"
        )
        checked += 1
    assert checked == 4


def test_the_date_field_keeps_the_calendar_popup_arrow(qtbot) -> None:
    """關掉上下鍵之後，**日曆還是要打得開** —— 否則就只是把功能拿掉而不是修好。

    箭頭是 `CC_ComboBox` 畫的，`buttonSymbols` 影響不到它；開日曆那條路徑也在
    轉交給 spinbox 之前就處理完了。
    """
    field = date_field()
    qtbot.addWidget(field)
    field.show()
    assert field.calendarPopup() is True
    assert field.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
    assert field.calendarWidget() is not None


def test_the_date_field_starts_on_the_day_section_and_has_a_range(qtbot) -> None:
    """鍵盤與滾輪預設動「日」，而且年份有上下界。

    `displayFormat` 以 `yyyy` 開頭時 Qt 預設停在年份那一段，於是按一下方向鍵就是
    跳一年。日期範圍則是防手滑用的護欄：沒有它年份可以一路打到 9999。
    """
    field = date_field()
    qtbot.addWidget(field)
    assert field.currentSection() == QDateTimeEdit.Section.DaySection
    assert field.minimumDate().year() == forms.MIN_YEAR
    assert field.maximumDate() > QDate.currentDate()
    # 上限必須放得下最長的定存（600 個月 = 50 年），否則到期日會被無聲夾掉。
    assert field.maximumDate() >= QDate.currentDate().addYears(50)


def test_calendar_cells_are_wide_and_tall_enough_for_two_digit_dates(qtbot) -> None:
    """日期格要放得下兩位數，否則每一格都會顯示成「...」。

    量的是 `SE_ItemViewItemText`（delegate 真正拿到的文字矩形），不是欄寬 ——
    2026-08-18 那次就是只看欄寬，以為修好了。實際上欄寬 33 px 綽綽有餘，是
    `QTableView::item { padding: 7px 8px }` 把文字矩形壓成 17x7，**高度**不夠才省略的。

    **斷言寫成「文字矩形幾乎等於整格」而不是「放得下 26 這兩個字」**，因為欄寬與字型
    會隨平台改變（offscreen 用的是 fallback 字型），而「有沒有被那圈 padding 吃掉」
    是不變的：壞掉時 33x21 的格子只剩 17x7，修好之後就是整格。
    """
    # **主題一定要真的套上去，否則這條測試什麼都沒驗到。** 樣式表是掛在 QApplication
    # 上的，只有建過 MainWindow 的測試才會設它 —— 單獨跑這一條時它是空的，於是
    # 「有沒有被 padding 吃掉」根本不會發生。2026-08-21 第一版就是這樣假性通過的。
    application = QApplication.instance()
    apply_dark_theme(application)
    assert "QTableView::item" in application.styleSheet(), (
        "樣式表裡沒有那條全域的 item padding —— 這條守門失去了它要防的東西"
    )

    field = date_field()
    qtbot.addWidget(field)
    calendar = field.calendarWidget()
    assert calendar is not None
    # 要**真的排版過**才量得到最終的格子大小；沒 show 過的 view 回報的是預設值。
    calendar.resize(320, 260)
    calendar.show()
    qtbot.waitExposed(calendar)
    view = calendar.findChild(QTableView, "qt_calendar_calendarview")
    assert view is not None, "找不到日曆的日期格 view，這條測試什麼都沒驗到"
    model = view.model()

    checked = 0
    for row in range(model.rowCount()):
        for column in range(model.columnCount()):
            index = model.index(row, column)
            text = str(model.data(index, Qt.ItemDataRole.DisplayRole) or "")
            if len(text) != 2 or not text.isdigit():
                continue
            option = QStyleOptionViewItem()
            option.initFrom(view)
            option.rect = view.visualRect(index)
            view.itemDelegate().initStyleOption(option, index)
            text_rect = view.style().subElementRect(
                QStyle.SubElement.SE_ItemViewItemText, option, view
            )
            cell = option.rect
            assert text_rect.height() >= cell.height() - 2, (
                f"第 {text} 格：格子高 {cell.height()} px，但文字只分到 "
                f"{text_rect.height()} px —— `::item` 的 padding 又跑回來了"
            )
            assert text_rect.width() >= cell.width() - 2, (
                f"第 {text} 格：格子寬 {cell.width()} px，但文字只分到 "
                f"{text_rect.width()} px —— `::item` 的 padding 又跑回來了"
            )
            checked += 1
    assert checked >= 10, f"只檢查到 {checked} 個兩位數日期，抓格子的方式有問題"


def test_the_calendar_is_tall_enough_for_six_week_rows(qtbot) -> None:
    """有些月份真的會用到第六列（1 號在週六又是 31 天），少一列就是最後一排被切掉。

    QSS 改了列高之後 `QCalendarPopup` 算出來的高度會少一截 —— 2026-08-21 實測切掉 7 px。
    """
    field = date_field()
    qtbot.addWidget(field)
    field.show()
    calendar = field.calendarWidget()
    assert calendar is not None
    view = calendar.findChild(QTableView, "qt_calendar_calendarview")
    assert view is not None
    rows = view.model().rowCount()
    assert rows == forms.CALENDAR_ROWS, f"日曆的列數變成 {rows}，最小高度的算法要跟著改"
    needed = sum(view.rowHeight(row) for row in range(rows))
    assert calendar.minimumHeight() >= needed, (
        f"日曆最小高度 {calendar.minimumHeight()} px 放不下 {rows} 列（要 {needed} px）"
    )


# --- 其餘缺陷（Stage 3）---------------------------------------------------------


def test_a_fresh_transfer_does_not_default_to_the_same_account(
    qtbot, tmp_path: Path
) -> None:
    """剛開程式選「轉帳」按下儲存，**不該必定失敗**。

    兩個下拉填的是同一份清單、預設都停在第 0 項，所以以前一定會撞
    `TRANSFER_SAME_ACCOUNT` —— 一個照著做就一定失敗的預設值。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    assert window.controller.create_account("郵局", "0").success
    window.entry.reload_options()

    page = window.entry
    assert page.account.count() >= 2, "要有兩個帳戶才驗得到這件事"
    assert page.destination.currentData() != page.account.currentData()

    page.select_entry_type("transfer")
    page.amount.setText("500")
    page.submit()
    assert "已儲存" in page.status.text(), page.status.text()

    # 把來源切成跟目的一樣，轉入帳戶要自己閃開。
    page.account.setCurrentIndex(
        page.account.findData(page.destination.currentData())
    )
    assert page.destination.currentData() != page.account.currentData()


def test_editing_a_deposit_contract_keeps_its_note(qtbot, tmp_path: Path) -> None:
    """修改定存合約**不可以動到備註**。

    對話框沒有備註欄位，以前卻永遠送 `note=""` 進去，而 store 無條件寫
    `note = ?` —— 使用者沒有任何機會發現備註被洗掉了。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
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


def test_editing_a_deposit_contract_hides_the_term_only_fields(
    qtbot, tmp_path: Path
) -> None:
    """修改合約時不顯示起存日與本金 —— 它們是「期」的欄位，這裡沒有值可以回填。

    以前那幾格是停用但**仍然顯示建立用的預設值**：起存日＝今天、本金＝空白。
    一個灰掉卻寫著今天的「起存日」比沒有那一列更糟，它看起來像事實。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
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


def test_the_paths_page_shows_the_data_root(qtbot, tmp_path: Path) -> None:
    """「資料路徑」要看得到資料根目錄。

    `PATH_OUTSIDE_DATA_ROOT` 這個錯誤講的正是這個值，而它是從「記帳資料路徑」的
    上一層推出來的 —— 畫面上沒有它，使用者就只能猜訊息在說哪個資料夾。
    """
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


# --- 一次問完的小表單（Stage 4）-------------------------------------------------


def test_the_simple_form_disables_ok_until_required_fields_are_filled(qtbot) -> None:
    """必填欄空白時「確定」是停用的。

    **不要讓使用者按下去才知道不行。** 空白名稱送到 store 換來的是
    `..._NAME_REQUIRED` 警告框，而那句話說的是他早就看得到的事。
    """
    dialog = SimpleFormDialog(
        "新增帳戶",
        [TextField("name", "帳戶名稱"), TextField("balance", "期初餘額（TWD）", default="0")],
        None,
    )
    qtbot.addWidget(dialog)
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)

    assert ok.isEnabled() is False, "名稱還空著就可以按確定"
    dialog._widgets["name"].setText("郵局")
    assert ok.isEnabled() is True
    dialog._widgets["name"].setText("   ")
    assert ok.isEnabled() is False, "只打空白也算沒填"

    dialog._widgets["name"].setText("郵局")
    assert dialog.values() == {"name": "郵局", "balance": "0"}


def test_adding_an_item_asks_everything_in_one_dialog(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    """新增項目**只開一次對話框**，而且類別是用 id 帶的不是用名字反查的。

    舊版是兩個連續的 `QInputDialog`：先選上層類別按 OK，再打名稱按 OK ——
    取消第二個，第一個選的類別就靜靜消失了。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    controller = window.controller
    assert controller.create_category("交通").success
    transport_id = next(
        str(item["category_id"])
        for item in controller.category_options()
        if item["name"] == "交通"
    )

    asked: list[list[Any]] = []

    def fake_ask(parent: Any, title: str, fields: Any) -> dict[str, Any]:
        asked.append(list(fields))
        assert title == "新增項目"
        options = dict(fields[0].options)
        # 下拉帶的是 id，不是顯示文字 —— 這正是舊版用 `labels.index()` 反查的地方。
        return {"parent_id": options["交通"], "name": "捷運"}

    monkeypatch.setattr("tagcor_ledger.ui.pages.catalog.ask_form", fake_ask)
    page = window.operation_settings.items
    page.add_item()

    assert len(asked) == 1, f"問了 {len(asked)} 次，應該只問一次"
    labels = [spec.label for spec in asked[0]]
    assert labels == ["所屬類別", "項目名稱"], labels

    children = {
        str(item["name"]): str(item["category_id"])
        for item in controller.category_options(transport_id)
    }
    assert "捷運" in children, f"項目沒有建在「交通」底下：{children}"


def test_adding_an_account_asks_everything_in_one_dialog(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    """新增帳戶也是一次問完，而且第一格叫「帳戶名稱」不是「名稱」。"""
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()

    asked: list[list[Any]] = []
    monkeypatch.setattr(
        "tagcor_ledger.ui.pages.catalog.ask_form",
        lambda parent, title, fields: (
            asked.append(list(fields)) or {"name": "郵局", "balance": "100000"}
        ),
    )
    window.operation_settings.accounts.add_item()

    assert len(asked) == 1
    assert [spec.label for spec in asked[0]] == ["帳戶名稱", "期初餘額（TWD）"]
    names = {str(item["name"]) for item in window.controller.account_options()}
    assert "郵局" in names


def test_creating_a_duplicate_category_says_which_name_clashed(
    qtbot, tmp_path: Path
) -> None:
    """同名衝突要有自己的錯誤碼與說法，不要塌成一句「請確認名稱沒有重複且上層類別有效」。

    以前三種失敗共用 `CATEGORY_CREATE_FAILED`，訊息後面還接著 SQLite 原文
    —— 一句同時指控兩個欄位、又沒說是哪個名字重複的話。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    controller = window.controller

    duplicate = controller.create_category("伙食")
    assert not duplicate.success
    assert duplicate.error_code == "CATEGORY_ACTIVE_NAME_CONFLICT", duplicate.error_code
    assert "伙食" in duplicate.message
    assert "reason" not in duplicate.details, "SQLite 原文不可以印到畫面上"

    blank = controller.create_category("   ")
    assert blank.error_code == "CATEGORY_NAME_REQUIRED", blank.error_code

    orphan = controller.create_category("早餐", "cat_does_not_exist")
    assert orphan.error_code == "CATEGORY_PARENT_INVALID", orphan.error_code


# --- 類別／項目的篩選與排序（Stage 5）------------------------------------------


def _column(page: Any, column: int) -> list[str]:
    return [
        str(page.model.index(row, column).data()) for row in range(page.model.rowCount())
    ]


def test_catalog_pages_filter_by_search_status_and_parent(
    qtbot, tmp_path: Path
) -> None:
    """搜尋、狀態、所屬類別三個條件都要真的縮短清單。

    **項目也要能用類別名搜到** —— 打「交通」就該列出交通底下的每一項，
    不然使用者得先知道項目叫什麼才找得到它。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    controller = window.controller

    transport = controller.create_category("交通")
    assert transport.success
    transport_id = str(transport.details["category_id"])
    assert controller.create_category("捷運", transport_id).success
    assert controller.create_category("加油", transport_id).success
    assert controller.create_category("早餐店", "cat_food").success

    page = window.operation_settings.items
    page.refresh()
    assert set(_column(page, 1)) == {"7-11", "早餐店", "捷運", "加油"}

    # 用項目名搜
    page.filter_bar.search.setText("捷")
    assert _column(page, 1) == ["捷運"]

    # 用類別名搜 —— 交通底下的兩個都要出來
    page.filter_bar.search.setText("交通")
    assert set(_column(page, 1)) == {"捷運", "加油"}

    page.filter_bar.search.clear()
    index = page.parent_filter.findData(transport_id)
    assert index > 0, "篩選下拉裡沒有「交通」"
    page.parent_filter.setCurrentIndex(index)
    assert set(_column(page, 1)) == {"捷運", "加油"}

    # 狀態：封存一個之後，「使用中」看不到它、「已封存」只看得到它
    page.parent_filter.setCurrentIndex(0)
    page.filter_bar.search.clear()
    assert controller.archive_category("cat_food_711").success
    page.refresh()

    page.filter_bar.status.setCurrentIndex(
        page.filter_bar.status.findData("active")
    )
    assert "7-11" not in _column(page, 1)
    page.filter_bar.status.setCurrentIndex(
        page.filter_bar.status.findData("archived")
    )
    assert _column(page, 1) == ["7-11"]
    page.filter_bar.status.setCurrentIndex(page.filter_bar.status.findData("all"))
    assert "7-11" in _column(page, 1)


def test_clicking_a_header_sorts_and_reverses(qtbot, tmp_path: Path) -> None:
    """點表頭排序，再點一次反向。**排序是 SQL 做的，不是 QTableView 自己排的。**"""
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    controller = window.controller
    for name in ("交通", "娛樂", "醫療"):
        assert controller.create_category(name).success
    assert controller.create_category("捷運", 
        str(next(item["category_id"] for item in controller.category_options()
                 if item["name"] == "交通"))).success

    page = window.operation_settings.categories
    page.refresh()
    header = page.table.horizontalHeader()
    assert header.sectionsClickable(), "表頭不能點就沒有排序可言"
    assert page.table.isSortingEnabled() is False, (
        "setSortingEnabled(True) 會讓 QTableView 在 Python 裡排序 —— 規則禁止"
    )

    header.setSortIndicator(0, Qt.SortOrder.AscendingOrder)
    ascending = _column(page, 0)
    header.setSortIndicator(0, Qt.SortOrder.DescendingOrder)
    descending = _column(page, 0)
    assert ascending == sorted(ascending)
    assert descending == list(reversed(ascending)), (ascending, descending)

    # 依「項目數」排：交通有 1 項、其餘 0 項（伙食有 1 項）
    header.setSortIndicator(1, Qt.SortOrder.DescendingOrder)
    counts = _column(page, 1)
    assert counts == sorted(counts, reverse=True), counts


def test_the_parent_dropdown_keeps_every_category_while_searching(
    qtbot, tmp_path: Path
) -> None:
    """搜尋縮短了清單，**「所屬類別」下拉不能跟著只剩搜到的那幾個** —— 否則換不回去。"""
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    assert window.controller.create_category("交通").success

    page = window.operation_settings.items
    page.refresh()
    before = [page.parent_filter.itemText(i) for i in range(page.parent_filter.count())]
    assert {"伙食", "交通"} <= set(before), before

    page.filter_bar.search.setText("7-11")
    after = [page.parent_filter.itemText(i) for i in range(page.parent_filter.count())]
    assert after == before, f"搜尋把下拉也縮掉了：{before} -> {after}"


# --- 轉帳的三種對象（Stage 6）---------------------------------------------------


def test_transfer_scope_switches_the_fields_and_the_account_label(
    qtbot, tmp_path: Path
) -> None:
    """三種對象各自顯示對的欄位，而「帳戶」那一列要說出它現在問的是什麼。

    對外轉帳要類別／項目（它存成收入或支出），內部轉帳要轉入帳戶 —— 三種各不相同，
    而且**標籤要跟著欄位一起收**（`QFormLayout` 的標籤是獨立 widget）。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    page = window.entry

    page.select_entry_type("expense")
    assert page.form.isRowVisible(page.scope_row) is False, "非轉帳不該出現轉帳對象"
    assert page.form.isRowVisible(page.category) is True

    expected = {
        "internal": ("轉出帳戶", True, False),
        "inbound": ("收款帳戶", False, True),
        "outbound": ("付款帳戶", False, True),
    }
    page.select_entry_type("transfer")
    checked = 0
    for scope, (label, destination_visible, category_visible) in expected.items():
        page.select_transfer_scope(scope)
        assert page.form.isRowVisible(page.scope_row) is True
        assert page.form.isRowVisible(page.destination) is destination_visible, scope
        assert page.form.isRowVisible(page.category) is category_visible, scope
        assert page.form.isRowVisible(page.detail) is category_visible, scope
        account_label = page.form.labelForField(page.account)
        assert account_label.text() == label, (scope, account_label.text())
        assert account_label.isHidden() is False
        checked += 1
    assert checked == 3

    # 切回支出，標籤要變回「帳戶」
    page.select_entry_type("expense")
    assert page.form.labelForField(page.account).text() == "帳戶"


def test_each_transfer_scope_saves_the_right_entry_type(qtbot, tmp_path: Path) -> None:
    """**資料庫只有一種轉帳。** 對外的兩種存成收入與支出，總資產才會跟著動。

    這是與 `state-machines.md`「利息記成收入，不是轉帳」同一個原則：
    錢有沒有離開你的總資產，才是收支與轉帳的分界。
    """
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    controller = window.controller
    assert controller.create_account("郵局", "0").success
    window.entry.reload_options()
    page = window.entry
    page.select_entry_type("transfer")

    def total() -> int:
        return int(controller.overview_snapshot()["total_minor"])

    start = total()

    page.select_transfer_scope("internal")
    page.amount.setText("500")
    page.submit()
    assert "已儲存" in page.status.text(), page.status.text()
    assert total() == start, "自己帳戶之間搬錢，總資產不該變"

    page.select_transfer_scope("inbound")
    page.amount.setText("1200")
    page.submit()
    assert "已儲存" in page.status.text(), page.status.text()
    assert total() == start + 1200, "別人轉入是收入，總資產要增加"

    page.select_transfer_scope("outbound")
    page.amount.setText("300")
    page.submit()
    assert "已儲存" in page.status.text(), page.status.text()
    assert total() == start + 1200 - 300, "轉出給別人是支出，總資產要減少"

    kinds = [
        row["entry_type"]
        for row in controller.list_transactions().details["transactions"]
    ]
    assert sorted(kinds) == ["expense", "income", "transfer"], kinds


def test_backup_list_never_shows_a_raw_error_code(qtbot, tmp_path: Path) -> None:
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


def test_deleting_a_broken_backup_from_the_page(qtbot, tmp_path: Path, monkeypatch) -> None:
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
    qtbot, tmp_path: Path, monkeypatch
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
    qtbot, tmp_path: Path
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
