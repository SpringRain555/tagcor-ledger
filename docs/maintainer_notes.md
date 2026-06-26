# 維護者筆記

## 驗證 Python

優先使用 `tagcor-ledger` Conda 環境。若環境尚未同步 PySide6，可先更新 `environment.yaml`，不要以重新加入 PyQt6 解決。

## Workspace Hygiene

- `.local-data*`、SQLite smoke data、cache、build 與 dist 不提交。
- 不提交使用者帳務資料、備份、匯出或絕對機器路徑。
- schema 變更必須新增 migration，不可直接假設新資料庫。

## 效能

禁止以 Python 載入全部交易後排序或搜尋。新增常用篩選時先確認 query plan 與索引。

## 已移除相容層

舊 PyQt6、TagPath、CSV/JSON runtime 與 importer 不得重新加入。若需處理 0.1.x 資料，使用 0.2.0 做一次性 SQLite 轉換。

## 排程

- 不建立背景程序或 Windows 工作排程。
- 產生 occurrence 時必須遵守 366 期上限與唯一 `(schedule_id, due_date)`。
- 確認 occurrence 與帳務寫入必須在同一 SQLite transaction。

## 餘額盤點

- 盤點是實際金額 snapshot，不是交易、調整或對帳完成狀態。
- 不得讓盤點寫入 `account_postings`；差額必須依查詢時的有效交易重新計算。
- 若未來加入「轉成調整交易」，必須作為獨立使用者動作並保留 audit。
