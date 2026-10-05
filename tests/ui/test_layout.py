"""版面規則：內容置中、寬度有上限、短表格不留接縫、視窗記得自己多大。

**這裡量的是實際的 geometry，不是設定值。** 「有沒有設 maximumWidth」跟「畫出來到底
多寬」是兩件事 —— 2026-08-20 就有一次靠讀設定值而漏掉版面沒生效的情況。

**整份標成 `geometry`，所以不在 Linux CI 跑。** 量出來的像素取決於字體與 Qt 平台
外掛，而這個專案是 Windows-first —— 在 Linux 上驗版面，驗到的不是使用者會看到的
東西，而失敗訊息會指向錯的方向。這幾條由本機的 `.\\tools\\Verify.ps1 -Ui` 負責。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QScrollArea, QTableView, QTabWidget, QWidget

from tagcor_ledger.app import window_state

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.ui.main_window import MainWindow
from tagcor_ledger.ui.navigation import PageId
from tagcor_ledger.ui.widgets import sidebar as sidebar_module
from tagcor_ledger.ui.widgets.table import RowsModel, setup_table
from tagcor_ledger.ui.widgets.layout import (
    ENTRY_PAGE_MARGINS,
    ENTRY_WIDTH,
    PAGE_MARGINS,
    TABLE_WIDTH,
    content_panel,
)

# 這個 App 必須裝得進的螢幕。實測（2026-08-20）：offscreen 912×800、windows 904×829。
#
# 這條守門攔的是**結構性**的退步 —— 多一排按鈕、多一列表單。實測過：把備份頁的六顆
# 按鈕擠回一行，最小寬度就跳到 1120 而失敗。
#
# 它攔不到純粹因為字變寬造成的增加：測試跑在 offscreen，中文是 fallback 字型，
# 寬度比實機窄。所以餘裕看起來比實際多，不要拿它當「還可以再加東西」的依據。
SCREEN_BUDGET = (1024, 880)
PAGE_BUDGET = (SCREEN_BUDGET[0] - sidebar_module.COMPACT_WIDTH, SCREEN_BUDGET[1])
"""一頁在 `SCREEN_BUDGET` 的螢幕上、扣掉側邊欄之後能用的空間。"""

pytestmark = pytest.mark.geometry


# 這個檔案不用 `window` fixture：版面測試要在 `show()` **之前** `resize()`，
# 而視窗一旦顯示過再改大小，量到的是動畫中途的尺寸。
def _open(qtbot, tmp_path: Path, *, size: tuple[int, int] = (1440, 900)) -> MainWindow:
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.resize(*size)
    window.show()
    qtbot.waitExposed(window)
    return window


def _relayout(window: MainWindow, width: int, height: int = 900) -> None:
    window.resize(width, height)
    QApplication.processEvents()


def test_page_content_is_capped_and_centred(qtbot, tmp_path: Path) -> None:
    """寬度 = min(可用寬度, 該頁上限)，而且置中。

    記帳頁原本是靠左貼著側邊欄，1920 px 下右邊約 1000 px 全是空的。
    """
    window = _open(qtbot, tmp_path)

    for window_width, page, cap, margins in (
        (1920, PageId.ENTRY, ENTRY_WIDTH, ENTRY_PAGE_MARGINS),
        (1920, PageId.TRANSACTIONS, TABLE_WIDTH, PAGE_MARGINS),
        (1100, PageId.TRANSACTIONS, TABLE_WIDTH, PAGE_MARGINS),
    ):
        _relayout(window, window_width)
        window.show_page(page)
        QApplication.processEvents()

        surface = window._page_widgets[page]
        panel = content_panel(surface)
        assert panel is not None
        available = surface.width() - margins[0] - margins[2]
        assert panel.width() == min(available, cap), (page, window_width)

        expected_left = margins[0] + (available - panel.width()) // 2
        assert abs(panel.x() - expected_left) <= 1, (page, window_width)


def test_entry_form_is_much_narrower_than_the_transactions_table(qtbot, tmp_path: Path) -> None:
    """兩者用同一個上限就是錯的：表單再寬只會讓標籤與欄位隔半個螢幕。

    **不要求視窗真的有 1920 px 寬。** 第一版斷言「表格面板寬度 > 表單的兩倍」，
    那需要視窗管理員真的給到 1672 px —— 而在整包跑的時候 Qt 會把視窗往右下疊放，
    Windows 於是把寬度夾掉，同一條測試單獨跑會過、整包跑會紅（2026-08-20）。

    改成量真正的規則：表單**停在**自己的上限，表格**吃滿**可用寬度。
    兩個上限差多少是常數的事，另外比一次就好。
    """
    window = _open(qtbot, tmp_path, size=(1920, 900))

    window.show_page(PageId.ENTRY)
    QApplication.processEvents()
    form_panel_widget = content_panel(window.entry)
    window.show_page(PageId.TRANSACTIONS)
    QApplication.processEvents()
    table_panel = content_panel(window.transactions)

    assert form_panel_widget is not None and table_panel is not None
    available = window.transactions.width() - PAGE_MARGINS[0] - PAGE_MARGINS[2]
    assert available > ENTRY_WIDTH, "視窗窄到連表單上限都放不下，這條測試等於沒作用"
    assert form_panel_widget.width() == ENTRY_WIDTH
    assert table_panel.width() == min(available, TABLE_WIDTH)
    # 2026-09-27 從「兩倍」放到 1.5 倍：記帳表單的標籤改成靠右貼著欄位之後，
    # 表單變寬不再讓標籤與欄位隔半個螢幕，720 → 880 是為了填滿預設視窗的內容區。
    assert TABLE_WIDTH > ENTRY_WIDTH * 1.5


def test_short_tables_stop_at_their_columns(qtbot, tmp_path: Path) -> None:
    """欄位少的表收到欄寬總和。

    拉滿整個視窗時，表頭只畫到最後一欄就結束，右邊留下一大塊有框線卻沒有表頭的
    空白 —— 實機截圖上那條接縫就是這樣來的。
    """
    window = _open(qtbot, tmp_path, size=(1600, 900))
    window.show_page(PageId.OPERATION_SETTINGS)
    QApplication.processEvents()

    table = window.operation_settings.accounts.table
    header = table.horizontalHeader()
    columns = sum(header.sectionSize(index) for index in range(header.count()))

    assert columns > 0
    assert table.width() <= columns + 2 * table.frameWidth()
    # 而且明顯沒有拉滿 —— 不然這條測試等於沒作用。
    assert table.width() < window.operation_settings.width() - 300


def test_fit_content_measures_the_data_not_the_empty_table(qtbot) -> None:
    """收寬必須在**資料進去之後**重量一次。

    這是那個 bug 的最小重現：`setup_table` 跑的時候 model 還是空的，若當下量到的寬度
    就定案，之後塞進再寬的資料也不會放寬 —— 欄位就被切掉。

    用長 ASCII 字串是刻意的：測試跑在 offscreen，中文走 fallback 字型，寬度跟實機
    對不起來；ASCII 兩邊都量得準，這條測試才不會因為換平台就失效。
    """
    table = QTableView()
    qtbot.addWidget(table)
    model = RowsModel(["A", "B"], lambda item: [str(item["a"]), str(item["b"])])
    setup_table(table, model, fit_content=True)
    empty_width = table.maximumWidth()

    model.replace_rows([{"a": "X" * 60, "b": "Y" * 60}])
    header = table.horizontalHeader()
    needed = sum(
        max(table.sizeHintForColumn(index), header.sectionSizeHint(index))
        for index in range(header.count())
    )

    assert needed > empty_width, "測試資料不夠寬，這條測試等於沒作用"
    assert table.maximumWidth() >= needed


def test_shrink_wrapped_tables_are_never_clipped(qtbot, tmp_path: Path) -> None:
    """收寬不可以收過頭。

    第一版拿 `sectionSize` 當依據，而 `ResizeToContents` 的欄寬是版面階段才算的 ——
    量到的是空 model 時的舊值，於是帳戶表被夾成 187 px（欄寬其實要 311），
    「狀態」欄整個看不到，底下還冒出一條橫向捲軸。**這是收寬做壞的樣子。**
    """
    window = _open(qtbot, tmp_path, size=(1600, 900))
    controller = window.controller
    # 期初餘額只需要「夠長」——欄寬才會被撐開。用一眼看得出是編造的值，
    # 免得以後有人（或稽核）停下來確認這是不是誰的真實餘額。
    controller.create_account("郵局活儲", "1234567")
    controller.create_category("交通")
    window.operation_settings.refresh()

    window.show_page(PageId.OPERATION_SETTINGS)
    tabs = window.operation_settings.findChild(QTabWidget, "settingsTabs")
    assert tabs is not None

    checked = 0
    for index in range(tabs.count()):
        tabs.setCurrentIndex(index)
        QApplication.processEvents()
        QApplication.processEvents()
        for table in tabs.widget(index).findChildren(QTableView):
            # **不要用 `isVisible()` 過濾。** `QStackedWidget` 底下的頁在 offscreen
            # 平台上永遠回報 False，於是這一圈什麼都不檢查就通過 —— 2026-08-20 加
            # 分頁時才發現這條守門一直是空的。版面已經算好了，量 geometry 就對。
            header = table.horizontalHeader()
            columns = sum(header.sectionSize(i) for i in range(header.count()))
            assert table.width() >= columns, (tabs.tabText(index), table.width(), columns)
            checked += 1
    assert checked >= tabs.count(), f"只檢查了 {checked} 張表，過濾條件把它們濾光了"


def test_tables_are_not_clipped_on_a_brand_new_ledger(qtbot, tmp_path: Path) -> None:
    """**開程式之後什麼都不做**，表格就不能是切掉的。

    上面那條守門在量之前先建了帳戶與類別、又呼叫了一次 `refresh()` —— 那會多發一次
    `modelReset`，而那一次的重算是對的。所以它只證明了「刷新過的表格沒問題」。

    真正壞掉的是**第一次**：`fit_to_contents` 在 `setup_table` 當下就跑，而那時候
    `apply_dark_theme()` 還沒把 12pt 中文字體套上去。量到的是預設字體下的寬度
    （帳戶表 187 px），套上字體之後欄位需要 279 px，於是「目前餘額（TWD）」被切掉、
    底下冒出一條橫向捲軸。實機截圖上看得一清二楚，而整包測試是綠的。
    """
    window = _open(qtbot, tmp_path, size=(1600, 900))
    window.show_page(PageId.OPERATION_SETTINGS)
    QApplication.processEvents()

    tabs = window.operation_settings.findChild(QTabWidget, "settingsTabs")
    assert tabs is not None

    checked = 0
    for index in range(tabs.count()):
        tabs.setCurrentIndex(index)
        QApplication.processEvents()
        for table in tabs.widget(index).findChildren(QTableView):
            header = table.horizontalHeader()
            columns = sum(header.sectionSize(i) for i in range(header.count()))
            assert table.width() >= columns, (
                f"「{tabs.tabText(index)}」分頁的表格只有 {table.width()} px，"
                f"欄位需要 {columns} px —— 表頭會被切掉"
            )
            assert not table.horizontalScrollBar().isVisible(), (
                f"「{tabs.tabText(index)}」分頁的表格冒出了橫向捲軸"
            )
            checked += 1
    assert checked >= tabs.count(), f"只檢查了 {checked} 張表"


def test_a_long_item_name_never_makes_the_table_scroll_sideways(qtbot, tmp_path: Path) -> None:
    """一個很長的項目名稱不可以讓表格長出橫向捲軸。

    上面那兩條掃描全分頁的守門用的是**短名稱**（「郵局活儲」「交通」），所以它們
    證明不了這件事：`fit_to_contents` 設的是 `setMaximumWidth`，那是上限不是保證 ——
    名稱長到 `ResizeToContents` 算出來的欄寬總和超過分頁能給的寬度時，欄位照樣溢出。

    而這些表是**固定高度**（`fit_rows`），橫向捲軸會從那個高度裡扣掉自己的厚度，
    最後一列因此被切掉，看起來像資料沒載完。所以那條捲軸不只是難看。

    名稱用 ASCII 是刻意的（同 `test_fit_content_measures_the_data_not_the_empty_table`）：
    測試跑在 offscreen，中文走 fallback 字型，寬度跟實機對不起來。
    """
    window = _open(qtbot, tmp_path, size=(1600, 900))
    controller = window.controller
    assert controller.create_category("交通").success
    parent_id = str(controller.category_options()[0]["category_id"])
    assert controller.create_category("X" * 300, parent_id).success
    window.operation_settings.refresh()

    window.show_page(PageId.OPERATION_SETTINGS)
    tabs = window.operation_settings.findChild(QTabWidget, "settingsTabs")
    assert tabs is not None
    # 2026-10-05 起項目在「類別與項目」分頁的右半邊 —— 跟類別並排，能給它的寬度更少了。
    items_tab = [tabs.tabText(i) for i in range(tabs.count())].index("類別與項目")
    tabs.setCurrentIndex(items_tab)
    QApplication.processEvents()
    QApplication.processEvents()

    table = window.operation_settings.items.table
    header = table.horizontalHeader()
    # 陽性對照：這個名字確實比整張表能給的還寬，否則這條測試等於沒作用。
    assert table.sizeHintForColumn(1) > table.width(), (
        f"「項目」欄的內容只要 {table.sizeHintForColumn(1)} px，表格有 {table.width()} px"
        " —— 名字不夠長，撐不破可用寬度"
    )
    columns = sum(header.sectionSize(i) for i in range(header.count()))
    assert columns <= table.viewport().width(), (columns, table.viewport().width())
    assert not table.horizontalScrollBar().isVisible(), "長項目名稱又讓表格長出橫向捲軸"


def test_long_tables_still_fill_the_width(qtbot, tmp_path: Path) -> None:
    """交易紀錄有七欄，寬度是真的有用 —— 它**不該**被收窄。"""
    window = _open(qtbot, tmp_path, size=(1600, 900))
    window.show_page(PageId.TRANSACTIONS)
    QApplication.processEvents()

    panel = content_panel(window.transactions)
    assert panel is not None
    assert window.transactions.table.width() == panel.width()


def test_sidebar_narrows_on_a_small_window(qtbot, tmp_path: Path) -> None:
    window = _open(qtbot, tmp_path, size=(1440, 900))
    assert window.sidebar.width() == sidebar_module.WIDTH

    _relayout(window, sidebar_module.COMPACT_BREAKPOINT - 100)
    assert window.sidebar.width() == sidebar_module.COMPACT_WIDTH

    _relayout(window, 1440)
    assert window.sidebar.width() == sidebar_module.WIDTH


def test_the_minimum_width_does_not_depend_on_where_the_project_lives(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    """法規庫不存在時，那一頁會顯示「預期位置」—— 而它**不可以**是完整絕對路徑。

    Windows 路徑沒有空格，`setWordWrap(True)` 找不到斷點，Qt 就把整條路徑當成一個
    不可斷的詞，於是視窗的 `minimumSizeHint()` 直接等於它的像素寬度。**專案裝得
    越深，視窗最小寬度就越寬** —— 而法規庫是產生物、不進版控，所以每一份全新
    clone 都走這條路徑。

    2026-09-01 實測：專案在 `D:\\Projects\\tagcor-ledger` 時是 1024（剛好卡在
    `SCREEN_BUDGET` 上限，所以作者自己看不到問題），clone 到 140 字元的深層路徑
    就變成 1256。
    """
    deep = tmp_path / ("very-long-directory-name-" * 6) / "reference.sqlite3"
    monkeypatch.setenv("TAGCOR_REFERENCE_DB", str(deep))
    assert not deep.exists(), "這條測試要的正是「檔案不存在」那個分支"

    window = _open(qtbot, tmp_path)
    hint = window.reference.minimumSizeHint()
    assert (hint.width(), hint.height()) <= PAGE_BUDGET, (
        f"法規庫路徑長度洩漏到版面上了：最小尺寸 {hint.width()}×{hint.height()}，"
        f"而那條路徑有 {len(str(deep))} 個字元。完整路徑要放 tooltip，不是標籤本文。"
    )


def test_every_page_fits_a_small_screen_without_scrolling(qtbot, tmp_path: Path) -> None:
    """每一頁的自然最小尺寸必須裝得進 `PAGE_BUDGET`。

    2026-09-27 之前量的是整個視窗的 `minimumSizeHint()`。現在每一頁包在自己的捲動區裡，
    視窗的最小尺寸永遠很小，那樣量會永遠通過 —— 所以改量**頁面本身**：在一般的小螢幕上
    它仍然不該需要捲動，多了一排按鈕或一個不會換行的長標籤照樣會被攔下來。
    """
    window = _open(qtbot, tmp_path)
    for page, widget in window._page_widgets.items():
        hint = widget.minimumSizeHint()
        assert (hint.width(), hint.height()) <= PAGE_BUDGET, (
            f"{page} 的最小尺寸 {hint.width()}×{hint.height()} 超過預算 "
            f"{PAGE_BUDGET[0]}×{PAGE_BUDGET[1]}；"
            "通常是某一頁多了一排按鈕或一個不會換行的長標籤。"
        )


def test_the_window_can_shrink_to_phone_width(qtbot, tmp_path: Path) -> None:
    """下限寫死在 `window_state`，而且真的拖得到那麼小。"""
    window = _open(qtbot, tmp_path)
    assert (window.minimumWidth(), window.minimumHeight()) == (
        window_state.MINIMUM_WIDTH,
        window_state.MINIMUM_HEIGHT,
    )
    assert window.minimumSizeHint().width() <= window_state.MINIMUM_WIDTH, (
        "內容的最小寬度比下限還寬 —— 某個東西沒有包進捲動區"
    )


def test_a_narrow_window_swaps_the_sidebar_for_a_page_menu(qtbot, tmp_path: Path) -> None:
    """窄視窗：側邊欄收起、頂端選單出現，選單換頁跟側邊欄是同一件事；拉寬後復原。"""
    window = _open(qtbot, tmp_path, size=(1280, 800))
    assert not window.is_narrow()
    assert not window.sidebar.isHidden() and window.narrow_nav.isHidden()

    _relayout(window, 390, 800)
    assert window.is_narrow()
    assert window.sidebar.isHidden() and not window.narrow_nav.isHidden()

    window._page_actions[PageId.ENTRY].trigger()
    QApplication.processEvents()
    assert window.current_page_widget() is window.entry
    assert window.sidebar.current_page() is PageId.ENTRY, "選單換頁要讓側邊欄的正本跟著變"
    assert "記帳" in window.page_menu_button.text()

    _relayout(window, 1280, 800)
    assert not window.is_narrow()
    assert not window.sidebar.isHidden() and window.narrow_nav.isHidden()
    assert window.current_page_widget() is window.entry


def test_the_entry_page_fits_phone_width_without_sideways_scrolling(
    qtbot, tmp_path: Path
) -> None:
    """記帳是每天最常用的一頁，手機寬度下不可以橫向捲動 —— 表格頁可以，這頁不行。

    **轉帳要一起量**：三顆轉帳對象按鈕並排要四百多 px，是這頁最寬的一列。
    """
    window = _open(qtbot, tmp_path, size=(window_state.MINIMUM_WIDTH, 800))
    window.show_page(PageId.ENTRY)
    for entry_type in ("expense", "transfer"):
        window.entry.select_entry_type(entry_type)
        QApplication.processEvents()
        scroll = window.pages.currentWidget()
        assert isinstance(scroll, QScrollArea)
        assert window.entry.is_wrapped(), "窄版面的標籤應該在欄位上方"
        assert window.entry.width() <= scroll.viewport().width(), (
            f"{entry_type}：記帳頁 {window.entry.width()} px 比可視範圍 "
            f"{scroll.viewport().width()} px 寬，會橫向捲動"
        )

    _relayout(window, 1280, 800)
    assert not window.entry.is_wrapped()


def test_every_launch_opens_at_the_default_size(qtbot, tmp_path: Path) -> None:
    """每次啟動都是預設大小，**不管上次多大、也不管舊版留下的 window.json**。

    2026-09-27 使用者指定。以前會還原上次的大小與位置；現在那個檔案不讀也不寫。
    """
    paths = resolve_app_paths(tmp_path / "ledger-data")
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    leftover = paths.config_dir / "window.json"
    leftover.write_text(
        json.dumps({"x": 40, "y": 60, "width": 1500, "height": 870}), encoding="utf-8"
    )

    window = MainWindow(paths)
    qtbot.addWidget(window)
    screen = QApplication.primaryScreen().availableGeometry()
    expected = (
        min(window_state.DEFAULT_WIDTH, screen.width()),
        min(window_state.DEFAULT_HEIGHT, screen.height()),
    )
    assert (window.width(), window.height()) == expected

    window.resize(900, 600)
    window.close()
    assert json.loads(leftover.read_text(encoding="utf-8"))["width"] == 1500, (
        "關閉時不該再寫 window.json"
    )


def test_the_summary_table_stops_at_its_last_row(qtbot, tmp_path: Path) -> None:
    """資產總覽的帳戶表**高度**也要收到列數。

    收寬解決了右邊那條接縫，但下面還有一條一樣的：三列資料底下留著一大片有框線卻沒有
    內容的空白，看起來像資料還沒載完。2026-08-20 實機截圖上就是那個樣子。
    """
    window = _open(qtbot, tmp_path, size=(1600, 900))
    controller = window.controller
    assert controller.create_account("郵局活儲", "1000").success
    window.show_page(PageId.OVERVIEW)
    QApplication.processEvents()

    table = window.overview.table
    model = table.model()
    assert model is not None and model.rowCount() >= 2, "資料不夠，這條測試等於沒作用"
    expected = (
        table.horizontalHeader().sizeHint().height()
        + model.rowCount() * table.verticalHeader().defaultSectionSize()
        + 2 * table.frameWidth()
    )
    assert table.height() == expected, (table.height(), expected)
    # 陽性對照：頁面本身確實高得多，所以「收到列數」是真的有在收。
    assert table.height() < window.overview.height() - 300


def test_todo_lines_do_not_wrap_while_there_is_room_to_spare(qtbot, tmp_path: Path) -> None:
    """待辦那一行不可以在還有大片空白時就斷行。

    旁邊有 stretch 時，QLabel 拿到的是它的 `sizeHint` 寬度，而**會換行的** QLabel 的
    sizeHint 是一個「大致方形」的啟發值 —— 於是「今天還沒記錄「現金」的目前金額。」
    在右邊還有 700 px 空白的情況下斷成兩行（2026-08-20 實機截圖）。

    **只量得到 `inbox_note`。** 同一列的另一個是 `gap_note`，而它只在有未解釋差額
    的時候才顯示 —— 這個 fixture 是全新的帳本，一次都還沒盤點。兩者走的是同一個
    `_action_row()`，所以量一個就守得住那個陷阱；`gap_note` 的顯示條件在
    `tests/ui/test_overview_page.py`。
    """
    window = _open(qtbot, tmp_path, size=(1600, 900))
    window.show_page(PageId.OVERVIEW)
    QApplication.processEvents()

    page = window.overview
    for label in (page.inbox_note,):
        assert label.isVisible(), label.text()
        assert label.text(), "標籤是空的，這條測試等於沒作用"
        # **量的是配到的寬度，不是 widget 的高度。** 這一列的高度是旁邊那顆按鈕決定的，
        # 標籤在垂直方向被拉滿，所以高度看不出有沒有斷行。
        needed = label.fontMetrics().horizontalAdvance(label.text())
        assert label.width() >= needed, (label.text(), label.width(), needed)


def test_settings_tabs_keep_their_content_at_the_top(qtbot, tmp_path: Path) -> None:
    """操作設定每一個分頁的內容都貼著上緣，不會散開撐滿整頁。

    表格改成固定高度（`fit_rows`）之後，`QVBoxLayout` 會把多出來的高度**平均塞進
    每個 widget 之間** —— 按鈕列跑到分頁中間、表格浮在下面，中間一大片空白
    （2026-08-20 實機截圖）。每個分頁最後都要有一個 `addStretch()` 吃掉那段高度。
    """
    window = _open(qtbot, tmp_path, size=(1600, 900))
    window.show_page(PageId.OPERATION_SETTINGS)
    tabs = window.operation_settings.findChild(QTabWidget, "settingsTabs")
    assert tabs is not None

    for index in range(tabs.count()):
        tabs.setCurrentIndex(index)
        QApplication.processEvents()
        QApplication.processEvents()
        page = tabs.widget(index)
        # 直接子 widget 的 geometry。**不用 `isVisible()` 過濾** —— `QStackedWidget`
        # 底下的頁在 offscreen 平台上永遠回報 False，過濾完會一個都不剩。
        children = [
            child for child in page.findChildren(QWidget) if child.parent() is page
        ]
        assert children, tabs.tabText(index)
        label = tabs.tabText(index)
        assert min(child.y() for child in children) < 40, (
            f"{label}：內容從 y={min(child.y() for child in children)} 才開始，沒有貼著上緣"
        )

        # **量的是元件之間的空隙，不是內容總高度。** 定存分頁本來就有兩張表與四個
        # 標題，內容佔掉大半個分頁是正常的；被 layout 撐開的樣子是「每個元件之間
        # 都多出一大段」。同一列的按鈕 y 範圍互相重疊，算出來是負的，不影響。
        bands = sorted((child.y(), child.y() + child.height()) for child in children)
        reach = bands[0][1]
        worst = 0
        for band_top, band_bottom in bands[1:]:
            worst = max(worst, band_top - reach)
            reach = max(reach, band_bottom)
        assert worst < 40, f"{label}：元件之間空出 {worst} px，多半是少了 addStretch()"
