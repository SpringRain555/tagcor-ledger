"""把 controller 回傳的 dict 轉成表格要顯示的字串。

**表格與清單的「一列長什麼樣」只在這裡決定。** 頁面負責擺 widget 與接訊號，不要在
頁面裡自己拼列內容 —— 同一個狀態一旦有兩個拼法，兩張表就會對同一筆資料講不同的話。

**頁面自己的一次性訊息不在這裡**（「備份已建立：…」「CSV 已匯出：…」這類），那些
只出現一次、只屬於那一頁，搬過來只會讓這個模組變成所有中文字的倉庫。分界是
**「這句話會不會在別的地方也要用同一個講法」**。

金額有兩種轉法，用錯地方會出事：

- `minor_text()` —— 給**輸入框**，純數字，因為它會被讀回來再解析。
- `group_digits()` / `signed_amount_text()` —— 給**表格**，有千分位與正負號。

TWD 沒有輔幣（`CURRENCY_SCALE = 0`），所以 minor unit 就是元；
**不要在這裡做除法**，那是把整數金額換成浮點數的第一步。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


from tagcor_ledger.application.failures import message_for
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
    """畫面上顯示的一句話 —— **就是 `result.message`，不再接任何東西**。

    以前這裡會把 `details["reason"]` 用括號補在後面，於是畫面長這樣：

        帳戶無法刪除；預設帳戶或已有歷史資料的帳戶請改用封存。（ACCOUNT_IS_DEFAULT）

    那個括號是在補償「一個錯誤碼代表好幾件事」—— 中文句子太籠統，只好把底層的碼
    原封不動印出來讓人自己判斷。真正的修法是把碼拆開、每個碼講自己的話，
    那件事在 `application/failures.py`。這裡就只剩下顯示。

    `details["detail"]` 是給診斷用的，**永遠不顯示**。
    """
    return str(result.message)


BACKUP_STATE_LABELS = {
    "BACKUP_FILES_MISSING": "檔案缺少",
    "BACKUP_MANIFEST_INVALID": "清單檔壞掉",
    "BACKUP_CHECKSUM_MISMATCH": "內容被改過",
    "BACKUP_INTEGRITY_FAILED": "完整性檢查沒過",
    "BACKUP_SCHEMA_MISSING": "讀不到版本",
    "BACKUP_SCHEMA_TOO_NEW": "版本太新",
}
"""備份清單那一欄的**短標籤**，不是完整說法。

跟 `ERROR_MESSAGES` 的句子是兩件事，不是同一件事寫兩遍：清單一列要能一眼掃過去，
塞一整句「這個備份的檔案內容與清單裡記的雜湊對不起來 —— 檔案在備份之後被改過或
損毀了。請不要還原它，改用別的備份。」會讓每一列長到看不出哪一份是哪一份。
完整說法在按下「驗證」或「刪除」時才出現。

兩張表要同步：`tests/unit/test_failure_messages.py` 會檢查每個 `BACKUP_*` 兩邊都有。
"""


def backup_state_text(valid: bool, error_code: Any) -> str:
    """備份清單那一欄：可用，或是壞在哪裡。

    以前這裡直接印 `f"無效：{error_code}"`，於是清單上一整排
    `無效：BACKUP_CHECKSUM_MISMATCH`。
    """
    if valid:
        return "可用"
    code = str(error_code or "")
    return f"不可用（{BACKUP_STATE_LABELS.get(code, code or '原因不明')}）"


def backup_row_text(item: dict[str, Any]) -> str:
    """備份清單的一列：時間｜狀態｜資料夾名。

    **不放完整路徑。** 那是一串上百字元的絕對路徑，會把清單撐出一條橫向捲軸，
    而每一列前面那一大段又完全相同 —— 想分辨哪一份是哪一份，得先橫向捲到最後。
    完整路徑放 tooltip（由 `MaintenancePage.refresh()` 設），刪除的確認框也會念出來
    —— 那才是真的需要「確定是這一個」的時刻。

    **壞掉的備份也要有時間。** `validate_backup()` 一發現問題就回傳，`created_at`
    來自清單檔所以是空的 —— 於是壞掉那幾列開頭是一個空欄位。而使用者正是在
    「這幾份都壞了，該刪哪一份」的時候需要那個時間。資料夾名字本身就帶著時間戳
    （`backup_20260821_204129_147229`），讀不到清單檔時就用它。

    資料夾名看起來跟時間欄重複，但它多了秒與微秒 —— 同一分鐘內建立的兩份備份
    在時間欄上長得一模一樣，靠它才分得開。
    """
    path = Path(str(item["path"]))
    created = str(item.get("created_at") or "").strip()
    when = display_datetime(created) if created else _time_from_backup_id(path.name)
    state = backup_state_text(bool(item["valid"]), item.get("error_code"))
    return f"{when}｜{state}｜{path.name}"


def _time_from_backup_id(name: str) -> str:
    """`backup_20260821_204129_147229` → `2026/08/21 20:41`，認不出來就原樣回傳。"""
    parts = name.split("_")
    if len(parts) >= 3 and parts[0] == "backup":
        try:
            stamp = datetime.strptime(f"{parts[1]}{parts[2]}", "%Y%m%d%H%M%S")
        except ValueError:
            return name
        return stamp.strftime("%Y/%m/%d %H:%M")
    return name


def display_datetime(value: str) -> str:
    """給備份清單用：到分鐘。

    這裡**要顯示時間**，跟 `display_date()` 刻意相反 —— 同一天可以有好幾份備份，
    只印日期就分不出哪一份是哪一份。（交易那邊的時分秒是程式補的，所以不印。）
    """
    try:
        return datetime.fromisoformat(value).strftime("%Y/%m/%d %H:%M")
    except ValueError:
        return value


def error_text(exc: BaseException, *, fallback: str) -> str:
    """把「訊息就是錯誤碼」的例外翻成中文，翻不出來就用 `fallback`。

    有些地方在送出之前就自己解析輸入（待確認頁、模板對話框），例外沒有經過
    `application/failures.py`。以前那些地方直接印 `str(exc)`，於是畫面上會出現
    `金額無效（Amount must be greater than zero.）` —— 全中文介面裡的一句英文。

    走同一張表，訊息才會跟服務層回的一致。
    """
    return message_for(str(exc)) or fallback


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
