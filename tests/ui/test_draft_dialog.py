"""模板與定期收支的編輯對話框。**它是這兩個功能唯一的 UI 入口。**

## 為什麼這一份特別重要

2026-08-22 的覆蓋率掃描顯示 `ui/widgets/draft_dialog.py` **171 行裡有 149 行沒被
執行過** —— 全專案最大的缺口。既有的頁面測試都繞過對話框直接呼叫 controller，
於是「使用者實際填的那張表變成什麼資料」這件事沒有任何東西驗過。

那張表決定的東西不小：

- **轉帳與非轉帳填的是不同欄位。** 轉帳要有轉入帳戶、不能有類別；反過來也是。
  弄反的話 store 會丟 `TRANSFER_DRAFT_INVALID`，但那是在「已經按下儲存」之後。
- **編輯既有項目時要保住 `schedule_id` 與 `next_due_date`。** 沒保住的話會變成
  「編輯」產生一筆新的，舊的還在 —— 而 v0.21.0 才剛補的 `AUTOMATION_ID_REQUIRED`
  就是因為空主鍵會 UPSERT 出一列。
- **金額可以留空**（套用時再填），但填了就要能解析。

這些全部發生在 `save()` 那三十行裡。
"""

from __future__ import annotations

from typing import Any

import pytest

from tagcor_ledger.ui.widgets.draft_dialog import DraftDialog


@pytest.fixture
def controller(window: Any) -> Any:
    """借 `window` fixture 的 controller —— 對話框要的是真的資料，不是假的。"""
    return window.controller


def _dialog(
    controller: Any,
    qtbot: Any,
    window: Any,
    *,
    schedule: bool,
    current: dict[str, Any] | None = None,
) -> DraftDialog:
    """`parent` 傳真的視窗 —— `DraftDialog` 的 `parent` 是必填而且不接受 `None`。"""
    dialog = DraftDialog(controller, schedule=schedule, current=current, parent=window)
    qtbot.addWidget(dialog)
    return dialog


def _pick_category(dialog: DraftDialog) -> None:
    """選第一個有子項目的類別，並選它底下的第一個項目。"""
    assert dialog.category.count() > 0, "沒有任何類別可選，種子資料可能變了"
    for index in range(dialog.category.count()):
        dialog.category.setCurrentIndex(index)
        if dialog.detail.count() > 0:
            return
    pytest.fail("沒有任何類別底下有項目")


# --------------------------------------------------------------- 建立（新的）


def test_a_new_template_dialog_only_shows_the_fields_a_template_needs(
    controller: Any, qtbot: Any, window: Any
) -> None:
    """模板沒有週期欄位 —— 那是定期收支才有的。"""
    dialog = _dialog(controller, qtbot, window, schedule=False)
    assert dialog.windowTitle() == "模板"
    labels = [
        dialog.form.itemAt(row, dialog.form.ItemRole.LabelRole)
        for row in range(dialog.form.rowCount())
    ]
    texts = [item.widget().text() for item in labels if item is not None and item.widget()]
    assert "週期" not in texts, "模板不該有週期欄位"
    assert "名稱" in texts and "金額（可留空）" in texts


def test_a_new_schedule_dialog_adds_the_recurrence_fields(
    controller: Any, qtbot: Any, window: Any
) -> None:
    dialog = _dialog(controller, qtbot, window, schedule=True)
    assert dialog.windowTitle() == "定期收支"
    assert dialog.frequency.count() == 4, "每日／每週／每月／每年"
    assert not dialog.end_date.isEnabled(), "沒勾『設定結束日期』時結束日期要停用"


def test_saving_a_template_produces_the_values_that_were_typed(
    controller: Any, qtbot: Any, window: Any
) -> None:
    dialog = _dialog(controller, qtbot, window, schedule=False)
    dialog.name.setText("  早餐  ")
    _pick_category(dialog)
    dialog.amount.setText("85")
    dialog.description.setText("7-11")
    dialog.save()

    saved = dialog.saved_value
    assert saved is not None, f"沒有存下來：{dialog.error.text()}"
    assert saved.name == "早餐", "名稱前後的空白要去掉"
    assert saved.amount_minor == 85
    assert saved.description == "7-11"
    assert saved.template_id.startswith("tpl_"), "新模板要有新的識別碼"


