# 錯誤碼目錄

**本檔的權威範圍：** 每一個錯誤碼的成因，以及**使用者該怎麼做**。

清單由 `tests/unit/test_error_codes.py` 用 AST 掃描原始碼比對，**程式裡有而這裡沒有的碼會讓測試失敗**。
所以這份文件不會悄悄過期。反過來，這裡有而程式沒有的碼，代表功能被移除了但文件忘了刪，測試也會報。

錯誤碼是**給開發者看的穩定識別字**，不是給使用者看的訊息。UI 顯示的一律是繁體中文訊息，
錯誤碼只出現在日誌與診斷資訊裡。

`Result` 同時帶 `correlation_id`，回報問題時附上它就能在日誌裡找到對應的那一次操作。

## 兩種碼，兩種責任

| | 誰產生 | 中文訊息寫在哪 |
|---|---|---|
| **具體碼**（`ACCOUNT_IS_DEFAULT`、`AMOUNT_NOT_POSITIVE`…） | 寫入層／驗證層 `raise ValueError("碼")` | [`application/failures.py`](../../src/tagcor_ledger/application/failures.py) 裡的錯誤碼對照表 |
| **`*_FAILED` 退路碼** | 應用層，**只在具體碼翻不出來時** | 呼叫處的 `fallback_message=` |

`failure()` 認得出 `str(exc)` 就用**那個具體碼**與它的句子；認不出來（`sqlite3.Error`
的原文、還沒收錄的碼）才退回 `*_FAILED`，原文放 `details["detail"]`。

**`details["reason"]` 已經廢除。** 以前應用層把 `str(exc)` 塞進去，而
`result_message()` 會把它用括號接在畫面訊息後面 —— 於是使用者看到
「帳戶無法刪除；預設帳戶或已有歷史資料的帳戶請改用封存。（`ACCOUNT_IS_DEFAULT`）」，
一句同時指控兩件事的中文，真正發生的那件只寫在後面的英文裡。
`details["detail"]` **永遠不顯示**，它是給日誌與人工排查看的。

---

## 金額

金額解析在 `domain/money.py`。**這一組最常被看到** —— 打錯金額是最普通的操作失誤。

| 錯誤碼 | 成因 | 使用者該怎麼做 |
|---|---|---|
| `AMOUNT_FORMAT_INVALID` | 不是合法的十進位數字（有逗號、單位、空白、指數） | 只填數字。`1,200` 要寫成 `1200` |
| `AMOUNT_NOT_POSITIVE` | 不允許 0 的欄位填了 0 | 填大於 0 的金額。**負數不會走到這裡** —— 減號在格式那一關就被擋掉，回的是上面那個碼 |
| `AMOUNT_NOT_A_STRING` | 傳進來的不是字串 | UI 正常操作不會發生 —— 這是程式的問題 |
| `CURRENCY_UNSUPPORTED` | 幣別不在幣別對照表裡 | 目前只有 TWD。同上，正常操作不會發生 |
| `CURRENCY_FRACTION_UNSUPPORTED` | 台幣填了小數 | 填整數元。TWD 的 scale 是 0，沒有角與分 |

## 帳戶

