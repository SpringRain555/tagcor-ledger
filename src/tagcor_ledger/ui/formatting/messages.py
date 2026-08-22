"""給人看的一句話：操作結果、例外翻譯、備份清單那一列。

**頁面自己的一次性訊息不在這裡**（「備份已建立：…」「CSV 已匯出：…」這類），
那些只出現一次、只屬於那一頁，搬過來只會讓這個模組變成所有中文字的倉庫。
分界是**「這句話會不會在別的地方也要用同一個講法」**。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from tagcor_ledger.application.failures import message_for
from tagcor_ledger.ui.formatting.primitives import display_datetime



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


def error_text(exc: BaseException, *, fallback: str) -> str:
    """把「訊息就是錯誤碼」的例外翻成中文，翻不出來就用 `fallback`。

    有些地方在送出之前就自己解析輸入（待確認頁、模板對話框），例外沒有經過
    `application/failures.py`。以前那些地方直接印 `str(exc)`，於是畫面上會出現
    `金額無效（Amount must be greater than zero.）` —— 全中文介面裡的一句英文。

    走同一張表，訊息才會跟服務層回的一致。
    """
    return message_for(str(exc)) or fallback
