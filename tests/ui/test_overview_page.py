"""資產總覽：總資產怎麼算、什麼時候重算、沒話說的區塊要收起來。

**這一頁是「切過去就重算」，不接跨頁連動的訊號** —— 理由在 `pages/overview.py`。
"""
import json
import os
from datetime import date, timedelta
from pathlib import Path

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.domain.tax.dataset import Window
from tagcor_ledger.domain.tax.estimate import Estimate
from tagcor_ledger.domain.tax.kinds import (
    DeductionChoice,
    FilingStatus,
    TaxKind,
)
from tagcor_ledger.domain.tax.records import PaymentFact, TaxYearInputs
from tagcor_ledger.domain.tax.reminders import ReminderCycle, ReminderState, ReminderSwitch, ReminderView
from tagcor_ledger.ui.controller.tax import TaxOverview
from tagcor_ledger.ui.main_window import MainWindow
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
    assert count >= 1, "測試資料沒有產生待確認草稿，這條測試等於沒作用"
    assert count == len(controller.list_deposit_pending())
    assert window.sidebar.item_for(PageId.BALANCE).data(BADGE_ROLE) == count
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
    assert page.inbox_note.text() == "沒有待確認草稿。"
    assert not page.inbox_button.isVisible()
    # 新帳本有四個稅目尚未決定是否提醒，所以總覽會多一列稅務狀態。
    assert page.tax_notes[0].text() == "還有 4 項稅務提醒沒決定要不要開。"
    assert not page.tax_notes[0].isHidden()
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


def test_the_gap_reminder_lives_on_the_page_not_the_status_bar(window) -> None:
    """**留下來的那則提醒是「盤點過了、金額對不上」**，不是「今天還沒盤點」。

    v0.26.0 拿掉後者：它依日曆觸發，只要今天沒盤點就跳，而這位使用者的盤點是不定期
    的 —— 一則永遠都在的提醒等於沒有提醒。前者依事實觸發，是真的有事情要做。

    這一條同時守三件事：**沒有差額就整列收起來**（「差額 0」不是待辦）、
    提醒是頁面上的一行字加一顆按鈕而不是 10 秒就消失的狀態列訊息、
    以及按下「去盤點」要真的跳到餘額盤點頁。
    """
    window.show_page(PageId.OVERVIEW)
    page = window.overview

    # 陽性對照：還沒盤點過，所以這一列是收起來的 —— 不是「永遠顯示」。
    assert not page.gap_note.isVisible()
    assert not page.gap_button.isVisible()

    # 現金餘額是 0，盤點填 500 → 未解釋差額 500。
    window.balance.amount.setText("500")
    window.balance.create_snapshot()
    window.show_page(PageId.OVERVIEW)

    assert page.gap_note.isVisible()
    assert page.gap_button.isVisible()
    assert "現金" in page.gap_note.text()
    assert "500" in page.gap_note.text()
    assert window.statusBar().currentMessage() == ""

    page.gap_button.click()
    assert window.current_page_widget() is window.balance


def _tax_window_data(
    tmp_path: Path,
    monkeypatch,
    *,
    kinds: tuple[TaxKind, ...] = tuple(TaxKind),
    base_path: Path | None = None,
) -> Path:
    base = base_path or Path(os.environ["TAGCOR_TAX_DATA"])
    dataset = json.loads(base.read_text(encoding="utf-8"))
    source_id = str(dataset["sources"][0]["id"])
    dataset["calendar"] = {
        "typical": {
            kind.value: {
                "start": "05-01",
                "end": "05-31",
                "basis": "測試用期間",
                "source_ids": [source_id],
            }
            for kind in kinds
        },
        "years": {},
    }
    target = tmp_path / "overview-tax-dataset.json"
    target.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("TAGCOR_TAX_DATA", str(target))
    return target


def _new_window(qtbot, tmp_path: Path) -> MainWindow:
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.resize(1280, 760)
    window.show()
    return window