def test_an_empty_amount_is_allowed_and_means_fill_it_in_later(
    controller: Any, qtbot: Any, window: Any
) -> None:
    """金額可以留空 —— 套用模板的時候再填。"""
    dialog = _dialog(controller, qtbot, window, schedule=False)
    dialog.name.setText("加油")
    _pick_category(dialog)
    dialog.amount.setText("   ")
    dialog.save()

    assert dialog.saved_value is not None, dialog.error.text()
    assert dialog.saved_value.amount_minor is None


def test_a_bad_amount_is_refused_in_the_dialog_not_at_the_store(
    controller: Any, qtbot: Any, window: Any
) -> None:
    """金額打錯要當場說，而且**不准關掉對話框** —— 關掉的話使用者剛打的東西全沒了。"""
    dialog = _dialog(controller, qtbot, window, schedule=False)
    dialog.name.setText("亂打")
    _pick_category(dialog)
    dialog.amount.setText("八十五")
    dialog.save()

    assert dialog.saved_value is None, "格式錯的金額不該存下來"
    assert dialog.error.text(), "要在對話框上說明哪裡不對"
    assert "AMOUNT" not in dialog.error.text(), "不准把英文碼印給使用者看"


# --------------------------------------------------------------- 轉帳與非轉帳


def test_a_transfer_draft_carries_a_destination_and_no_category(
    controller: Any, qtbot: Any, window: Any
) -> None:
    """轉帳：有轉入帳戶、**沒有**類別。

    弄反的話 store 會丟 `TRANSFER_DRAFT_INVALID` —— 那是在按下儲存之後才知道。
    """
    assert controller.create_account("郵局", "0").success
    dialog = _dialog(controller, qtbot, window, schedule=False)
    dialog.name.setText("每月轉存")
    dialog.flow.setCurrentIndex(dialog.flow.findData("transfer"))
    assert dialog.destination.count() >= 2, "要有第二個帳戶才轉得了"
    dialog.destination.setCurrentIndex(1)
    dialog.save()

    saved = dialog.saved_value
    assert saved is not None, dialog.error.text()
    assert saved.entry_type == "transfer"
    assert saved.destination_account_id is not None
    assert saved.category_id is None, "轉帳不該帶類別"


def test_a_non_transfer_draft_carries_a_category_and_no_destination(
    controller: Any, qtbot: Any, window: Any
) -> None:
    dialog = _dialog(controller, qtbot, window, schedule=False)
    dialog.name.setText("午餐")
    _pick_category(dialog)
    dialog.save()

    saved = dialog.saved_value
    assert saved is not None, dialog.error.text()
    assert saved.category_id is not None
    assert saved.destination_account_id is None, "支出不該帶轉入帳戶"


def test_switching_the_flow_swaps_which_rows_are_visible(
    controller: Any, qtbot: Any, window: Any
) -> None:
    """切到轉帳時類別與項目要收起來，切回來要放出來。

    看的是 `setRowVisible` 的效果 —— 欄位還在但不該讓使用者填。
    """
    dialog = _dialog(controller, qtbot, window, schedule=False)
    dialog.show()

    dialog.flow.setCurrentIndex(dialog.flow.findData("transfer"))
    assert dialog.destination.isVisibleTo(dialog)
    assert not dialog.category.isVisibleTo(dialog)

    dialog.flow.setCurrentIndex(dialog.flow.findData("expense"))
    assert not dialog.destination.isVisibleTo(dialog)
    assert dialog.category.isVisibleTo(dialog)


# ------------------------------------------------------------------ 編輯既有


def test_editing_a_schedule_keeps_its_id_and_next_due_date(
    controller: Any, qtbot: Any, window: Any
) -> None:
    """**編輯不可以產生新的識別碼。**

    產生新的話舊那筆還在，使用者看到兩筆；而 `next_due_date` 掉了的話，
    已經跑到第五期的排程會退回第一期重跑。
    """
    seed = _dialog(controller, qtbot, window, schedule=True)
    seed.name.setText("房租")
    _pick_category(seed)
    seed.amount.setText("12000")
    seed.save()
    assert controller.save_schedule(seed.saved_value).success

    existing = controller.list_schedules()[0]
    original_id = str(existing["schedule_id"])
    original_due = str(existing["next_due_date"])

    dialog = _dialog(controller, qtbot, window, schedule=True, current=existing)
    assert dialog.name.text() == "房租", "既有內容要讀進來"
    dialog.name.setText("房租（調漲）")
    dialog.save()

    saved = dialog.saved_value
    assert saved is not None, dialog.error.text()
    assert saved.schedule_id == original_id, "編輯產生了新的識別碼"
    assert saved.next_due_date == original_due, "下次到期日被重設了"
    assert saved.name == "房租（調漲）"

    assert controller.save_schedule(saved).success
    assert len(controller.list_schedules()) == 1, "編輯不該多出一筆"


