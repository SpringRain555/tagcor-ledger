"""版面規則：內容置中、寬度有上限、短表格不留接縫、視窗記得自己多大。

**這裡量的是實際的 geometry，不是設定值。** 「有沒有設 maximumWidth」跟「畫出來到底
多寬」是兩件事 —— 2026-08-20 就有一次靠讀設定值而漏掉版面沒生效的情況。
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import QApplication, QTableView, QTabWidget, QWidget

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.app.window_state import (
    WindowGeometry,
    load_geometry,
    save_geometry,
    state_path,
)
from tagcor_ledger.ui.main_window import MainWindow
from tagcor_ledger.ui.navigation import PageId
from tagcor_ledger.ui.widgets import sidebar as sidebar_module
from tagcor_ledger.ui.widgets.table import RowsModel, setup_table
from tagcor_ledger.ui.widgets.layout import (
    FORM_WIDTH,
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
    horizontal_margins = PAGE_MARGINS[0] + PAGE_MARGINS[2]

    for window_width, page, cap in (
        (1920, PageId.ENTRY, FORM_WIDTH),
        (1920, PageId.TRANSACTIONS, TABLE_WIDTH),
        (1100, PageId.TRANSACTIONS, TABLE_WIDTH),
    ):
        _relayout(window, window_width)
        window.show_page(page)
        QApplication.processEvents()

        surface = window._page_widgets[page]
        panel = content_panel(surface)
        assert panel is not None
        available = surface.width() - horizontal_margins
        assert panel.width() == min(available, cap), (page, window_width)

        expected_left = PAGE_MARGINS[0] + (available - panel.width()) // 2
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
    horizontal_margins = PAGE_MARGINS[0] + PAGE_MARGINS[2]

    window.show_page(PageId.ENTRY)
    QApplication.processEvents()
    form_panel_widget = content_panel(window.quick)
    window.show_page(PageId.TRANSACTIONS)
    QApplication.processEvents()
    table_panel = content_panel(window.transactions)

    assert form_panel_widget is not None and table_panel is not None
    available = window.transactions.width() - horizontal_margins
    assert available > FORM_WIDTH, "視窗窄到連表單上限都放不下，這條測試等於沒作用"
    assert form_panel_widget.width() == FORM_WIDTH
    assert table_panel.width() == min(available, TABLE_WIDTH)
    assert TABLE_WIDTH > FORM_WIDTH * 2


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
    controller.create_account("郵局活儲", "1102410")
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


def test_the_whole_app_fits_a_small_screen(qtbot, tmp_path: Path) -> None:
    """視窗的自然最小尺寸必須裝得進 `SCREEN_BUDGET`。

    **不寫死 `setMinimumSize`。** 硬設一個比內容還小的下限只會讓版面被擠爛；
    正確的做法是讓內容決定下限，然後守住那個下限不要失控。
    """
    window = _open(qtbot, tmp_path)
    hint = window.minimumSizeHint()
    assert (hint.width(), hint.height()) <= SCREEN_BUDGET, (
        f"視窗最小尺寸 {hint.width()}×{hint.height()} 超過預算 "
        f"{SCREEN_BUDGET[0]}×{SCREEN_BUDGET[1]}；"
        "通常是某一頁多了一排按鈕或一個不會換行的長標籤。"
    )


def test_window_size_survives_a_restart(qtbot, tmp_path: Path) -> None:
    """關掉再開要回到同樣大小。以前每次開都是 1280×760。"""
    data_dir = tmp_path / "ledger-data"
    window = _open(qtbot, tmp_path, size=(1500, 870))
    window.close()

    reopened = MainWindow(resolve_app_paths(data_dir))
    qtbot.addWidget(reopened)
    reopened.show()
    qtbot.waitExposed(reopened)
    assert (reopened.width(), reopened.height()) == (1500, 870)


def test_a_broken_window_state_file_does_not_break_startup(qtbot, tmp_path: Path) -> None:
    """這個檔案壞掉只該讓視窗回到預設大小，不該讓程式開不起來。"""
    paths = resolve_app_paths(tmp_path / "ledger-data")
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    state_path(paths.config_dir).write_text("{ 這不是 JSON", encoding="utf-8")

    window = MainWindow(paths)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    assert window.width() > 0


def test_window_state_rejects_values_that_make_no_sense(tmp_path: Path) -> None:
    """負數、比最小尺寸還小、離螢幕十萬八千里的座標，一律當成沒設定過。"""
    config = tmp_path / "config"
    config.mkdir()

    save_geometry(config, WindowGeometry(x=40, y=60, width=1400, height=820))
    restored = load_geometry(config)
    assert restored == WindowGeometry(x=40, y=60, width=1400, height=820)

    for bad in (
        {"x": 0, "y": 0, "width": 200, "height": 800},
        {"x": 0, "y": 0, "width": 1400, "height": 100},
        {"x": 999_999, "y": 0, "width": 1400, "height": 820},
        {"x": 0, "y": 0, "width": "寬", "height": 820},
        {"x": 0, "y": 0},
        [1, 2, 3],
    ):
        state_path(config).write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        assert load_geometry(config) is None, bad


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
    """待辦那兩行不可以在還有大片空白時就斷行。

    旁邊有 stretch 時，QLabel 拿到的是它的 `sizeHint` 寬度，而**會換行的** QLabel 的
    sizeHint 是一個「大致方形」的啟發值 —— 於是「今天還沒記錄「現金」的目前金額。」
    在右邊還有 700 px 空白的情況下斷成兩行（2026-08-20 實機截圖）。
    """
    window = _open(qtbot, tmp_path, size=(1600, 900))
    window.show_page(PageId.OVERVIEW)
    QApplication.processEvents()

    page = window.overview
    for label in (page.inbox_note, page.snapshot_note):
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
