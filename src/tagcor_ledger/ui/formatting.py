"""把 controller 回傳的 dict 轉成表格要顯示的字串。

這裡是**唯一**決定畫面上中文長什麼樣子的地方 —— 頁面只負責擺 widget 與接訊號，不要
在頁面裡自己拼顯示字串，否則同一個狀態會在不同頁面長出不同講法。

金額一律用 `minor_text()` 轉。TWD 沒有輔幣（`CURRENCY_SCALE = 0`），所以 minor unit
就是元；**不要在這裡做除法**，那是把整數金額換成浮點數的第一步。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


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