def test_editing_a_template_keeps_its_id_and_sort_order(
    controller: Any, qtbot: Any, window: Any
) -> None:
    """模板同理，而且要保住自訂順序 —— 改個名字就跳回列表最後面很惱人。"""
    seed = _dialog(controller, qtbot, window, schedule=False)
    seed.name.setText("早餐")
    _pick_category(seed)
    seed.save()
    assert controller.save_template(seed.saved_value).success

    existing = controller.list_templates()[0]
    dialog = _dialog(controller, qtbot, window, schedule=False, current=existing)
    dialog.name.setText("早餐（新）")
    dialog.save()

    saved = dialog.saved_value
    assert saved is not None, dialog.error.text()
    assert saved.template_id == str(existing["template_id"])
    assert saved.sort_order == int(existing["sort_order"])


def test_an_end_date_is_only_sent_when_the_box_is_ticked(
    controller: Any, qtbot: Any, window: Any
) -> None:
    """沒勾就是沒有結束日期 —— 不能因為欄位裡有一個預設值就送出去。"""
    dialog = _dialog(controller, qtbot, window, schedule=True)
    dialog.name.setText("訂閱")
    _pick_category(dialog)
    dialog.save()
    assert dialog.saved_value is not None, dialog.error.text()
    assert dialog.saved_value.end_date is None

    ticked = _dialog(controller, qtbot, window, schedule=True)
    ticked.name.setText("訂閱")
    _pick_category(ticked)
    ticked.has_end.setChecked(True)
    ticked.save()
    assert ticked.saved_value is not None, ticked.error.text()
    assert ticked.saved_value.end_date is not None


def test_editing_restores_the_category_two_levels_down(
    controller: Any, qtbot: Any, window: Any
) -> None:
    """既有項目的**第二層**要被選回來，不是只選到它的所屬類別。

    `_select_category()` 得逐一翻每個類別的子項目才找得到 —— 那段邏輯在這條之前
    沒有任何東西走過。
    """
    seed = _dialog(controller, qtbot, window, schedule=False)
    seed.name.setText("捷運")
    _pick_category(seed)
    chosen = str(seed.detail.currentData())
    seed.save()
    assert controller.save_template(seed.saved_value).success

    existing = controller.list_templates()[0]
    reopened = _dialog(controller, qtbot, window, schedule=False, current=existing)
    assert str(reopened.detail.currentData()) == chosen, "第二層沒有被選回來"


def test_reopening_a_schedule_that_has_an_end_date_ticks_the_box(
    controller: Any, qtbot: Any, window: Any
) -> None:
    """有結束日期的定期收支，重開時勾選框要是勾起來的、日期要讀回來。

    沒讀回來的話使用者一存檔就把結束日期弄丟了 —— 而畫面上看不出來少了東西。
    """
    seed = _dialog(controller, qtbot, window, schedule=True)
    seed.name.setText("健身房")
    _pick_category(seed)
    seed.has_end.setChecked(True)
    seed.save()
    assert controller.save_schedule(seed.saved_value).success
    expected = seed.saved_value.end_date
    assert expected is not None

    existing = controller.list_schedules()[0]
    reopened = _dialog(controller, qtbot, window, schedule=True, current=existing)

    assert reopened.has_end.isChecked(), "結束日期的勾選框沒有被讀回來"
    assert reopened.end_date.isEnabled()
    assert reopened.end_date.date().toString("yyyy-MM-dd") == expected


def test_a_category_with_no_children_leaves_the_detail_box_empty(
    controller: Any, qtbot: Any, window: Any
) -> None:
    """沒有子項目的類別：項目下拉要是空的，**不是沿用上一個類別的項目**。

    沿用的話使用者會把帳記到完全不相干的項目底下。
    """
    assert controller.create_category("交通").success
    dialog = _dialog(controller, qtbot, window, schedule=False)
    _pick_category(dialog)
    assert dialog.detail.count() > 0

    for index in range(dialog.category.count()):
        if dialog.category.itemText(index) == "交通":
            dialog.category.setCurrentIndex(index)
            break
    else:
        pytest.fail("找不到剛建立的「交通」類別")

    assert dialog.detail.count() == 0, "空類別的項目下拉沒有清空"
