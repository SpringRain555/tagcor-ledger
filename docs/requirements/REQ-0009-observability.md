# REQ-0009 例外處理與可觀測性

狀態：**已實作**（Stage 4，v0.8.0）

## 目標

出錯時看得到訊息，也留得下紀錄。

實作前的現況是**全專案零日誌、零 crash 處理**：`log_dir` 有被建立但從來沒有被寫入過，
整個 `src/` 找不到 `logging`、`sys.excepthook` 或任何 traceback 捕捉。
`main.py` 的 `initialize_database` 在任何 try 之外，所以從捷徑啟動遇到問題時，
使用者看到的是「視窗沒出現、沒有訊息、沒有紀錄」。

**實作位置**：`app/logging_setup.py`、`app/startup.py`、`app/single_instance.py`、
`ui/error_handler.py`、`ui/startup_dialog.py`、`application/diagnostics.py`。

## 功能需求

### 日誌

- `RotatingFileHandler` 寫 `logs/app.log`，UTF-8 無 BOM，1 MB × 5 份。
- **預設不記金額與備註。** 只記操作名稱、錯誤碼、`correlation_id`、時間。
  這樣日誌可以直接交出去而不外洩內容。

### 全域例外攔截

- `sys.excepthook` ＋ Qt 層攔截：寫日誌 → 跳繁中對話框（含 `correlation_id` 與日誌路徑）
  → 可繼續的錯誤不殺掉程式。

### 啟動失敗畫面

`main.py` 要包住 `bootstrap` 與 `initialize_database`，每種失敗給**可執行的**繁中指示。
六種分支列在 `docs/architecture/state-machines.md` §6。`--gui` 模式用 Qt 對話框，
Qt 不可用時退回 stderr。

### 逐項處理的例外狀況

每一種都要對到一個錯誤碼、一筆 `error-codes.md` 條目、一個測試：

- 資料庫被鎖
- 磁碟滿
- 備份目錄不可寫
- 資料庫損毀（`PRAGMA integrity_check`）
- schema 太新
- 設定檔損毀
- 路徑指向已拔除的磁碟
- **同時開兩個實例** —— 用 `filelock` 在 `ledger_dir` 放 advisory lock 做單一實例守門

> `filelock` 目前是宣告了但沒有任何程式碼使用的依賴。與其刪掉它，
> 不如拿來做單一實例守門 —— 把死依賴變成有用的依賴，同時補上一個真實的例外缺口。
> 兩個視窗各自快取餘額與待確認數量、各自跳盤點提醒，是很難 debug 的困惑來源。

### 診斷資訊匯出

系統設定加一顆按鈕，把版本、schema 版本、七個路徑、`integrity_check` 結果、
最近 N 行日誌寫成一個文字檔到 `exports/`，**不含任何金額**。

### 效能守門

對熱查詢（最近交易、篩選、盤點差額、待確認）加 `EXPLAIN QUERY PLAN` 斷言，禁止全表掃描。

## 邊界

- 日誌只寫本機，不上傳、不外送。
- 不做 crash reporter、不做遙測。
- 單一實例守門是 advisory lock，不是強制鎖；lock 檔殘留時要能自行判斷並清掉。

## 驗收

故意製造五種故障各跑一次，每種都必須**出現繁中對話框、日誌有紀錄、程式不無聲死掉**：

1. 改壞 `system_paths.json`
2. 把 `ledger_dir` 指到不存在的磁碟
3. 把資料庫的 schema 版本手動改成 99
4. 開兩個實例
5. 把備份目錄設成唯讀

另外：日誌檔不得出現任何金額；診斷資訊匯出檔不得出現任何金額。
