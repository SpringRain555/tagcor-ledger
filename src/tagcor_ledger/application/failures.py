"""把底層丟出來的例外翻成使用者看得懂的失敗。

## 為什麼有這個檔

寫入層（`infrastructure/stores/`）、路徑驗證（`app/path_settings.py`）、備份
（`infrastructure/maintenance.py`）與金額解析（`domain/money.py`）失敗時，
丟的都是**訊息就是錯誤碼**的例外：

    raise ValueError("ACCOUNT_IS_DEFAULT")

以前應用層的每一個 `except` 都把它塌成一個籠統的 `*_FAILED`，再把 `str(exc)`
塞進 `details["reason"]` —— 而 `ui/formatting.result_message()` 會把 reason 用
括號接在畫面訊息後面。使用者於是看到：

    帳戶無法刪除；預設帳戶或已有歷史資料的帳戶請改用封存。（ACCOUNT_IS_DEFAULT）

那句中文同時指控兩件事，真正發生的是哪一件只寫在後面那串英文裡。更糟的是金額：
`MoneyError` 以前帶的是英文散文，於是全中文的畫面上會出現

    請檢查交易內容。（Amount must be greater than zero.）

**問題不是那串英文難看，是畫面上唯一講清楚失敗原因的東西只有那串英文。**

## 這裡怎麼做

反過來：**底層的碼就是這次操作的錯誤碼**，每個碼有自己的一句話。翻不出來的
（`sqlite3.Error` 的原文、沒收錄的碼）才退回呼叫端給的 `fallback_code`，
原文放 `details["detail"]` —— 那個 key **不會**被印在畫面上。

## `ERROR_MESSAGES` 的範圍

只收**會以例外形式冒出來**的碼。服務自己 `Result.fail("CODE", "中文")` 當場回的
碼不收，那些訊息就在它們自己的呼叫處，收進來會變成同一個碼有兩個講法。

表裡的句子是那個碼的**預設說法**。呼叫端可以用 `overrides` 給更貼近當下情境的
說法（例如 `CATEGORY_NAME_REQUIRED` 在「類別」與「項目」兩個分頁該說不同的話）。

加一個新的 `raise ValueError("SOME_CODE")` 卻沒有在這裡加一列，
`tests/unit/test_failure_messages.py` 會紅。
"""

from __future__ import annotations

from collections.abc import Mapping
import sqlite3

from tagcor_ledger.application.result import Result
from tagcor_ledger.infrastructure.stores.base import NotFoundError


DOMAIN_FAILURES: tuple[type[BaseException], ...] = (ValueError, NotFoundError)
"""「這次操作的內容有問題」或「要動的東西不在了」—— 兩者都翻得出使用者能懂的一句話。

**`NotFoundError` 繼承 `RuntimeError` 不是 `ValueError`**（`stores/base.py`），
所以它一定要自己列出來 —— 這是 2026-08-22 盤點時發現 15 個 handler 漏掉它的原因。
**`MoneyError` 不必列** —— 它繼承 `ValueError`，寫上去只是雜訊。

用在**兩層寫入路徑**的第一層：交易與餘額盤點的寫入區分「內容有問題」與「資料庫寫不進去」，
後者要另外講一句「什麼都沒變」，所以不能跟前者共用一個 handler。
"""

STORE_FAILURES: tuple[type[BaseException], ...] = (*DOMAIN_FAILURES, sqlite3.Error)
"""寫入層可能丟出來的**全部**東西。用在單層 handler —— 包一個 store 呼叫，交給 `failure()`。

`failure()` 認得出碼就用那個碼的中文，認不出來（`sqlite3.Error` 的英文原文）才退回
呼叫端給的 `fallback_code`。所以這三種擺在同一個 handler 裡不會混淆，
它們的分歧在 `failure()` 內部處理。

**`sqlite3.IntegrityError` 不必列** —— 它繼承 `sqlite3.Error`。
"""


