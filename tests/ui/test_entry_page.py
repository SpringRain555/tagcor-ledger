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
    QLabel,
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

    順序是 帳戶 → 日期 → 類別 → 項目 → 金額 → 備註（2026-09-27 起日期緊跟帳戶）。

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
        page.occurred_at,
        page.category,
        page.detail,
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


def test_switching_flow_never_moves_the_fields_that_stay(window) -> None:
    """切流向時，留著的欄位**一格都不動**。

    2026-09-27 使用者回報「支出跟收入欄位一樣，位置卻不一致」。三個原因：
    1. 列距隨視窗高度重算，切到轉帳多一列就變小，每個欄位都跟著跳；
    2. 標籤欄寬度＝看得到的最寬標籤，轉帳多了四個字的標籤，所有欄位往右跳；
    3. 分段按鈕比下拉高 4 px，「轉帳對象」換掉一列下拉，底下就往下跳 4 px。

    支出、收入、轉帳・我的帳戶之間都是七列，所以金額、備註、儲存鈕的 y 要完全一樣；
    x 則是四種情形都一樣。
    """
    page = window.entry
    window.show_page(PageId.ENTRY)
    fields = (page.account, page.occurred_at, page.amount, page.description, page.save_button)

    def positions(entry_type: str, scope: str = "internal") -> list[tuple[int, int]]:
        page.select_entry_type(entry_type)
        page.select_transfer_scope(scope)
        QApplication.processEvents()
        return [(field.x(), field.y()) for field in fields]

    expense = positions("expense")
    assert positions("income") == expense
    internal = positions("transfer", "internal")
    assert internal[2:] == expense[2:], "我的帳戶之間也是七列，金額以下不該移動"
    inbound = positions("transfer", "inbound")
    xs = {x for x, _ in expense + internal + inbound}
    assert len(xs) == 1, f"欄位左緣在切流向時橫移了：{sorted(xs)}"
    assert positions("expense") == expense


def test_labels_hug_their_fields(window) -> None:
    """標籤的**字**貼著欄位左緣，不是只有標籤那個 widget 貼著。

    標籤欄為了切流向不橫移而撐成同寬（`_pin_label_column()`），之後 `setLabelAlignment`
    只管得到 widget 放哪，字預設靠左 ——「流向」兩個字就又離欄位一大段
    （2026-09-27 截圖看到的）。量的是字的右緣，不是 widget 的右緣。
    """
    page = window.entry
    window.show_page(PageId.ENTRY)
    page.select_entry_type("expense")
    QApplication.processEvents()
    for field in (page.account, page.amount):
        label = page.form.labelForField(field)
        assert isinstance(label, QLabel)
        text_right = label.x() + label.contentsRect().right() - (
            label.contentsRect().width() - label.fontMetrics().horizontalAdvance(label.text())
        ) * (0 if label.alignment() & Qt.AlignmentFlag.AlignRight else 1)
        gap = field.x() - text_right
        assert gap <= page.form.horizontalSpacing() + 2, (
            f"「{label.text()}」的字離欄位 {gap} px"
        )


def test_the_message_sits_beside_the_clear_button(window) -> None:
    """訊息在「清空」右邊，不是備註與按鈕之間獨立的一列。

    獨立一列時沒有訊息也佔一列加兩段間距，備註與按鈕之間空一大塊（2026-09-27 使用者回報）。
    """
    page = window.entry
    window.show_page(PageId.ENTRY)
    page.select_entry_type("expense")
    page.amount.setText("85")
    page.submit()
    QApplication.processEvents()

    assert page.status.text() == "交易已儲存。"
    assert page.status.x() > page.clear_button.x() + page.clear_button.width()
    gap = page.save_button.y() - (page.description.y() + page.description.height())
    assert gap == page.form.verticalSpacing(), (
        f"備註與按鈕之間空了 {gap} px，比列距 {page.form.verticalSpacing()} 多"
    )


def test_the_currency_is_a_hint_inside_the_amount_field(window) -> None:
    """「TWD」在金額框內右緣當背景提示，標籤只寫「金額」；打的字不會跑到它底下。"""
    page = window.entry
    window.show_page(PageId.ENTRY)
    QApplication.processEvents()

    label = page.form.labelForField(page.amount)
    assert isinstance(label, QLabel) and label.text() == "金額"
    suffix = page.amount.findChild(QLabel, "inputSuffix")
    assert suffix is not None and suffix.text() == "TWD"
    right_gap = page.amount.width() - (suffix.x() + suffix.width())
    assert 0 < right_gap <= 16, f"TWD 沒有貼在右緣（離右邊 {right_gap} px）"
    assert page.amount.textMargins().right() >= suffix.width(), "打的數字會跑到 TWD 底下"


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


def test_the_saved_message_clears_itself_after_three_seconds(window, qtbot) -> None:
    """「交易已儲存。」三秒後自己消失。

    留著不動的話，填第二筆時畫面上還寫著「交易已儲存」—— 而那句講的是上一筆，
    使用者分不出眼前這筆存了沒。

    **不在計時中改 interval**：Qt 對「執行中的 timer 被改 interval」的行為版本間
    不一致，所以先把 interval 縮短、再送出，走的仍然是 `submit()` 啟動計時器的真實路徑。
    """
    from tagcor_ledger.ui.pages import entry as entry_module

    page = window.entry
    timer = page.saved_message_timer
    assert timer.interval() == entry_module.SAVED_MESSAGE_MS == 3000
    assert not timer.isActive(), "還沒存過任何東西，計時器不該在跑"
    timer.setInterval(50)

    page.select_entry_type("expense")
    page.amount.setText("85")
    page.submit()
    assert page.status.text() == "交易已儲存。"
    assert timer.isActive(), "成功之後計時器要開始跑"
    qtbot.waitUntil(lambda: page.status.text() == "", timeout=2000)


