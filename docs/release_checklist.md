# Release Checklist

## 功能

- 資產總覽、記帳、待確認、交易紀錄、餘額盤點、法規參考、操作設定、系統設定八頁都可啟動。
- 開啟程式停在資產總覽；總資產等於各「使用中」帳戶餘額相加。
- 操作設定六個分頁：帳戶／類別／項目／模板／定期收支／定存。
- 有子項目的類別在「類別」分頁有自己的一列，可選取、可改名。
- 定存合約與期可新增、修改、刪除；到期與領息只出現在「待確認」頁，不自動入帳。
- 待確認是**一張表**，「來源」欄分得出定期收支與定存；確認與略過各自開對的流程；
  「全部確認」只處理定期收支，並講清楚還剩幾件定存。
- 待確認為空時顯示「這頁是做什麼的」那段說明，**不是一張空表格加三顆停用的按鈕**。
- 法規庫檔案不存在時，記帳不受影響，法規頁顯示怎麼建立而不是報錯。
- 帳戶、類別、項目可新增、重新命名、封存、恢復、刪除未使用。
- 手動備份、驗證、還原、刪除、重製與 CSV 匯出可用。
- 備份清單不出現英文錯誤碼、不出現橫向捲軸；壞掉的備份刪得掉，而且刪完清單真的少一列。
- 資料路徑與備份路徑可分開設定，危險路徑會被拒絕。
- UI 不出現「對象／商家」「分類」「細項」「快速記帳」「週期排程」。
- 側邊欄沒有任何點不動的字（沒有分組標題）。
- UI 固定深色主題可讀；分頁、下拉選單、表格、備份清單、彈窗與狀態列不出現文字/背景同色。
- 側邊欄與備份清單使用不同 objectName，避免 `QListWidget` 樣式污染。

## 架構

- `tests/unit/test_architecture.py` 全過：分層邊界（domain 的依賴、PySide6 只在 `ui/`、
  依賴方向、`ui/` 無 SQL）與 700 行模組上限。
- 新增頁面放在 `ui/pages/`，跨頁連動只寫在 `ui/main_window.py`。
- 新增 store 方法放在對應的 `infrastructure/stores/<聚合>.py`，不要塞回 `sqlite_store.py`。
- **要建立交易就呼叫 `StoreBase._write_transaction()` / `_write_transfer()`**，
  不要自己寫 `INSERT INTO transactions`。需要跟別的表同一個 transaction 時把
  `connection` 傳進去就好 —— 那正是那兩個函式收 `connection` 而不是自己開的原因。

## Schema

- migration 可從 v1 跑到最新版本。
- 較新 schema 會被拒絕。
- v5 後沒有 payees table 與 payee 欄位。
- **沒有任何卡內餘額概念**（`stored_value`／`card_balance`／`icash` 這類表或欄位）——
  電子票證只記儲值當下的支出，見 `AGENTS.md`。
- 加了新表或新欄位就更新 `docs/architecture/data-model.md` 的 migration registry。
  **v0.9.1 的 v7 漏了這一步**，glossary 有同步而 data-model 沒有，到收尾才發現。

## 例外處理與可觀測性

- 五種故障各跑一次，每種都要有繁中訊息、日誌有紀錄、程式不無聲死掉：
  改壞 `system_paths.json`、`ledger_dir` 指到不存在的磁碟、schema 版本改成 99、
  開兩個實例、備份目錄設成唯讀。
- `logs/app.log` 內**不得出現任何金額或備註**；診斷資訊匯出檔同理（測試會擋）。
- 新增熱查詢時，`tests/integration/test_query_plans.py` 要跟著加一條 —— 並且
  **實際拿掉索引驗證它會紅**，否則那條守門可能什麼都沒檢查。
- 新的啟動失敗分支要同時更新 `app/startup.py`、`error-codes.md`、
  `state-machines.md` §6 與 `tests/integration/test_startup_failures.py`。

## 驗證

```powershell
python -m ruff check --no-cache .
python -m mypy --no-incremental src
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest -q
```

## 文件

- README、AGENTS、Roadmap、Changelog、Requirements、Architecture 互相一致。
- `.\Verify.ps1` 全過（含路徑漂移檢查、錯誤碼目錄同步、文件連結、繁體中文守門）。
- 有新錯誤碼的話，`docs/architecture/error-codes.md` 已同步（測試會擋）。
- 有新狀態或新轉移的話，`docs/architecture/state-machines.md` 已同步。
- 有新用詞的話，`docs/architecture/glossary.md` 已同步。
- **改了頁面名稱或操作設定的分頁名**，`docs/architecture/ui-workflows.md` 的頁面地圖
  已跟著改（`tests/unit/test_docs_drift.py` 逐字比對，漏了會紅）。新增一頁時，
  頁面地圖那一列的**「不在這裡做的事」不可留空** —— 那一欄才是這張表存在的理由。
- 踩到坑的話，`docs/lessons.md` 已追加一筆。
- Markdown 以 UTF-8 儲存；當前規格文件不得出現 mojibake 或替換字元。
- `docs/archive/phase-0-2/` 僅供追溯，不作為目前規格來源。

## 效能

```powershell
$env:TAGCOR_RUN_PERFORMANCE = "1"
python -m pytest -q tests\performance\test_large_ledger.py
```

目標（20 萬筆）：新增交易 < 200ms、最近交易頁 < 300ms、常用篩選 < 500ms、
建立盤點 < 500ms、未解釋差額 < 500ms、列出帳戶餘額 < 500ms、**開啟資產總覽 < 1s**。

資產總覽是唯一一項**每次切過去都重算**的，所以它必須被量著。它的成本幾乎就是
「列出帳戶餘額 ＋ 未解釋差額」，其餘幾項（定存、收件匣、設定）的筆數與資料量無關。
