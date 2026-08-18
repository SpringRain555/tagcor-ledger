# 錯誤碼目錄

**本檔的權威範圍：** 每一個錯誤碼的成因，以及**使用者該怎麼做**。

清單由 `tests/unit/test_error_codes.py` 用 AST 掃描原始碼比對，**程式裡有而這裡沒有的碼會讓測試失敗**。
所以這份文件不會悄悄過期。反過來，這裡有而程式沒有的碼，代表功能被移除了但文件忘了刪，測試也會報。

錯誤碼是**給開發者看的穩定識別字**，不是給使用者看的訊息。UI 顯示的一律是繁體中文訊息，
錯誤碼只出現在日誌與診斷資訊裡。

`Result` 同時帶 `correlation_id`，回報問題時附上它就能在日誌裡找到對應的那一次操作。

---

## 帳戶

| 錯誤碼 | 成因 | 使用者該怎麼做 |
|---|---|---|
| `ACCOUNT_NAME_REQUIRED` | 帳戶名稱空白 | 填名稱 |
| `ACCOUNT_NOT_FOUND` | 指定的帳戶不存在 | 通常是資料不一致；重開程式，仍有問題就匯出診斷資訊 |
| `ACCOUNT_ACTIVE_NAME_CONFLICT` | 已有同名的使用中帳戶 | 換名字，或先把同名的封存 |
| `ACCOUNT_NOT_ACTIVE` | 想用一個已封存的帳戶記帳 | 先恢復該帳戶，或改選別的 |
| `ACCOUNT_IS_DEFAULT` | 想刪掉預設帳戶 | 先到操作設定改預設帳戶，再刪 |
| `ACCOUNT_IN_USE` | 想刪掉已被歷史交易引用的帳戶 | **改用封存。** 刪除只允許從未被引用過的 |
| `ACCOUNT_CREATE_FAILED` / `ACCOUNT_RENAME_FAILED` / `ACCOUNT_ARCHIVE_FAILED` / `ACCOUNT_RESTORE_FAILED` / `ACCOUNT_DELETE_FAILED` | 上述操作在寫入層失敗 | 看 `details.reason`；多半是底下某個更具體的錯誤 |

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
| `CATEGORY_CREATE_FAILED` / `CATEGORY_RENAME_FAILED` / `CATEGORY_ARCHIVE_FAILED` / `CATEGORY_RESTORE_FAILED` / `CATEGORY_DELETE_FAILED` | 上述操作在寫入層失敗 | 看 `details.reason` |

## 交易

| 錯誤碼 | 成因 | 使用者該怎麼做 |
|---|---|---|
| `ENTRY_TYPE_INVALID` | 流向不是收入／支出／轉帳 | UI 正常操作不會發生；發生代表有 bug |
| `DATETIME_TIMEZONE_REQUIRED` | 時間字串沒有時區 | 同上。本專案固定 `Asia/Taipei` |
| `VALIDATION_FAILED` | 泛用的輸入驗證失敗 | 看 `details.reason` 找出實際原因 |
| `TRANSACTION_NOT_FOUND` | 交易不存在 | 可能已被刪除或資料庫被換過 |
| `TRANSACTION_VOIDED` | 想編輯一筆已作廢的交易 | 作廢不可復原。要改就新建一筆 |
| `TRANSACTION_REVISION_CONFLICT` | 樂觀鎖衝突 —— 這筆在你編輯期間被別處改過 | 重新載入交易紀錄再改一次 |
| `TRANSACTION_STATUS_FILTER_INVALID` | 篩選的狀態值不合法 | UI 正常操作不會發生 |
| `TRANSACTION_UPDATE_FAILED` | 更新在寫入層失敗 | 看 `details.reason` |
| `LIST_TRANSACTIONS_FAILED` | 查詢失敗 | 多半是資料庫層問題；匯出診斷資訊 |
| `PAGE_LIMIT_INVALID` | 每頁筆數不在允許範圍 | 只接受 20／50／100 |

## 轉帳