def test_a_failure_right_after_a_success_is_not_wiped_by_the_timer(window, qtbot) -> None:
    """成功後三秒內接著失敗，失敗訊息要留著 —— 那是要讀完的。"""
    page = window.entry
    timer = page.saved_message_timer
    timer.setInterval(50)

    page.select_entry_type("expense")
    page.amount.setText("85")
    page.submit()
    assert timer.isActive()

    page.amount.setText("這不是金額")
    page.submit()
    assert not timer.isActive(), "失敗要把上一筆的計時器停掉"
    assert page.status.property("state") == "error"
    shown = page.status.text()
    qtbot.wait(200)
    assert page.status.text() == shown, "失敗訊息被上一筆成功的計時器清掉了"


def test_saving_keeps_the_date_the_user_picked(window) -> None:
    """儲存成功後日期**不**跳回今天 —— 補記前幾天時，同一天常連記好幾筆。

    以前 `submit()` 成功後走 `clear_form()`，日期被設回今天，下一筆忘了改就記錯天，
    而畫面上完全看不出來。金額與備註照樣清掉。
    """
    page = window.entry
    picked = QDate.currentDate().addDays(-3)
    page.select_entry_type("expense")
    page.occurred_at.setDate(picked)
    page.amount.setText("85")
    page.description.setText("午餐")

    page.submit()

    assert page.status.property("state") == "ok", page.status.text()
    assert page.occurred_at.date() == picked
    assert page.amount.text() == ""
    assert page.description.text() == ""


def test_the_clear_button_does_what_escape_does(window) -> None:
    """「清空」＝ Esc：清日期（回今天）、金額、備註，**流向／帳戶／類別留著**。

    連記幾筆同類的帳時那幾格本來就該留著；儲存成功後的自動清除也是同一個範圍。
    """
    page = window.entry
    assert page.clear_button.text() == "清空"

    page.select_entry_type("income")
    category_before = page.category.currentData()
    detail_before = page.detail.currentData()
    account_before = page.account.currentData()
    page.amount.setText("1200")
    page.description.setText("紅包")
    page.occurred_at.setDate(QDate.currentDate().addDays(-3))

    page.clear_button.click()

    assert page.amount.text() == ""
    assert page.description.text() == ""
    assert page.occurred_at.date() == QDate.currentDate()
    assert page.current_entry_type() == "income"
    assert page.account.currentData() == account_before
    assert page.category.currentData() == category_before
    assert page.detail.currentData() == detail_before


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

    **選取中的那一格要另外量，而且要帶 `State_Selected`。** 2026-09-27 使用者看到
    「選到的那一天」顯示成「...」：`QTableView::item:selected { padding: 6px 8px }`
    比日曆那條 `padding: 0` 多一個偽類，優先度較高，於是只有被選的那格又被擠爆。
    以前這條測試量的 option 沒有選取狀態，那條規則根本沒有機會套上來。
    """
    # **主題一定要真的套上去，否則這條測試什麼都沒驗到。** 樣式表是掛在 QApplication
    # 上的，只有建過 MainWindow 的測試才會設它 —— 單獨跑這一條時它是空的，於是
    # 「有沒有被 padding 吃掉」根本不會發生。2026-08-21 第一版就是這樣假性通過的。
    application = QApplication.instance()
    apply_dark_theme(application)
    assert "QTableView::item" in application.styleSheet(), (
        "樣式表裡沒有那條全域的 item padding —— 這條守門失去了它要防的東西"
    )

    # 選在兩位數的日子，選取中的那格才會被下面的迴圈量到。
    field = date_field(QDate(2026, 9, 27))
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
    selected_checked = 0
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
            if view.selectionModel().isSelected(index):
                option.state |= QStyle.StateFlag.State_Selected
                selected_checked += 1
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
    assert selected_checked == 1, "沒量到選取中的那一格，`:selected` 那條規則等於沒被驗到"


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


def test_a_transfer_template_lands_between_my_own_accounts(window) -> None:
    """模板裡的轉帳一定是「我的帳戶之間」—— 不管記帳頁上一次停在哪一種轉帳對象。

    以前 `apply_draft()` 只切流向、不切轉帳對象：剛記過一筆「別人轉入」，再按「郵局提款」
    模板的「填入記帳頁」，轉入帳戶那一列被藏起來，**存下去是一筆收入**，總資產憑空多了一筆。
    """
    controller = window.controller
    created = controller.create_account("郵局", "1000")
    assert created.success
    post_office = str(created.details["account_id"])
    page = window.entry
    page.reload_options()

    page.select_entry_type("transfer")
    page.select_transfer_scope("inbound")
    assert page.effective_entry_type() == "income", "前提：上一次停在「別人轉入」"

    page.apply_draft(
        {
            "entry_type": "transfer",
            "account_id": post_office,
            "destination_account_id": "acct_cash",
            "description": "郵局提款",
        }
    )

    assert page.current_transfer_scope() == "internal"
    assert page.form.isRowVisible(page.destination) is True
    assert page.account.currentData() == post_office
    assert page.destination.currentData() == "acct_cash"
    page.amount.setText("3000")
    page.submit()
    assert "已儲存" in page.status.text(), page.status.text()
    kinds = [
        row["entry_type"]
        for row in controller.list_transactions().details["transactions"]
    ]
    assert kinds == ["transfer"], kinds