| 錯誤碼 | 成因 | 使用者該怎麼做 |
|---|---|---|
| `ACCOUNT_NAME_REQUIRED` | 帳戶名稱空白 | 填名稱 |
| `ACCOUNT_OPENING_BALANCE_INVALID` | 期初餘額不是整數元 | 只填數字，不要逗號或單位。留空當 0 |
| `ACCOUNT_NOT_FOUND` | 指定的帳戶不存在 | 通常是資料不一致；重開程式，仍有問題就匯出診斷資訊 |
| `ACCOUNT_ACTIVE_NAME_CONFLICT` | 已有同名的使用中帳戶（新增或恢復時） | **多半是本來就想用那一個** —— 直接在選單裡選它。真要兩個就換名字 |
| `ACCOUNT_NOT_ACTIVE` | 想用一個已封存的帳戶記帳 | 先恢復該帳戶，或改選別的 |
| `ACCOUNT_IS_DEFAULT` | 想刪掉預設帳戶 | 先到操作設定改預設帳戶，再刪 |
| `ACCOUNT_IN_USE` | 想刪掉已被歷史交易引用的帳戶 | **改用封存。** 刪除只允許從未被引用過的 |
| `ACCOUNT_CREATE_FAILED` / `ACCOUNT_RENAME_FAILED` / `ACCOUNT_ARCHIVE_FAILED` / `ACCOUNT_RESTORE_FAILED` / `ACCOUNT_DELETE_FAILED` | **退路碼**：寫入層失敗，而且原因不是上面任何一個 | 匯出診斷資訊回報。原文在 `details.detail` |
| `DESTINATION_ACCOUNT_NOT_ACTIVE` | 待確認的轉帳，轉入帳戶已封存 | 恢復那個帳戶，或改掉這筆待確認項目的轉入帳戶 |

## 類別與項目

| 錯誤碼 | 成因 | 使用者該怎麼做 |
|---|---|---|
| `CATEGORY_NAME_REQUIRED` | 名稱空白 | 填名稱 |
| `CATEGORY_NOT_FOUND` | 指定的類別／項目不存在 | 同 `ACCOUNT_NOT_FOUND` |
| `CATEGORY_ACTIVE_NAME_CONFLICT` | 同一層已有同名的使用中項目 | 換名字。**同層才會衝突**，不同父類別下可以同名 |
| `CATEGORY_NOT_ACTIVE` | 想用已封存的類別記帳 | 先恢復，或改選別的 |
| `CATEGORY_PARENT_INVALID` | 指定的父類別不是第一層 | 只有第一層能當父。**沒有第三層** |
| `CATEGORY_PARENT_NOT_ACTIVE` | 父類別已封存 | 先恢復父類別 |
| `CATEGORY_HAS_CHILDREN` | 想刪掉還有子項目的類別 | 先處理掉所有子項目 |
| `CATEGORY_HAS_ACTIVE_CHILDREN` | 想封存還有使用中子項目的類別 | 先封存子項目。否則會出現「父封存了、子還在選單裡」的矛盾 |
| `CATEGORY_IN_USE` | 想刪掉已被歷史交易引用的 | **改用封存** |
| `CATEGORY_REQUIRED` | 收入／支出沒選類別 | 選一個。轉帳不需要類別 |
| `CATEGORY_CREATE_FAILED` | **預期外**的寫入失敗。名稱空白、上層無效、同層同名這三種都已經有自己的碼，走到這裡表示三道檢查都沒攔到 | 匯出診斷資訊回報。原文在 `details.detail`，**不會印在畫面上** |
| `CATEGORY_REORDER_DIFFERENT_PARENT` | 想把項目移到**別的類別**底下的位置 | 調整順序只在同一組之內。換類別是另一件事，這裡不做 |
| `CATEGORY_REORDER_PLACE_INVALID` | `place` 不是 `before` 或 `after` | 正常操作不會發生（UI 只送這兩個值）；回報 |
| `CATEGORY_RENAME_FAILED` / `CATEGORY_ARCHIVE_FAILED` / `CATEGORY_RESTORE_FAILED` / `CATEGORY_DELETE_FAILED` / `CATEGORY_REORDER_FAILED` | **退路碼**：寫入層失敗，而且原因不是上面任何一個 | 匯出診斷資訊回報。原文在 `details.detail` |

## 交易

