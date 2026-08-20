"""把 controller 回傳的 dict 轉成表格要顯示的字串。

這裡是**唯一**決定畫面上中文長什麼樣子的地方 —— 頁面只負責擺 widget 與接訊號，不要
在頁面裡自己拼顯示字串，否則同一個狀態會在不同頁面長出不同講法。

金額有兩種轉法，用錯地方會出事：

- `minor_text()` —— 給**輸入框**，純數字，因為它會被讀回來再解析。
- `group_digits()` / `signed_amount_text()` —— 給**表格**，有千分位與正負號。

TWD 沒有輔幣（`CURRENCY_SCALE = 0`），所以 minor unit 就是元；
**不要在這裡做除法**，那是把整數金額換成浮點數的第一步。
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
    """給**輸入框**用的純數字字串。不加千分位 —— 它會被原封不動讀回來再解析。"""
    return str(int(value))


def group_digits(value: int | str) -> str:
    """給**表格**用：1200 → `1,200`。純字串運算，不經過浮點數。

    三位一撇是這一欄能不能一眼比大小的關鍵。`100000` 與 `10000` 在等寬右對齊之前
    看起來只差一個字元寬度，`100,000` 與 `10,000` 一眼就分得出來。
    """
    text = str(value).strip()
    sign = ""
    if text[:1] in "+-":
        sign, text = text[0], text[1:]
    whole, _, fraction = text.partition(".")
    if not whole.isdigit():
        return str(value)
    grouped = f"{int(whole):,}"
    return f"{sign}{grouped}" + (f".{fraction}" if fraction else "")


def signed_amount_text(item: dict[str, Any]) -> str:
    """依流向加上正負號。**轉帳不加** —— 它既不是收入也不是支出。

    顏色不是唯一線索：色盲、列印與截圖都可能讓紅綠消失，符號在那些情況下還在。
    """
    amount = group_digits(str(item["amount"]))
    entry_type = str(item.get("entry_type", ""))
    if amount.startswith(("+", "-")):
        return amount
    if entry_type == "expense":
        return f"-{amount}"
    if entry_type == "income":
        return f"+{amount}"
    return amount


def result_message(result: Any) -> str:
    reason = str(result.details.get("reason", "")).strip()
    return f"{result.message}{'（' + reason + '）' if reason else ''}"


def display_date(value: str) -> str:
    """只顯示日期。

    資料庫存的是完整時間戳，但那個時分秒是**程式補的排序用值**，不是使用者輸入的 ——
    把它印出來會讓人以為那是真的記錄時間。畫面只問到哪一天，就只顯示到哪一天。
    """
    try:
        return datetime.fromisoformat(value).strftime("%Y/%m/%d")
    except ValueError:
        return value


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


INBOX_SOURCE_NAMES = {"schedule": "定期", "deposit": "定存"}
"""待確認那一列是哪裡來的。**這一欄不能省** —— 兩種來源的「類型」講的是不同的事
（一邊是收入／支出／轉帳，一邊是到期／領息／存入），沒有這一欄就看不懂。"""


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
