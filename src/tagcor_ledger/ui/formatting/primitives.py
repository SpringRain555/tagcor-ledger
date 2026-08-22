"""金額、日期與名稱對照表 —— 每一列都用得到的那幾個轉換。

金額有兩種轉法，用錯地方會出事：

- `minor_text()` —— 給**輸入框**，純數字，因為它會被讀回來再解析。
- `group_digits()` / `signed_amount_text()` —— 給**表格**，有千分位與正負號。

TWD 沒有輔幣（`CURRENCY_SCALE = 0`），所以 minor unit 就是元；
**不要在這裡做除法**，那是把整數金額換成浮點數的第一步。
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
    """給**輸入框**用的純數字字串。不加千分位 —— 它會被原封不動讀回來再解析。"""
    return str(int(value))


def group_digits(value: int | str) -> str:
    """給**表格**用：1200 → `1,200`。純字串運算，不經過浮點數。

    三位一撇是這一欄能不能一眼比大小的關鍵。`100000` 與 `10000` 在等寬右對齊之前
    看起來只差一個字元寬度，`100,000` 與 `10,000` 一眼就分得出來。
    """
    text = str(value).strip()
    sign = ""
    # **`in ("+", "-")` 不是 `in "+-"`。** 後者是子字串判斷，而空字串是任何字串的
    # 子字串 —— `group_digits("")` 因此會進到這個分支，然後在 `text[0]` 上炸出
    # `IndexError`。目前的呼叫端都餵整數（`amount` 一律來自 `Money.to_decimal_string()`），
    # 所以那條路走不到，但這是個公開函式，「走不到」不等於「擋住了」。
    if text[:1] in ("+", "-"):
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


def display_datetime(value: str) -> str:
    """給備份清單用：到分鐘。

    這裡**要顯示時間**，跟 `display_date()` 刻意相反 —— 同一天可以有好幾份備份，
    只印日期就分不出哪一份是哪一份。（交易那邊的時分秒是程式補的，所以不印。）
    """
    try:
        return datetime.fromisoformat(value).strftime("%Y/%m/%d %H:%M")
    except ValueError:
        return value


def display_date(value: str) -> str:
    """只顯示日期。

    資料庫存的是完整時間戳，但那個時分秒是**程式補的排序用值**，不是使用者輸入的 ——
    把它印出來會讓人以為那是真的記錄時間。畫面只問到哪一天，就只顯示到哪一天。
    """
    try:
        return datetime.fromisoformat(value).strftime("%Y/%m/%d")
    except ValueError:
        return value


INBOX_SOURCE_NAMES = {"schedule": "定期", "deposit": "定存"}
"""待確認那一列是哪裡來的。**這一欄不能省** —— 兩種來源的「類型」講的是不同的事
（一邊是收入／支出／轉帳，一邊是到期／領息／存入），沒有這一欄就看不懂。"""


DEPOSIT_TERM_STATUS_NAMES = {
    "active": "存續中",
    "matured": "已到期",
    "renewed": "已續約",
    "settled": "已結清",
    "terminated": "已解約",
}


def ppm_digits(annual_rate_ppm: Any) -> str:
    """百萬分之一為單位的整數 → **沒有百分號**的數字字串。**不用浮點數。**

    1.6% 存成 16000 ppm，除以 10000 得到整數位與小數位，用字串組起來。

    這是「利率長什麼樣」的唯一實作。`rate_text()` 給表格看（加百分號、空值寫「未填」），
    `rate_input_text()` 給輸入框看（不加百分號、空值就是空的）—— 兩者只差在**外框**，
    數字本身不該有兩份算法。2026-08-22 之前 `ui/pages/deposits.py` 自己有一份
    `ppm_to_rate_text()`，內容跟這裡一模一樣。
    """
    whole, fraction = divmod(int(annual_rate_ppm), 10_000)
    return f"{whole}.{fraction:04d}".rstrip("0").rstrip(".")


def rate_text(annual_rate_ppm: Any) -> str:
    """表格裡的利率：帶百分號，沒填就寫「未填」。"""
    if annual_rate_ppm is None:
        return "未填"
    return ppm_digits(annual_rate_ppm) + "%"


def rate_input_text(annual_rate_ppm: Any) -> str:
    """輸入框裡的利率：**不帶百分號**，沒填就是空字串。

    輸入框要能直接被 `rate_to_ppm()` 讀回去，所以不能寫「未填」那種給人看的字。
    """
    if annual_rate_ppm is None:
        return ""
    return ppm_digits(annual_rate_ppm)