| 錯誤碼 | 成因 | 使用者該怎麼做 |
|---|---|---|
| `ENTRY_TYPE_INVALID` | 流向不是收入／支出／轉帳 | UI 正常操作不會發生；發生代表有 bug |
| `DATETIME_TIMEZONE_REQUIRED` | 時間字串沒有時區 | 同上。本專案固定 `Asia/Taipei` |
| `VALIDATION_FAILED` | **退路碼**：輸入驗證失敗，而且認不出是哪一種 | 匯出診斷資訊回報。**這個碼出現代表分類漏了一種情形**，該補一個具體的碼 |
| `TRANSACTION_NOT_FOUND` | 交易不存在 | 可能已被刪除或資料庫被換過 |
| `TRANSACTION_VOIDED` | 想編輯一筆已作廢的交易 | 作廢不可復原。要改就新建一筆 |
| `TRANSACTION_REVISION_CONFLICT` | 樂觀鎖衝突 —— 這筆在你編輯期間被別處改過 | 重新載入交易紀錄再改一次 |
| `TRANSACTION_STATUS_FILTER_INVALID` | 篩選的狀態值不合法 | UI 正常操作不會發生 |
| `TRANSACTION_UPDATE_FAILED` | **退路碼**：更新失敗，原因認不出來 | 匯出診斷資訊回報 |
| `LIST_TRANSACTIONS_FAILED` | **退路碼**：查詢失敗 | 多半是資料庫層問題；匯出診斷資訊 |
| `PAGE_LIMIT_INVALID` | 每頁筆數不在允許範圍 | 只接受 20／50／100 |

## 轉帳

| 錯誤碼 | 成因 | 使用者該怎麼做 |
|---|---|---|
| `TRANSFER_SAME_ACCOUNT` | 來源與目的是同一個帳戶 | 選不同的帳戶 |
| `TRANSFER_DESTINATION_REQUIRED` | 沒選轉入帳戶 | 選一個 |
| `TRANSFER_EDIT_NOT_SUPPORTED` | 想就地編輯轉帳 | **這是刻意的。** 轉帳用「替換」流程：建新的、作廢舊的，同一個 SQLite transaction 完成 |
| `TRANSFER_NOT_FOUND` | 要替換的轉帳不存在 | 重新載入 |
| `TRANSFER_NOT_ACTIVE` | 要替換的轉帳已作廢 | 已作廢的不能再替換 |
| `TRANSFER_REPLACE_FAILED` | **退路碼**：替換流程失敗 | **舊轉帳未變更。** 匯出診斷資訊回報 |
| `CURRENCY_MISMATCH` | 兩個帳戶幣別不同 | 目前只支援同幣別 TWD 轉帳 |

## 餘額盤點

| 錯誤碼 | 成因 | 使用者該怎麼做 |
|---|---|---|
| `BALANCE_SNAPSHOT_NEGATIVE` | 填了負數的實際金額 | 盤點金額不能是負的 |
| `BALANCE_SNAPSHOT_NOT_FOUND` | 盤點不存在 | 重新載入 |
| `BALANCE_SNAPSHOT_STATUS_FILTER_INVALID` | 篩選狀態值不合法 | UI 正常操作不會發生 |
| `BALANCE_SNAPSHOT_VALIDATION_FAILED` | **退路碼**：輸入驗證失敗，認不出是哪一種 | 匯出診斷資訊回報 |
| `BALANCE_SNAPSHOT_UPDATE_FAILED` / `BALANCE_SNAPSHOT_LIST_FAILED` / `BALANCE_SNAPSHOT_EXPORT_FAILED` | **退路碼**：對應操作失敗 | 匯出診斷資訊回報 |
| `BALANCE_GAP_LOAD_FAILED` / `BALANCE_GAP_TRANSACTIONS_FAILED` | 差額或期間交易查詢失敗 | 匯出診斷資訊 |

## 模板、排程與待確認

