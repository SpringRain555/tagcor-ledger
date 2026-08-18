"""把 controller 回傳的 dict 轉成表格要顯示的字串。

這裡是**唯一**決定畫面上中文長什麼樣子的地方 —— 頁面只負責擺 widget 與接訊號，不要
在頁面裡自己拼顯示字串，否則同一個狀態會在不同頁面長出不同講法。

金額一律用 `minor_text()` 轉。TWD 沒有輔幣（`CURRENCY_SCALE = 0`），所以 minor unit
就是元；**不要在這裡做除法**，那是把整數金額換成浮點數的第一步。
"""

from __future__ import annotations

from datetime import datetime
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

ENTRY_NAMES = {"expense": "支出", "income": "收入", "transfer": "轉帳"}
STATUS_NAMES = {"active": "有效", "voided": "已作廢"}
FREQUENCY_NAMES = {
    "daily": "日",
    "weekly": "週",
    "monthly": "月",
    "yearly": "年",
}


def minor_text(value: int | str) -> str:
    return str(int(value))


def result_message(result: Any) -> str:
    reason = str(result.details.get("reason", "")).strip()
    return f"{result.message}{'（' + reason + '）' if reason else ''}"


def display_datetime(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%Y/%m/%d %H:%M")
    except ValueError:
        return value


def balance_gap_values(item: dict[str, Any]) -> list[str]:
    return [
        display_datetime(str(item["observed_at"])),
        str(item["account_name"]),
        f"{item['actual_balance']} {item['currency']}",
        f"{item['expected_balance']} {item['currency']}",
        f"{item['difference']} {item['currency']}",
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
    return [
        display_datetime(str(item["occurred_at"])),
        str(item["entry_type_name"]),
        account,
        category,
        f"{item['amount']} {item['currency']}",
        str(item["description"]),
        STATUS_NAMES.get(str(item["status"]), str(item["status"])),
    ]


def account_values(item: dict[str, Any]) -> list[str]:
    return [
        str(item["name"]),
        str(item["account_type"]),
        str(item["currency"]),
        minor_text(item["balance_minor"]),
        "使用中" if item["status"] == "active" else "已封存",
    ]


def category_values(item: dict[str, Any]) -> list[str]:
    return [
        str(item.get("parent_name", "")),
        str(item["name"]) if int(item["level"]) == 2 else "",
        "使用中" if item["status"] == "active" else "已封存",
    ]


def template_values(item: dict[str, Any]) -> list[str]:
    amount = (
        minor_text(item["amount_minor"])
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
        minor_text(item["amount_minor"])
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


DEPOSIT_TERM_STATUS_NAMES = {
    "active": "存續中",
    "matured": "已到期",
    "renewed": "已續約",
    "settled": "已結清",
    "terminated": "已解約",
}


def rate_text(annual_rate_ppm: Any) -> str:
    """百萬分之一為單位的整數 → 百分比字串。**不用浮點數。**

    1.6% 存成 16000 ppm，除以 10000 得到整數位與小數位，用字串組起來。
    """
    if annual_rate_ppm is None:
        return "未填"
    ppm = int(annual_rate_ppm)
    whole, fraction = divmod(ppm, 10_000)
    return f"{whole}.{fraction:04d}".rstrip("0").rstrip(".") + "%"


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
        minor_text(item["principal_minor"]),
        shown_rate,
        minor_text(actual) if actual is not None else "尚未確認",
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
        minor_text(suggested) if suggested is not None else "需照存摺填寫",
    ]