| 錯誤碼 | 成因 | 使用者該怎麼做 |
|---|---|---|
| `TRANSFER_SAME_ACCOUNT` | 來源與目的是同一個帳戶 | 選不同的帳戶 |
| `TRANSFER_DESTINATION_REQUIRED` | 沒選轉入帳戶 | 選一個 |
| `TRANSFER_EDIT_NOT_SUPPORTED` | 想就地編輯轉帳 | **這是刻意的。** 轉帳用「替換」流程：建新的、作廢舊的，同一個 SQLite transaction 完成 |
| `TRANSFER_NOT_FOUND` | 要替換的轉帳不存在 | 重新載入 |
| `TRANSFER_NOT_ACTIVE` | 要替換的轉帳已作廢 | 已作廢的不能再替換 |
| `TRANSFER_REPLACE_FAILED` | 替換流程失敗 | **舊轉帳未變更。** 看 `details.reason` |
| `CURRENCY_MISMATCH` | 兩個帳戶幣別不同 | 目前只支援同幣別 TWD 轉帳 |

## 餘額盤點

| 錯誤碼 | 成因 | 使用者該怎麼做 |
|---|---|---|
| `BALANCE_SNAPSHOT_NEGATIVE` | 填了負數的實際金額 | 盤點金額不能是負的 |
| `BALANCE_SNAPSHOT_NOT_FOUND` | 盤點不存在 | 重新載入 |
| `BALANCE_SNAPSHOT_STATUS_FILTER_INVALID` | 篩選狀態值不合法 | UI 正常操作不會發生 |
| `BALANCE_SNAPSHOT_VALIDATION_FAILED` | 輸入驗證失敗 | 看 `details.reason` |
| `BALANCE_SNAPSHOT_UPDATE_FAILED` / `BALANCE_SNAPSHOT_LIST_FAILED` / `BALANCE_SNAPSHOT_EXPORT_FAILED` | 對應操作失敗 | 看 `details.reason` |
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
| `TEMPLATE_SAVE_FAILED` / `TEMPLATE_ARCHIVE_FAILED` / `SCHEDULE_SAVE_FAILED` / `SCHEDULE_ARCHIVE_FAILED` / `SCHEDULE_GENERATE_FAILED` / `OCCURRENCE_CONFIRM_FAILED` / `OCCURRENCE_SKIP_FAILED` / `OCCURRENCE_UPDATE_FAILED` | 對應操作失敗 | 看 `details.reason` |

## 設定

| 錯誤碼 | 成因 | 使用者該怎麼做 |
|---|---|---|
| `DEFAULT_ACCOUNT_NOT_ACTIVE` | 想把已封存的帳戶設成預設 | 先恢復該帳戶 |
| `SETTINGS_ENTRY_TYPE_INVALID` | 預設流向值不合法 | UI 正常操作不會發生 |
| `SETTINGS_PAGE_SIZE_INVALID` | 每頁筆數不合法 | 只接受 20／50／100 |
| `SETTINGS_SAVE_FAILED` | 設定寫入失敗 | 看 `details.reason` |

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
| `PATH_SETTINGS_SAVE_FAILED` | 路徑設定儲存失敗 | **舊設定與舊資料都沒有變動。** 看 `details.reason` |
| `DATABASE_SCHEMA_TOO_NEW` | 資料庫版本比程式支援的新 | **不要繼續使用，先更新程式。** 用舊程式開新資料庫會壞資料 |
| `DATABASE_WRITE_FAILED` | 寫入交易時資料庫層失敗 | 磁碟滿、檔案被鎖、資料庫損毀都可能。匯出診斷資訊 |

---

## 加新錯誤碼的規矩

1. 碼要是**穩定的英文大寫識別字**，不要因為訊息改了就改碼。
2. 加完之後**這份文件要同步加一列**，否則 `tests/unit/test_error_codes.py` 會失敗。
3. 「使用者該怎麼做」那一欄不能寫「請聯絡開發者」—— 這是單人使用的本機工具，開發者就是使用者。
   寫不出可執行的動作，代表這個錯誤的設計還沒想清楚。