| 錯誤碼 | 成因 | 使用者該怎麼做 |
|---|---|---|
| `AUTOMATION_NAME_REQUIRED` | 模板／排程沒有名稱 | 填名稱 |
| `AUTOMATION_AMOUNT_INVALID` | 金額格式不對 | 金額可留空（套用時再填），但填了就要合法 |
| `TRANSACTION_DRAFT_INVALID` | 收入／支出的草稿缺類別 | 選類別 |
| `TRANSFER_DRAFT_INVALID` | 轉帳草稿缺轉入帳戶，或誤填了類別 | 轉帳要有轉入帳戶、不要類別 |
| `TEMPLATE_NOT_FOUND` / `SCHEDULE_NOT_FOUND` | 不存在 | 重新載入 |
| `SCHEDULE_FREQUENCY_INVALID` | 頻率不是每日／每週／每月／每年 | 選合法的頻率 |
| `SCHEDULE_INTERVAL_INVALID` | 間隔倍數不合法 | 要是正整數 |
| `OCCURRENCE_NOT_PENDING` | 想修改一筆已確認或已略過的待確認項目 | 兩者都是終點。要改結果就去作廢它產生的交易 |
| `OCCURRENCE_AMOUNT_REQUIRED` | 確認時金額還是空的 | 填金額才能入帳 |
| `TEMPLATE_SAVE_FAILED` / `TEMPLATE_ARCHIVE_FAILED` / `SCHEDULE_SAVE_FAILED` / `SCHEDULE_ARCHIVE_FAILED` / `SCHEDULE_GENERATE_FAILED` / `OCCURRENCE_CONFIRM_FAILED` / `OCCURRENCE_SKIP_FAILED` / `OCCURRENCE_UPDATE_FAILED` | **退路碼**：對應操作失敗，原因認不出來 | 匯出診斷資訊回報 |

## 設定

| 錯誤碼 | 成因 | 使用者該怎麼做 |
|---|---|---|
| `DEFAULT_ACCOUNT_NOT_ACTIVE` | 想把已封存的帳戶設成預設 | 先恢復該帳戶 |
| `SETTINGS_ENTRY_TYPE_INVALID` | 預設流向值不合法 | UI 正常操作不會發生 |
| `SETTINGS_PAGE_SIZE_INVALID` | 每頁筆數不合法 | 只接受 20／50／100 |
| `SETTINGS_SAVE_FAILED` | **退路碼**：設定寫入失敗 | 匯出診斷資訊回報 |

## 系統路徑與資料庫

**這一組最重要 —— 它們發生在啟動階段，處理不好等於資料看起來消失。**

| 錯誤碼 | 成因 | 使用者該怎麼做 |
|---|---|---|
| `LEDGER_BACKUP_PATH_SAME` | 記帳路徑與備份路徑相同 | 設成兩個不同的資料夾。**Windows 路徑比對不分大小寫**，只改大小寫不算不同 |
| `LEDGER_BACKUP_PATH_NESTED` | 兩個路徑互相包含 | 設成平輩資料夾 |
| `PATH_OUTSIDE_DATA_ROOT` | `ledger_dir` 或 `backup_dir` 不在 `data_root` 底下 | 五個資料夾都必須在資料根目錄內 |
| `SYSTEM_PATH_NOT_WRITABLE` | 資料夾建不出來或寫不進去 | 檢查磁碟是否連接、權限是否足夠、空間是否夠 |
| `SYSTEM_PATH_SETTINGS_INVALID` | `system_paths.json` 不是合法 JSON | **刪掉它會退回預設路徑**，不會損失帳務資料 |
| `TARGET_LEDGER_ALREADY_EXISTS` | 搬移目標已經有一個資料庫檔 | 換一個空資料夾，或先處理掉目標位置那一份 |
| `PATH_SETTINGS_SAVE_FAILED` | **退路碼**：路徑設定儲存失敗，而且原因不是這一節其他任何一個 | **舊設定與舊資料都沒有變動。** 匯出診斷資訊回報 |
| `DATABASE_SCHEMA_TOO_NEW` | 資料庫版本比程式支援的新 | **不要繼續使用，先更新程式。** 用舊程式開新資料庫會壞資料 |
| `DATABASE_WRITE_FAILED` | 寫入交易時資料庫層失敗 | 磁碟滿、檔案被鎖、資料庫損毀都可能。匯出診斷資訊 |

---

## 啟動失敗

這一組的特點是**使用者還沒看到主視窗**。所以訊息只能靠對話框或 stderr，而且每一則都必須
自己講完「發生什麼事、接下來按什麼」—— 沒有介面可以讓人摸索。

分支定義在 `state-machines.md` §6，實作在 `app/startup.py`。

