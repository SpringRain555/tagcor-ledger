# Release Checklist

## 功能

- 資產總覽、記帳、待確認、交易紀錄、餘額盤點、法規參考、操作設定、系統設定八頁都可啟動。
- 開啟程式停在資產總覽；總資產等於各「使用中」帳戶餘額相加。
- 操作設定五個分頁：帳戶／類別／項目／模板／定存。
- 有子項目的類別在「類別」分頁有自己的一列，可選取、可改名。
- 定存合約與期可新增、修改、**結束合約**、刪除；期可**中途解約**。
  到期與領息只出現在「待確認」頁，不自動入帳。
- **新增定存合約時把首次起存日填成兩年多以前**（例如 2023-11-15、期長 12、
  選「本金無限次數自動轉期續存」）：對話框當場說出「目前存續中的是**第 3 期**：
  2026/02/15 – 2027/02/15」。建立之後那張「每一期」的表第一列寫的是**第 3 期**，
  而且**待確認不該多出任何東西**（ADR-0012）。
- 同樣的日期換成「不自動轉存」：說的是「這份定存已經結束」，期序是 1。
- 換成「本息無限次數自動轉期續存」：多一句「本金請填目前存摺上的金額」。
- 合約清單有「首次起存日」欄，寫的是你填的那一天（不是 2026/02/15）。
- 修改合約時「首次起存日」看得到但改不了。
- 「結束合約」對還有存續中期數的合約會被擋下來，訊息指向「中途解約」。
- 結束的合約預設不在清單上，勾「顯示已結束的合約」看得到。
- 待確認是**一張四欄的表**（到期日／定存合約／類型／建議金額），唯一的來源是定存。
  確認只問入帳日期與實際金額；**沒有「全部確認」**（批次套用試算值等於替使用者決定
  一個他沒看過的數字）。
- 「金額以存摺為準」寫在表格上方一次，不是每一列重複一遍。
- 定存頁的「產生到期與領息項目」按得動，而且按完待確認頁與側邊欄數字會跟著動。
- 待確認為空時顯示「這頁是做什麼的」那段說明，**不是一張空表格加兩顆停用的按鈕**。
- 確認入帳的對話框有**兩欄**：入帳日期（預設到期日）與實際金額。
- 對**到期**項目按「略過」會被擋下來，訊息講得出替代作法（確認、金額填 0）。
- 法規庫檔案不存在時，記帳不受影響，法規頁顯示怎麼建立而不是報錯。
- 帳戶、類別、項目可新增、重新命名、封存、恢復、刪除未使用。
- 手動備份、驗證、還原、刪除、重製與 CSV 匯出可用。
- 備份清單不出現英文錯誤碼、不出現橫向捲軸；壞掉的備份刪得掉，而且刪完清單真的少一列。
- 資料路徑與備份路徑可分開設定，危險路徑會被拒絕。
- UI 不出現「對象／商家」「分類」「細項」「快速記帳」「週期排程」「定期收支」。
  （最後兩個是**已移除的功能**，不只是舊用詞 —— 一顆通往不存在功能的按鈕比錯的用詞更糟。）
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