def test_income_tax_row_routes_to_estimate_and_mapping_tabs(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    _tax_window_data(tmp_path, monkeypatch, kinds=(TaxKind.INCOME_TAX,))
    window = _new_window(qtbot, tmp_path)
    window.controller.today_provider = lambda: date(2026, 5, 15)
    row_signal = QSignalSpy(window.overview.tax_requested)

    window.overview.refresh()
    assert "綜合所得稅：" in window.overview.tax_notes[0].text()
    window.overview.tax_buttons[0].click()
    assert row_signal.count() == 1
    assert row_signal.at(0)[0] == "estimate"
    assert window.current_page_widget() is window.tax
    assert window.tax.tabs.currentWidget() is window.tax.estimate
    estimate_year = window.tax.estimate.year.findData(2025)
    assert estimate_year >= 0
    window.tax.estimate.year.setCurrentIndex(estimate_year)

    assert window.controller.save_tax_year_inputs(
        TaxYearInputs(
            income_year=2025,
            filing=FilingStatus.SINGLE,
            deduction=DeductionChoice.STANDARD,
            other_special_deductions=False,
            dependents_have_income=False,
            filer_70_plus=False,
            dependents=0,
            dependents_70_plus=0,
            official_tax_minor=None,
            official_balance_minor=None,
        )
    ).success
    assert window.controller.submit(
        occurred_at="2025-08-19T10:00:00+08:00",
        entry_type="income",
        amount="100",
        account_id="acct_cash",
        destination_account_id=None,
        category_id="cat_food_711",
        description="未歸類收入",
    ).success
    window.overview.refresh()
    window.overview.tax_buttons[0].click()
    assert row_signal.count() == 2
    assert row_signal.at(1)[0] == "mapping"
    assert window.tax.tabs.currentWidget() is window.tax.mapping
    mapping_year = window.tax.mapping.year.findData(2025)
    assert mapping_year >= 0
    window.tax.mapping.year.setCurrentIndex(mapping_year)
    assert "未歸類" in window.tax.mapping.warning.text()


def test_missing_dataset_status_opens_data_and_supported_reminder_opens_reminders(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    baseline = Path(os.environ["TAGCOR_TAX_DATA"])
    monkeypatch.setenv("TAGCOR_TAX_DATA", str(tmp_path / "missing.json"))
    missing_window = _new_window(qtbot, tmp_path / "missing")
    missing_window.controller.today_provider = lambda: date(2026, 11, 9)
    missing_window.overview.refresh()
    assert missing_window.overview.tax_notes[0].text() == (
        "稅務資料不在，稅務提醒與試算暫停。"
    )
    missing_window.overview.tax_buttons[0].click()
    assert missing_window.current_page_widget() is missing_window.tax
    assert missing_window.tax.tabs.currentWidget() is missing_window.tax.data

    _tax_window_data(
        tmp_path,
        monkeypatch,
        kinds=(TaxKind.INCOME_TAX,),
        base_path=baseline,
    )
    reminder_window = _new_window(qtbot, tmp_path / "reminders")
    reminder_window.controller.today_provider = lambda: date(2026, 5, 15)
    assert reminder_window.controller.save_tax_year_inputs(
        TaxYearInputs(
            income_year=2025,
            filing=FilingStatus.SINGLE,
            deduction=DeductionChoice.STANDARD,
            other_special_deductions=False,
            dependents_have_income=False,
            filer_70_plus=False,
            dependents=0,
            dependents_70_plus=0,
            official_tax_minor=None,
            official_balance_minor=None,
        )
    ).success
    reminder_window.overview.refresh()
    signal = QSignalSpy(reminder_window.overview.tax_requested)
    reminder_window.overview.tax_buttons[0].click()
    assert signal.at(0)[0] == "reminders"
    assert reminder_window.tax.tabs.currentWidget() is reminder_window.tax.reminders


def test_five_open_tax_items_fold_into_at_most_four_overview_rows(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    _tax_window_data(tmp_path, monkeypatch)
    window = _new_window(qtbot, tmp_path)
    window.controller.today_provider = lambda: date(2026, 5, 15)
    for kind in TaxKind:
        assert window.controller.save_tax_reminder_switch(kind, ReminderSwitch.ON).success
    window.overview.refresh()

    active = [
        (label, button)
        for label, button in zip(
            window.overview.tax_notes,
            window.overview.tax_buttons,
            strict=True,
        )
        if not label.isHidden()
    ]
    assert len(active) == 3
    assert sum("：" in label.text() for label, _ in active) == 2
    assert "另有 3 件稅務提醒。" in [label.text() for label, _ in active]
    assert any("還有" in label.text() for label, _ in active)


@pytest.mark.parametrize(
    ("kind", "state", "start", "end", "today", "income_balance"),
    [
        (
            TaxKind.FUEL_FEE,
            ReminderState.OVERDUE,
            date(2026, 7, 1),
            date(2026, 7, 31),
            date(2026, 8, 1),
            None,
        ),
        (
            TaxKind.FUEL_FEE,
            ReminderState.OPEN,
            date(2026, 7, 1),
            date(2026, 7, 31),
            date(2026, 7, 15),
            None,
        ),
        (
            TaxKind.INCOME_TAX,
            ReminderState.OVERDUE,
            date(2026, 5, 1),
            date(2026, 5, 31),
            date(2026, 6, 1),
            1_234_567,
        ),
    ],
    ids=("燃料費逾期", "燃料費期間中", "綜所稅逾期"),
)
def test_longest_tax_sentence_fits_its_action_row_geometry(
    window,
    monkeypatch,
    kind: TaxKind,
    state: ReminderState,
    start: date,
    end: date,
    today: date,
    income_balance: int | None,
) -> None:
    cycle = ReminderCycle(
        kind=kind,
        year=start.year,
        window=Window(
            kind=kind,
            year=start.year,
            start=start,
            end=end,
            estimated=True,
            note=None,
            source_ids=(),
        ),
        notify_from=start - timedelta(days=14),
        overdue_until=end + timedelta(days=30),
    )
    view = ReminderView(
        kind=kind,
        state=state,
        cycle=cycle,
        mark=None,
        last_year_paid=(
            PaymentFact(count=2, total_minor=123_456, last_on="2025-07-31")
            if kind is TaxKind.FUEL_FEE
            else None
        ),
    )
    estimate = (
        Estimate(2025, (), (), None, None, income_balance, False, None, ())
        if income_balance is not None
        else None
    )
    overview = TaxOverview((view,), 0, None, 0, estimate)
    monkeypatch.setattr(window.controller, "tax_overview", lambda: overview)
    window.controller.today_provider = lambda: today
    window.resize(1280, 760)
    QApplication.processEvents()
    window.overview.refresh()
    QApplication.processEvents()
    label = window.overview.tax_notes[0]

    sentence = label.text()
    # REQ-0011 §UI 2026-11-09：總覽不標預估；燃料費用正式短名。
    assert "預估" not in sentence
    if kind is TaxKind.FUEL_FEE:
        assert "公路使用養護安全管理費" in sentence
        assert "（原燃料費）" not in sentence
        assert "（去年 123,456 元）" in sentence
    else:
        assert "估計應補 1,234,567 元" in sentence
    assert label.sizeHint().width() <= label.width(), (
        f"{kind.value}/{state.value}：句子需要 {label.sizeHint().width()} px，"
        f"分到 {label.width()} px；{sentence}"
    )