| 錯誤碼 | 成因 | 使用者該怎麼做 |
|---|---|---|
| `ALREADY_RUNNING` | 同一份帳本已經有實例在跑，**而且叫不動它的視窗** | 切換到那個視窗。找不到視窗就是上次沒正常關閉，等幾秒再開。（正常情況會直接把既有視窗叫到最前面，看不到這個錯誤） |
| `DATA_DIRECTORY_UNAVAILABLE` | 資料夾不存在或無法存取 | **最常見是外接磁碟沒接。** 接上再開；資料夾真的搬走了就刪掉路徑設定檔退回預設 |
| `DATA_DIRECTORY_NOT_WRITABLE` | 資料夾唯讀或權限不足（`PermissionError`） | 確認資料夾不是唯讀，也沒被防毒軟體鎖住 |
| `DISK_FULL` | 磁碟已滿（`errno 28`） | 清出空間後再開 |
| `DATABASE_LOCKED` | 資料庫被鎖住 | 確認沒有第二個視窗，也沒有備份／同步軟體正在讀寫該檔案 |
| `DATABASE_CORRUPT` | 資料庫檔案損毀或不是資料庫 | 用最近一次可用備份還原。**先把損毀檔另存一份**，有時仍能救回部分資料 |
| `DATABASE_UNAVAILABLE` | 其他 `sqlite3.DatabaseError` | 確認檔案存在且沒被佔用，並匯出診斷資訊 |
| `STARTUP_FAILED` | 認不出來的啟動例外 | 提供日誌檔。**這個碼出現代表分類漏了一種情形**，應該補一個更明確的分支 |

## 定存

| 錯誤碼 | 成因 | 使用者該怎麼做 |
|---|---|---|
| `DEPOSIT_NAME_REQUIRED` | 合約沒有名稱 | 填名稱 |
| `DEPOSIT_METHOD_INVALID` | 計息方式或到期轉存方式不是允許的值 | UI 正常操作不會發生 |
| `DEPOSIT_TERM_MONTHS_INVALID` | 期長不是正整數 | 填月數，例如一年是 12 |
| `DEPOSIT_PRINCIPAL_INVALID` | 本金是負數 | 本金不能是負的 |
| `DEPOSIT_AMOUNT_INVALID` | 本金或每月存入金額格式不對 | 只接受整數元，不要加逗號或單位 |
| `DEPOSIT_MATURITY_BEFORE_START` | 到期日不晚於起存日 | 檢查起存日與期長 |
| `DEPOSIT_MONTHLY_DEPOSIT_REQUIRED` | 零存整付沒填每月存入金額 | 零存整付就是每月存一筆，這個欄位必填 |
| `DEPOSIT_INTEREST_DESTINATION_REQUIRED` | 沒指定利息轉入哪個帳戶 | 選一個帳戶。**只有「本息續存」不需要**，因為利息留在定存裡 |
| `DEPOSIT_CONTRACT_NOT_FOUND` / `DEPOSIT_TERM_NOT_FOUND` / `DEPOSIT_EVENT_NOT_FOUND` | 對應資料不存在 | 重新整理定存頁 |
| `DEPOSIT_EVENT_NOT_PENDING` | 想處理一件已確認或已略過的項目 | 兩者都是終點。要改結果就去作廢它產生的交易 |
| `DEPOSIT_AMOUNT_REQUIRED` | 確認時沒有金額，而且利率空白算不出建議值 | **照存摺填實際金額。** 或先回定存頁補上年利率 |
| `DEPOSIT_CONTRACT_IN_USE` | 想刪掉已經有入帳紀錄的定存 | **改用「結束合約」。** 刪除只允許從未入帳過的，否則帳本裡的交易會失去來歷 |
| `DEPOSIT_TERM_NOT_EDITABLE` | 想修改已續約或已結清的期 | 只有「存續中」的期能改。已經產生過交易的改了會對不起帳 |
| `DEPOSIT_CONTRACT_CREATE_FAILED` / `DEPOSIT_CONTRACT_UPDATE_FAILED` / `DEPOSIT_CONTRACT_DELETE_FAILED` / `DEPOSIT_TERM_UPDATE_FAILED` / `DEPOSIT_GENERATE_FAILED` / `DEPOSIT_CONFIRM_FAILED` | **退路碼**：對應操作失敗，原因認不出來 | 匯出診斷資訊回報 |

