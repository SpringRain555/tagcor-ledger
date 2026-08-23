"""每一張表「一列長什麼樣」。

**只有這裡決定表格與清單的列內容。** 頁面負責擺 widget 與接訊號，不要在頁面裡自己
拼列內容 —— 同一個狀態一旦有兩個拼法，兩張表就會對同一筆資料講不同的話。
`tests/ui/test_table_columns.py` 會把這裡的每一個函式與它那張表的欄位標題對起來比長度。
"""

from __future__ import annotations

from typing import Any

from tagcor_ledger.domain.deposits import (
    DEPOSIT_EVENT_TYPE_NAMES,
    INTEREST_METHOD_NAMES,
    MATURITY_ACTION_NAMES,
    RATE_TYPE_NAMES,
    DepositEventType,
    InterestMethod,
    MaturityAction,
    RateType,
)
from tagcor_ledger.ui.formatting.primitives import (
    DEPOSIT_TERM_STATUS_NAMES,
    ENTRY_NAMES,
    STATUS_NAMES,
    display_date,
    group_digits,
    rate_text,
    signed_amount_text,
)



def balance_gap_values(item: dict[str, Any]) -> list[str]:
    return [
        display_date(str(item["observed_at"])),
        str(item["account_name"]),
        group_digits(str(item["actual_balance"])),
        group_digits(str(item["expected_balance"])),
        group_digits(str(item["difference"])),
        str(item["note"]),
        STATUS_NAMES.get(str(item["status"]), str(item["status"])),
    ]


def entry_target_text(item: dict[str, Any]) -> tuple[str, str]:
    """「錢從哪個帳戶走、記到哪個類別」—— 交易與模板共用的兩欄。

    回傳 `(帳戶, 類別)`：轉帳的帳戶欄是「來源 → 目的」，類別欄是空的；
    收入／支出反過來。**兩張表用同一個函式**，否則同一筆資料在交易紀錄與模板頁
    會被拼成兩種樣子 —— 而這正是「一列長什麼樣只由 `ui/formatting/` 決定」那條
    規則要防的東西。
    """
    account = str(item["account_name"])
    if item["entry_type"] == "transfer":
        account += f" → {item.get('destination_account_name') or ''}"
    category = " / ".join(
        str(part)
        for part in (item.get("category_name"), item.get("subcategory_name"))
        if part
    )
    return account, category


def transaction_values(item: dict[str, Any]) -> list[str]:
    account, category = entry_target_text(item)
    # 幣別不放進每一列 —— 目前固定 TWD，寫在欄位標題就夠，每列重複只是雜訊。
    return [
        display_date(str(item["occurred_at"])),
        str(item["entry_type_name"]),
        account,
        category,
        signed_amount_text(item),
        str(item["description"]),
        STATUS_NAMES.get(str(item["status"]), str(item["status"])),
    ]


def account_values(item: dict[str, Any]) -> list[str]:
    """**不顯示「類型」與「幣別」。**

    `account_type` 目前永遠是 `cash`（介面沒有地方可以改），`currency` 永遠是 TWD。
    兩欄對每一列都印同一個值，其中一個還是英文 —— 那不是資訊，是雜訊。
    幣別改寫在「目前餘額」的欄位標題上。
    """
    return [
        str(item["name"]),
        group_digits(item["balance_minor"]),
        "使用中" if item["status"] == "active" else "已封存",
    ]


def overview_account_values(item: dict[str, Any]) -> list[str]:
    """資產總覽只列名稱與餘額。

    **不重複「狀態」欄** —— 那一頁只顯示使用中的帳戶，每一列都寫「使用中」等於沒說。
    封存帳戶的餘額另外用一句話交代（見 `overview.py`）。
    """
    return [str(item["name"]), group_digits(item["balance_minor"])]


def category_values(item: dict[str, Any]) -> list[str]:
    """「類別」分頁：類別／項目數／狀態。

    **每一個類別都有自己的一列，不管它有沒有子項目。** 舊的做法只在沒有子項目時才
    列出類別本身，於是「伙食」永遠沒有自己的列 —— 畫面上那個「伙食」是項目那一列的
    第一欄，改名、封存、刪除因此對類別全部失效。
    """
    return [
        str(item["name"]),
        f"{int(item['item_count'])} 項",
        "使用中" if item["status"] == "active" else "已封存",
    ]


