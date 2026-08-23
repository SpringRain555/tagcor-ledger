"""側邊欄、頁面堆疊與主題 —— 「哪一頁在前面」這件事。

頁面身分是 `PageId` 不是顯示文字，所以改 `LABELS` 不該讓這些測試失效。
"""

import ast
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
)

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.ui import colors
from tagcor_ledger.ui.main_window import MainWindow
from tagcor_ledger.ui.navigation import DAILY_PAGES, LABELS, SETTINGS_PAGES, PageId
from tagcor_ledger.ui.widgets.sidebar import BADGE_ROLE


def test_sidebar_lists_every_page_and_keeps_the_stack_in_step(window) -> None:
    """側邊欄的順序與頁面堆疊必須一一對應。

    導覽 key 是 `PageId` 不是顯示文字 —— 所以這裡改標籤不會讓測試失效，
    改對應關係才會。
    """

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


def test_every_sidebar_row_can_be_clicked(window) -> None:
    """**側邊欄裡不得有任何點不動的東西。**

    分組標題失敗過兩次 —— 第一版只是顏色淡一點，第二版縮小加字距。兩次使用者的第一個
    反應都是「這是什麼？為什麼點不動？」。第三次的做法是把標籤整個拿掉，分組改用位置
    表達（日常在上、設定沉底），這條測試就是不讓它再長回來。
    """

    items = window.sidebar.all_items()
    assert items
    for item in items:
        assert item.flags() & Qt.ItemFlag.ItemIsSelectable, item.text()
        assert item.flags() & Qt.ItemFlag.ItemIsEnabled, item.text()


def test_selecting_one_group_clears_the_other(window) -> None:
    """兩個清單各自有選取狀態，任何時候**只有一列是選取的**。

    這段最容易寫成無窮遞迴：清掉對方會觸發對方的 `currentRowChanged`。

    量的是**選取**不是 current row。current row 是鍵盤游標的位置，兩個清單都會有一個
    （而且必須有 —— 見 `test_focus_landing_on_the_sidebar_does_not_navigate`）。
    """

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


def test_focus_landing_on_the_sidebar_does_not_navigate(window) -> None:
    """焦點落到側邊欄**不等於**使用者選了一頁。

    `QAbstractItemView::focusInEvent` 在 current index 無效時會自動把它設成第一列。
    舊做法把非作用中那組的 current row 設成 -1，於是焦點一碰到「日常」那組，
    Qt 就把它設成第 0 列（資產總覽）並發出 `currentRowChanged(0)` —— 畫面就跳走了。

    使用者回報的症狀是「在操作設定裡做任何事都有機會跳回資產總覽」，因為讓焦點移動的
    事情太多了：關掉對話框、按鈕被停用、Tab。
    """

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


def test_tabbing_through_a_settings_tab_never_changes_the_page(window) -> None:
    """在一頁裡按 Tab 只該在那一頁裡繞，不該換頁。

    實測舊版按第 4 次 Tab 就跳走：焦點鏈是
    `QTabBar → QPushButton → QTableView → 側邊欄清單`。
    """
    window.show_page(PageId.OPERATION_SETTINGS)
    window.operation_settings.setFocus(Qt.FocusReason.OtherFocusReason)

    for step in range(40):
        window.focusNextPrevChild(True)
        QApplication.processEvents()
        assert window.pages.currentWidget() is window.operation_settings, (
            f"按了 {step + 1} 次 Tab 就換頁了"
        )


def test_clicking_the_current_page_again_still_works(window) -> None:
    """點一列就是選那一頁，**不管它是不是已經是 current row**。

    修焦點問題時兩個清單都保有 current row，所以「點自己那一組裡 current 的那一列」
    不會觸發 `currentRowChanged`。少了 `itemClicked` 這條路，那一列會變成點不動的 ——
    而側邊欄裡不該有任何點不動的東西。
    """

    # 先讓「日常」那組的 current row 停在資產總覽，再切去設定那組。
    window.show_page(PageId.OVERVIEW)
    window.show_page(PageId.SYSTEM_SETTINGS)
    assert window.sidebar.daily.currentRow() == DAILY_PAGES.index(PageId.OVERVIEW)

    item = window.sidebar.item_for(PageId.OVERVIEW)
    assert item is not None
    window.sidebar.daily.itemClicked.emit(item)

    assert window.pages.currentWidget() is window.overview
    assert window.sidebar.current_page() is PageId.OVERVIEW