## 備份

`validate_backup()` 把碼放在**回傳值**裡（`{"valid": False, "error_code": …}`），
還原時才轉成例外。**這一組每一個都是「不要用這份備份」** ——
所以每一句都要講清楚該改用別的，不要只說「失敗」。

| 錯誤碼 | 成因 | 使用者該怎麼做 |
|---|---|---|
| `BACKUP_FILES_MISSING` | 資料夾裡少了 `backup_manifest.json` 或 `ledger.sqlite3` | 改用別的備份 |
| `BACKUP_MANIFEST_INVALID` | 清單檔讀不開或不是合法 JSON | 改用別的備份 |
| `BACKUP_CHECKSUM_MISMATCH` | 檔案雜湊與清單記的對不起來 —— 備份之後被改過或損毀 | **不要還原。** 改用別的備份 |
| `BACKUP_INTEGRITY_FAILED` | 資料庫完整性檢查沒過 | **不要還原。** 建立備份時就出現的話，代表當下複製出來的那一份是壞的 |
| `BACKUP_SCHEMA_MISSING` | 讀不到 `schema_migrations`，檔案可能不是本程式建的 | 改用別的備份 |
| `BACKUP_SCHEMA_TOO_NEW` | 備份是用比較新的版本建立的 | **先更新程式再還原。** 用舊程式寫新結構會弄壞資料 |
| `BACKUP_NOT_FOUND` | 要刪的備份資料夾已經不在了 | 按「重新整理」更新清單 |
| `BACKUP_OUTSIDE_BACKUP_DIR` | 要刪的資料夾不在備份資料夾底下 | **程式只清自己管的地方。** 外部資料夾的備份請自己在檔案總管處理 |
| `BACKUP_DELETE_FAILED` | **退路碼**：刪除失敗，多半是檔案被鎖住 | 關掉可能在讀那個資料夾的程式（防毒、雲端同步、另一個視窗）再試 |

> 刪除**不檢查備份有沒有效** —— 檢查了就變成「壞掉的備份刪不掉」，而使用者想刪的
> 八成就是壞的那一份。要不要留由確認框上的資訊決定：它會念出這一份是什麼，
> 以及刪掉之後還剩幾份可用的備份。

## 法規參考庫

法規庫是**選用的**。沒有它記帳完全不受影響，所以這兩個錯誤都不會擋住程式啟動。

| 錯誤碼 | 成因 | 使用者該怎麼做 |
|---|---|---|
| `REFERENCE_LIBRARY_MISSING` | `reference/reference.sqlite3` 不存在 | 依畫面指示跑 `tools/law_sync/` 的三支腳本建立。**不建也可以**，只是法規頁沒東西 |
| `REFERENCE_LIBRARY_UNREADABLE` | 檔案在但讀不開（損毀、權限不足） | 刪掉它重新產生 —— 它是產生物，沒有任何不可重建的內容 |

## 診斷資訊

| 錯誤碼 | 成因 | 使用者該怎麼做 |
|---|---|---|
| `DIAGNOSTICS_BUILD_FAILED` | 蒐集診斷資訊時失敗 | 通常是資料庫讀不到；確認磁碟已連接 |
| `DIAGNOSTICS_WRITE_FAILED` | 診斷檔寫不進 `exports/` | 確認匯出資料夾存在且可寫、磁碟有空間 |

---

## 加新錯誤碼的規矩

1. 碼要是**穩定的英文大寫識別字**，不要因為訊息改了就改碼。
2. 加完之後**這份文件要同步加一列**，否則 `tests/unit/test_error_codes.py` 會失敗。
3. 「使用者該怎麼做」那一欄不能寫「請聯絡開發者」—— 這是單人使用的本機工具，開發者就是使用者。
   寫不出可執行的動作，代表這個錯誤的設計還沒想清楚。