def item_values(item: dict[str, Any]) -> list[str]:
    """「項目」分頁：所屬類別／項目／狀態。"""
    return [
        str(item.get("parent_name") or ""),
        str(item["name"]),
        "使用中" if item["status"] == "active" else "已封存",
    ]


def template_values(item: dict[str, Any]) -> list[str]:
    """「模板」分頁：名稱／類型／帳戶／類別／金額／備註／狀態。

    **帳戶與類別是 v0.22.0 加的。** 只列名稱與金額時，兩個都叫「午餐」的模板在
    「填入記帳頁」之前分不出誰是誰 —— 而分辨它們正是這一頁存在的理由。
    兩欄的拼法與交易紀錄共用 `entry_target_text()`，所以同一筆資料在兩張表上
    長得一樣。

    **狀態欄也是 v0.22.0 才有的。** 在那之前這一頁只列使用中的模板，而「封存」沒有
    對應的「恢復」—— 於是封存等同刪除，但那一列其實還在資料庫裡，還擋著它引用的
    帳戶與類別被刪掉。狀態欄放最後，與帳戶／類別／項目三頁一致。
    """
    amount = (
        group_digits(item["amount_minor"])
        if item.get("amount_minor") is not None
        else "套用時輸入"
    )
    account, category = entry_target_text(item)
    return [
        str(item["name"]),
        ENTRY_NAMES.get(str(item["entry_type"]), str(item["entry_type"])),
        account,
        category,
        amount,
        str(item["description"]),
        "使用中" if item["status"] == "active" else "已封存",
    ]


def deposit_contract_values(item: dict[str, Any]) -> list[str]:
    method = InterestMethod(str(item["interest_method"]))
    action = MaturityAction(str(item["maturity_action"]))
    kind = RateType(str(item.get("rate_type", "fixed")))
    return [
        str(item["name"]),
        str(item.get("account_name", "")),
        INTEREST_METHOD_NAMES[method],
        MATURITY_ACTION_NAMES[action],
        RATE_TYPE_NAMES[kind],
        f"{item['term_months']} 個月",
        "使用中" if item["status"] == "active" else "已結束",
    ]


def deposit_term_values(item: dict[str, Any]) -> list[str]:
    """年利率欄優先顯示**反推出來的實際利率** —— 那是真的發生過的事實。

    事前填的牌告利率只是預期值，機動利率更是連填都不該填。
    """
    actual = item.get("actual_interest_minor")
    effective = item.get("effective_rate_ppm")
    if effective is not None:
        shown_rate = f"{rate_text(effective)}（實際）"
    else:
        shown_rate = rate_text(item.get("annual_rate_ppm"))
    return [
        f"第 {item['sequence']} 期",
        str(item["start_date"]),
        str(item["maturity_date"]),
        group_digits(item["principal_minor"]),
        shown_rate,
        group_digits(actual) if actual is not None else "尚未確認",
        DEPOSIT_TERM_STATUS_NAMES.get(str(item["status"]), str(item["status"])),
    ]


def deposit_event_values(item: dict[str, Any]) -> list[str]:
    """待確認那張表的一列：到期日／合約／類型／建議金額。

    **日期要走 `display_date()`。** 這個函式在 v0.23.0 之前沒有任何頁面用它
    （待確認走的是自己的 `inbox_values()`，而那一份有轉格式），所以它印 ISO 字串
    一直沒有人看到。合併成一份的時候差一點就把畫面上的日期換成 `2021-01-15`。

    **`deposit_term_values()` 的兩個日期目前還是 ISO 的**，那是另一件事：
    它們在定存頁上一直是那個樣子，改了要連那一頁的測試一起改。記在這裡，不順手動。

    **金額欄寫「需照存摺填寫」而不是 0。** 建議值是程式試算的，權威值在存摺上；
    印一個 0 會讓人以為那就是答案。
    """
    suggested = item.get("suggested_amount_minor")
    return [
        display_date(str(item["due_date"])),
        str(item["contract_name"]),
        DEPOSIT_EVENT_TYPE_NAMES.get(
            DepositEventType(str(item["event_type"])), str(item["event_type"])
        ),
        group_digits(suggested) if suggested is not None else "需照存摺填寫",
    ]


def reference_entry_values(item: dict[str, Any]) -> list[str]:
    return [
        str(item["law_name"]),
        f"第 {item['article']} 條",
        str(item["title"]),
        str(item["amended_date"]),
        "需複查" if item.get("stale") else "已複查",
    ]