def test_settings_group_sits_at_the_bottom_of_the_rail(window, qtbot, tmp_path: Path) -> None:
    """設定要**沉底**，中間的留白會隨視窗長高。

    如果兩個清單都用預設的 Expanding size policy，它們會各分一半空間，
    設定那一組就浮在中間 —— 分組靠位置表達的做法也就失效了。
    """
    # 不用 `window` fixture：`resize()` 要在 `show()` 之前。
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


def test_pending_badge_is_drawn_beside_the_label_not_inside_it(window) -> None:
    """數字放在項目資料裡，**不寫進標籤文字**。

    舊做法是把文字改寫成「待確認（2）」，標籤長度會隨數字跳動 —— 而側邊欄的項目
    應該是固定不動的錨點。
    """

    item = window.sidebar.item_for(PageId.INBOX)
    assert item is not None
    assert item.text() == "待確認"
    assert item.data(BADGE_ROLE) is None

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
    assert controller.generate_deposit_events().success
    window.refresh_pending_badge()
    assert item.text() == "待確認"  # 文字不動
    assert item.data(BADGE_ROLE) == len(controller.list_inbox())


def test_main_window_applies_scoped_dark_theme(window) -> None:
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


def test_the_theme_is_only_applied_once_per_process(qtbot, tmp_path: Path) -> None:
    """第二個 `MainWindow` 不得再套一次全域主題。

    `setFont` / `setPalette` / `setStyleSheet` 是 **application 層級**的操作 —— Qt
    要把改變傳播給當下活著的每一個 widget。所以重複套用的成本隨 process 裡的 widget
    數量成長，而且比線性還快。2026-08-22 實測：活著 25 個視窗時，再建一個 `MainWindow`
    要 **49.7 秒**（沒有其他視窗時是 0.26 秒）。整包 UI 測試因此跑 32 分鐘。

    正式執行只開一個視窗，所以使用者看不到這件事 —— **這是測試才會爆炸的成本**，
    但它會讓每一次改動都變得昂貴，於是沒有人願意跑完整套件。

    這裡量的是「有沒有再套一次」而不是「花了多久」—— 時間會因機器而異，
    而語意不會。
    """
    app = QApplication.instance()
    assert app is not None

    # 兩個都要交給 qtbot 管。沒有 `addWidget` 的話 Python 一 GC 掉 MainWindow，
    # C++ 那邊就先沒了，而 `bind_selection` 掛在 model 上的 `sync` 還會再被叫一次
    # —— 直譯器關閉時噴 "Internal C++ object already deleted"。
    first = MainWindow(resolve_app_paths(tmp_path / "first"))
    qtbot.addWidget(first)

    calls: list[str] = []
    original = app.setStyleSheet
    app.setStyleSheet = lambda sheet: calls.append(sheet)  # type: ignore[method-assign]
    try:
        second = MainWindow(resolve_app_paths(tmp_path / "second"))
        qtbot.addWidget(second)
    finally:
        app.setStyleSheet = original  # type: ignore[method-assign]

    assert calls == [], (
        "第二個 MainWindow 又套了一次全域樣式表 —— "
        f"呼叫了 {len(calls)} 次。apply_dark_theme 的「只套一次」守門失效了。"
    )
    # 但主題**必須仍然在生效**，否則就只是把 bug 換成另一個 bug。
    assert colors.BG in app.styleSheet()


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


def test_the_app_opens_on_the_overview(window) -> None:
    """開啟程式停在資產總覽，而且它是側邊欄第一項。

    記帳是「我要做一件事」，總覽回答的是「我現在是什麼狀況」—— 打開程式的當下多半
    還沒決定要做什麼。真的要記帳，`Ctrl+N` 一鍵就到。
    """

    assert DAILY_PAGES[0] is PageId.OVERVIEW
    assert window.pages.currentWidget() is window.overview
    assert window.sidebar.current_page() is PageId.OVERVIEW