ERROR_MESSAGES: dict[str, str] = {
    # ---- 金額（domain/money.py）----
    "AMOUNT_FORMAT_INVALID": "金額只能填數字，不要加逗號、單位或空白。",
    "AMOUNT_NOT_POSITIVE": "金額要大於 0。",
    "AMOUNT_NOT_A_STRING": "金額的內部格式不對。這是程式的問題，請匯出診斷資訊回報。",
    "CURRENCY_UNSUPPORTED": "目前只支援台幣（TWD）。",
    "CURRENCY_FRACTION_UNSUPPORTED": "台幣沒有角與分，金額請填整數元。",
    # ---- 帳戶 ----
    "ACCOUNT_NAME_REQUIRED": "請輸入帳戶名稱。",
    "ACCOUNT_NOT_FOUND": "找不到這個帳戶，它可能已經被刪除。請重新整理後再試一次。",
    "ACCOUNT_ACTIVE_NAME_CONFLICT": (
        "已經有一個使用中的帳戶叫這個名字了。請換一個名字，或直接用既有的那一個。"
    ),
    "ACCOUNT_NOT_ACTIVE": "這個帳戶已經封存，不能拿來記帳。請先恢復它，或改選別的帳戶。",
    "ACCOUNT_IS_DEFAULT": (
        "這是預設帳戶，不能刪除。請先到「操作設定」把預設帳戶改成別的，再回來刪。"
    ),
    "ACCOUNT_IN_USE": (
        "這個帳戶已經有交易紀錄，不能刪除。請改用「封存」—— 歷史交易會留著，"
        "帳戶則不再出現在選單裡。"
    ),
    "DESTINATION_ACCOUNT_NOT_ACTIVE": (
        "轉入帳戶已經封存了。請先恢復那個帳戶，或改掉這筆待確認項目的轉入帳戶。"
    ),
    # ---- 類別與項目 ----
    "CATEGORY_NAME_REQUIRED": "請輸入名稱。",
    "CATEGORY_NOT_FOUND": "找不到這個類別／項目，它可能已經被刪除。請重新整理後再試一次。",
    "CATEGORY_ACTIVE_NAME_CONFLICT": (
        "同一層裡已經有一個使用中的項目叫這個名字了。請換一個名字 ——"
        "不同類別底下可以同名。"
    ),
    "CATEGORY_NOT_ACTIVE": "這個類別／項目已經封存，不能拿來記帳。請先恢復它，或改選別的。",
    "CATEGORY_PARENT_INVALID": (
        "所屬類別不存在或已封存。請先在「類別」分頁選一個使用中的類別 —— 只有第一層"
        "能當所屬類別，沒有第三層。"
    ),
    "CATEGORY_PARENT_NOT_ACTIVE": "所屬類別已經封存了。請先恢復它，再恢復這個項目。",
    "CATEGORY_HAS_CHILDREN": "這個類別底下還有項目，不能刪除。請先處理掉所有子項目。",
    "CATEGORY_HAS_ACTIVE_CHILDREN": (
        "這個類別底下還有使用中的項目，不能封存。請先把子項目封存 —— 否則會出現"
        "「類別封存了、項目還在選單裡」的矛盾。"
    ),
    "CATEGORY_IN_USE": "這個類別／項目已經有交易紀錄，不能刪除。請改用「封存」。",
    "SORT_SPEC_PAGE_UNKNOWN": "這一頁沒有可以記住的排序設定。正常操作不會發生，請回報。",
    "REORDER_LIST_STALE": (
        "清單在排序視窗開著的時候變了，順序沒有存下來。請關掉這個視窗、重新打開一次"
        "再排 —— 直接存下去會把新增或刪掉的那一筆弄丟位置。"
    ),
    # ---- 交易 ----
    "TRANSACTION_NOT_FOUND": "找不到這筆交易，它可能已經被刪除。請重新整理交易紀錄。",
    "TRANSACTION_VOIDED": "這筆交易已經作廢了，不能再修改。要更正就新增一筆。",
    "TRANSACTION_REVISION_CONFLICT": (
        "這筆交易在你編輯的期間被改過了。請重新整理交易紀錄，確認現在的內容之後再改一次。"
    ),
    "TRANSACTION_STATUS_FILTER_INVALID": "狀態篩選值不合法。正常操作不會發生，請回報。",
    "PAGE_LIMIT_INVALID": "每頁筆數只接受 20、50 或 100。",
    "ENTRY_TYPE_INVALID": "流向只能是收入、支出或轉帳。正常操作不會發生，請回報。",
    "DATETIME_TIMEZONE_REQUIRED": "時間缺少時區。正常操作不會發生，請回報。",
    # ---- 轉帳 ----
    "TRANSFER_SAME_ACCOUNT": "轉出與轉入不能是同一個帳戶。",
    "TRANSFER_DESTINATION_REQUIRED": "請選擇轉入帳戶。",
    "TRANSFER_EDIT_NOT_SUPPORTED": (
        "轉帳不能直接改。請用「替換」—— 它會建一筆新的、作廢舊的，兩件事在同一次"
        "寫入裡完成。"
    ),
    "TRANSFER_NOT_FOUND": "找不到要替換的轉帳。請重新整理交易紀錄。",
    "TRANSFER_NOT_ACTIVE": "這筆轉帳已經作廢了，不能再替換。",
    "CURRENCY_MISMATCH": "兩個帳戶的幣別不同。目前只支援同幣別（TWD）的轉帳。",
    # ---- 餘額盤點 ----
    "BALANCE_SNAPSHOT_NEGATIVE": "盤點金額不能是負數。",
    "BALANCE_SNAPSHOT_NOT_FOUND": "找不到這筆餘額盤點。請重新整理。",
    "BALANCE_SNAPSHOT_STATUS_FILTER_INVALID": "狀態篩選值不合法。正常操作不會發生，請回報。",
    # ---- 模板 ----
    "TEMPLATE_ID_REQUIRED": (
        "這個模板沒有識別碼，無法儲存。正常操作不會發生，請匯出診斷資訊回報。"
    ),
    "TEMPLATE_NAME_REQUIRED": "請輸入名稱。",
    "TEMPLATE_AMOUNT_INVALID": "金額格式不正確。可以留空（套用時再填），但填了就要是整數元。",
    "TRANSACTION_DRAFT_INVALID": "收入與支出都要選類別。",
    "TRANSFER_DRAFT_INVALID": "轉帳要有轉入帳戶，而且不要選類別。",
    "TEMPLATE_NOT_FOUND": "找不到這個模板。請重新整理。",
    "TEMPLATE_ACTIVE_NAME_CONFLICT": (
        "已經有一個使用中的模板叫這個名字了。請先把那一個改名，或改名之後再恢復這一個。"
    ),
    # ---- 設定 ----
    "DEFAULT_ACCOUNT_NOT_ACTIVE": "已封存的帳戶不能設成預設帳戶。請先恢復它。",
    # ---- 系統路徑 ----
    "LEDGER_BACKUP_PATH_SAME": (
        "記帳資料夾與備份資料夾不能是同一個。（Windows 比對路徑不分大小寫，"
        "只改大小寫不算不同）"
    ),
    "LEDGER_BACKUP_PATH_NESTED": (
        "記帳資料夾與備份資料夾不能互相包含。請設成兩個平輩的資料夾。"
    ),
    "PATH_OUTSIDE_DATA_ROOT": "記帳資料夾與備份資料夾都必須在資料根目錄底下。",
    "SYSTEM_PATH_NOT_WRITABLE": (
        "資料夾建不出來或寫不進去。請確認磁碟已連接、權限足夠、空間還夠。"
    ),
    "SYSTEM_PATH_SETTINGS_INVALID": (
        "路徑設定檔不是合法的 JSON。把 system_paths.json 刪掉就會退回預設路徑，"
        "帳務資料不會損失。"
    ),
    "TARGET_LEDGER_ALREADY_EXISTS": (
        "目標資料夾裡已經有一個帳本檔了。請換一個空資料夾，或先處理掉那一份。"
    ),
    # ---- 定存 ----
    "DEPOSIT_NAME_REQUIRED": "請輸入合約名稱。",
    "DEPOSIT_TERM_MONTHS_INVALID": "期長要是正整數月，例如一年填 12。",
    "DEPOSIT_PRINCIPAL_INVALID": "本金不能是負數。",
    "DEPOSIT_MATURITY_BEFORE_START": "到期日必須晚於起存日。請檢查起存日與期長。",
    "DEPOSIT_CONTRACT_NOT_FOUND": "找不到這份定存合約。請重新整理定存頁。",
    "DEPOSIT_TERM_NOT_FOUND": "找不到這一期。請重新整理定存頁。",
    "DEPOSIT_EVENT_NOT_FOUND": "找不到這筆定存項目。請重新整理。",
    "DEPOSIT_EVENT_NOT_PENDING": (
        "這筆定存項目已經確認或略過了，不能再改 —— 兩者都是終點。"
        "要改結果就去作廢它產生的交易。"
    ),
    "DEPOSIT_CONTRACT_IN_USE": (
        "這個定存已經有入帳紀錄，不能刪除。請改用「結束合約」—— 否則帳本裡那些"
        "交易會失去來歷。"
    ),
    "DEPOSIT_TERM_NOT_EDITABLE": (
        "只有「存續中」的期可以修改。已續約或已結清的期已經產生過交易，改了會對不起帳。"
    ),
    # `DEPOSIT_TERM_NOT_ACTIVE` 與 `DEPOSIT_MATURITY_CANNOT_BE_SKIPPED` **不在這裡** ——
    # 它們是服務自己 `Result.fail()` 當場回的，訊息就寫在那兩個呼叫處（見本檔開頭
    # 「`ERROR_MESSAGES` 的範圍」）。收進來會變成同一個碼有兩個講法。
    "DEPOSIT_CONTRACT_HAS_ACTIVE_TERM": (
        "這份定存還有存續中的一期，不能直接結束 —— 那筆本金會從清單上消失而帳上不動。"
        "要提前結束請用「中途解約」；要等它到期就在「待確認」確認到期。"
    ),
    # ---- 備份（infrastructure/maintenance.py）----
    # 這一組是 `validate_backup()` **回傳**的，不是 raise 的（見測試裡的
    # RAISED_INDIRECTLY），只有 `BACKUP_INTEGRITY_FAILED` 兩種形式都有。
    "BACKUP_FILES_MISSING": (
        "這個備份資料夾裡少了檔案（要有 backup_manifest.json 與 ledger.sqlite3）。"
        "請改用別的備份。"
    ),
    "BACKUP_MANIFEST_INVALID": "這個備份的清單檔讀不開或不是合法的 JSON。請改用別的備份。",
    "BACKUP_CHECKSUM_MISMATCH": (
        "這個備份的檔案內容與清單裡記的雜湊對不起來 —— 檔案在備份之後被改過或損毀了。"
        "請不要還原它，改用別的備份。"
    ),
    "BACKUP_INTEGRITY_FAILED": (
        "資料庫完整性檢查沒過，這份備份是壞的。請不要還原它，改用別的備份。"
    ),
    "BACKUP_SCHEMA_MISSING": (
        "這個備份裡讀不到資料庫版本，檔案可能不是本程式建立的。請改用別的備份。"
    ),
    "BACKUP_NOT_FOUND": (
        "找不到這份備份，它可能已經被刪掉或搬走了。請按「重新整理」更新清單。"
    ),
    "BACKUP_OUTSIDE_BACKUP_DIR": (
        "只能刪除備份資料夾底下的備份。外部資料夾裡的備份請自己在檔案總管處理 ——"
        "程式不去動它管理範圍以外的檔案。"
    ),
    "BACKUP_SCHEMA_TOO_NEW": (
        "這份備份是用比較新的版本建立的，不能用現在這個版本還原 ——"
        "用舊程式寫新結構的資料庫會弄壞資料。請先把程式更新到最新版。"
    ),
}
"""錯誤碼 → 使用者看得懂的一句話。**不含**服務自己當場回的碼（見模組 docstring）。"""


def message_for(code: str) -> str | None:
    """查一個錯誤碼的中文說法，查不到回 `None`。"""
    return ERROR_MESSAGES.get(code)


def failure(
    exc: BaseException,
    *,
    fallback_code: str,
    fallback_message: str,
    correlation_id: str | None = None,
    overrides: Mapping[str, str] | None = None,
) -> Result:
    """把例外翻成 `Result`。

    `str(exc)` 認得出來就用**那個碼**與它的句子；認不出來（`sqlite3.Error` 的
    原文、還沒收錄的碼）才用 `fallback_code`，並把原文放進 `details["detail"]`。

    **原文一律不進 `details["reason"]`** —— `result_message()` 只印 `message`，
    reason 這個 key 已經沒有人讀了，留著只會讓下一個人以為它還會顯示。
    """
    code = str(exc).strip()
    message = (overrides or {}).get(code) or ERROR_MESSAGES.get(code)
    if message is None:
        return Result.fail(
            fallback_code,
            fallback_message,
            details={"detail": str(exc)},
            correlation_id=correlation_id,
        )
    return Result.fail(code, message, correlation_id=correlation_id)
