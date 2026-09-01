"""記帳頁：三種流向、三種轉帳對象，以及日期欄與日曆彈窗。

日期欄那幾條守的是一個 Qt 與 QSS 的交互作用誤觸（`SC_ComboBoxFrame` 與
`SC_SpinBoxUp` 是同一個數字），細節見 `widgets/forms.py::date_field()`。
"""

from datetime import date, datetime

import pytest
from PySide6.QtCore import QDate, QPoint, Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QDateTimeEdit,
    QStyle,
    QStyleOptionViewItem,
    QTableView,
)

from tagcor_ledger.infrastructure.clock import TAIPEI
from tagcor_ledger.ui.navigation import PageId
from tagcor_ledger.ui.theme import apply_dark_theme
from tagcor_ledger.ui.widgets import forms
from tagcor_ledger.ui.widgets.forms import date_field, iso_from_date


def test_entry_page_switches_transfer_fields_and_saves(window) -> None:
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


def test_entry_page_hides_the_label_together_with_the_field(window) -> None:
    """QFormLayout 的標籤是獨立 widget，只藏欄位會留下孤兒標籤（2026-08-18 實機發現）。"""
    page = window.entry

    page.select_entry_type("expense")
    assert page.form.labelForField(page.destination).isHidden() is True
    assert page.form.labelForField(page.category).isHidden() is False
    assert page.form.labelForField(page.detail).isHidden() is False

    page.select_entry_type("transfer")
    assert page.form.labelForField(page.destination).isHidden() is False
    assert page.form.labelForField(page.category).isHidden() is True
    assert page.form.labelForField(page.detail).isHidden() is True


def test_the_entry_form_asks_in_the_order_the_user_fills_it(window) -> None:
    """欄位由上到下＝使用者實際填寫的順序：先決定這筆錢的身分，最後才打金額。

    **量的是 y 座標，不是 `addRow` 的呼叫順序。** 只在轉帳時出現的那兩列各自要貼著
    自己的第一層（轉帳對象接在流向後面、轉入帳戶接在帳戶後面），而那件事只有排出來
    的版面看得出來。金額靠**字重**當主角（`amountInput` 只留 `font-weight`），
    字級與高度與其他欄位一致 —— 強調的手段與位置是綁在一起的。
    """
    page = window.entry
    # **要先切到這一頁。** 落地頁是資產總覽，而 `QStackedWidget` 底下沒被選到的那幾頁
    # 在 offscreen 平台上版面根本不會跑 —— 每個欄位的 y 都是 0，斷言等於沒作用。
    window.show_page(PageId.ENTRY)

    page.select_entry_type("expense")
    QApplication.processEvents()
    fields = (
        page.account,
        page.category,
        page.detail,
        page.occurred_at,
        page.amount,
        page.description,
    )
    tops = [field.y() for field in fields]
    assert tops == sorted(tops), tops
    assert len(set(tops)) == len(tops), "有兩個欄位落在同一列，這條測試等於沒作用"

    # 轉帳時多出來的兩列插在對的位置：轉帳對象在帳戶之前、轉入帳戶在帳戶之後。
    page.select_entry_type("transfer")
    page.select_transfer_scope("internal")
    QApplication.processEvents()
    transfer_fields = (
        page.scope_row,
        page.account,
        page.destination,
        page.occurred_at,
        page.amount,
    )
    transfer_tops = [field.y() for field in transfer_fields]
    assert transfer_tops == sorted(transfer_tops), transfer_tops
    assert len(set(transfer_tops)) == len(transfer_tops)


def test_entry_page_reports_success_without_the_error_colour(window) -> None:
    """成功不能長得像失敗。

    舊版把「交易已儲存。」寫進紅色的 `errorLabel` —— 每天最常做的動作，回饋是紅的。
    現在用同一個標籤但帶 `state` 屬性，成功綠、失敗紅。
    """
    page = window.entry

    page.select_entry_type("expense")
    page.amount.setText("85")
    page.submit()
    assert page.status.text() == "交易已儲存。"
    assert page.status.property("state") == "ok"

    page.amount.setText("這不是金額")
    page.submit()
    assert page.status.property("state") == "error"


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


def test_lists_show_the_date_without_a_made_up_time(window) -> None:
    """時分秒是程式補的，印出來會讓人以為那是真的記錄時間。"""
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


@pytest.mark.geometry
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


@pytest.mark.geometry
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


def test_a_fresh_transfer_does_not_default_to_the_same_account(window) -> None:
    """剛開程式選「轉帳」按下儲存，**不該必定失敗**。

    兩個下拉填的是同一份清單、預設都停在第 0 項，所以以前一定會撞
    `TRANSFER_SAME_ACCOUNT` —— 一個照著做就一定失敗的預設值。
    """
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


def test_transfer_scope_switches_the_fields_and_the_account_label(window) -> None:
    """三種對象各自顯示對的欄位，而「帳戶」那一列要說出它現在問的是什麼。

    對外轉帳要類別／項目（它存成收入或支出），內部轉帳要轉入帳戶 —— 三種各不相同，
    而且**標籤要跟著欄位一起收**（`QFormLayout` 的標籤是獨立 widget）。
    """
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


def test_each_transfer_scope_saves_the_right_entry_type(window) -> None:
    """**資料庫只有一種轉帳。** 對外的兩種存成收入與支出，總資產才會跟著動。

    這是與 `state-machines.md`「利息記成收入，不是轉帳」同一個原則：
    錢有沒有離開你的總資產，才是收支與轉帳的分界。
    """
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
