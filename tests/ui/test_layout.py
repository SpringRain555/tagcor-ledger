"""版面規則：內容置中、寬度有上限、短表格不留接縫、視窗記得自己多大。

**這裡量的是實際的 geometry，不是設定值。** 「有沒有設 maximumWidth」跟「畫出來到底
多寬」是兩件事 —— 2026-08-20 就有一次靠讀設定值而漏掉版面沒生效的情況。
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import QApplication, QTableView, QTabWidget

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
    """兩者用同一個上限就是錯的：表單再寬只會讓標籤與欄位隔半個螢幕。"""
    window = _open(qtbot, tmp_path, size=(1920, 900))

    window.show_page(PageId.ENTRY)
    QApplication.processEvents()
    form_panel_widget = content_panel(window.quick)
    window.show_page(PageId.TRANSACTIONS)
    QApplication.processEvents()
    table_panel = content_panel(window.transactions)

    assert form_panel_widget is not None and table_panel is not None
    assert form_panel_widget.width() == FORM_WIDTH
    assert table_panel.width() > form_panel_widget.width() * 2


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

    for index in range(tabs.count()):
        tabs.setCurrentIndex(index)
        QApplication.processEvents()
        QApplication.processEvents()
        for table in tabs.widget(index).findChildren(QTableView):
            if not table.isVisible():
                continue
            header = table.horizontalHeader()
            columns = sum(header.sectionSize(i) for i in range(header.count()))
            assert table.width() >= columns, (tabs.tabText(index), table.width(), columns)
            assert not table.horizontalScrollBar().isVisible(), tabs.tabText(index)


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
