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
    FREQUENCY_NAMES,
    INBOX_SOURCE_NAMES,
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


def transaction_values(item: dict[str, Any]) -> list[str]:
    category = " / ".join(
        str(part)
        for part in (item.get("category_name"), item.get("subcategory_name"))
        if part
    )
    account = str(item["account_name"])
    if item["entry_type"] == "transfer":
        account += f" → {item.get('destination_account_name') or ''}"
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
    amount = (
        group_digits(item["amount_minor"])
        if item.get("amount_minor") is not None
        else "套用時輸入"
    )
    return [
        str(item["name"]),
        ENTRY_NAMES.get(str(item["entry_type"]), str(item["entry_type"])),
        amount,
        str(item["description"]),
    ]


def schedule_values(item: dict[str, Any]) -> list[str]:
    interval = int(item["interval_count"])
    frequency = FREQUENCY_NAMES.get(str(item["frequency"]), str(item["frequency"]))
    return [
        str(item["name"]),
        ENTRY_NAMES.get(str(item["entry_type"]), str(item["entry_type"])),
        f"每 {interval} {frequency}",
        str(item["next_due_date"]),
        str(item.get("end_date") or "無"),
    ]


def occurrence_values(item: dict[str, Any]) -> list[str]:
    amount = (
        group_digits(item["amount_minor"])
        if item.get("amount_minor") is not None
        else "尚未填寫"
    )
    return [
        str(item["due_date"]),
        str(item["schedule_name"]),
        ENTRY_NAMES.get(str(item["entry_type"]), str(item["entry_type"])),
        amount,
        str(item.get("invalid_reason") or "可確認"),
    ]


def inbox_values(item: dict[str, Any]) -> list[str]:
    """待確認的單一表格：到期日／來源／名稱／類型／金額／狀態說明。

    定期收支與定存的欄位形狀不同，統一成字串的地方就是這裡 —— 頁面只擺 widget。

    **定存的金額欄寫「需照存摺填寫」而不是 0。** 建議值是程式試算的，權威值在存摺上；
    印一個 0 會讓人以為那就是答案。
    """
    source = str(item["source"])
    if source == "deposit":
        suggested = item.get("suggested_amount_minor")
        return [
            display_date(str(item["due_date"])),
            INBOX_SOURCE_NAMES[source],
            str(item["contract_name"]),
            DEPOSIT_EVENT_TYPE_NAMES.get(
                DepositEventType(str(item["event_type"])), str(item["event_type"])
            ),
            group_digits(suggested) if suggested is not None else "需照存摺填寫",
            "確認時輸入實際金額",
        ]
    amount = item.get("amount_minor")
    return [
        display_date(str(item["due_date"])),
        INBOX_SOURCE_NAMES[source],
        str(item["schedule_name"]),
        ENTRY_NAMES.get(str(item["entry_type"]), str(item["entry_type"])),
        group_digits(amount) if amount is not None else "尚未填寫",
        str(item.get("invalid_reason") or "可確認"),
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
    suggested = item.get("suggested_amount_minor")
    return [
        str(item["due_date"]),
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
