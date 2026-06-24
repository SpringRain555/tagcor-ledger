# 維護者筆記

## 驗證 Python

優先使用 `tagcor-ledger` Conda 環境。若環境尚未同步 PySide6，可先更新 `environment.yaml`，不要以重新加入 PyQt6 解決。

## Workspace Hygiene

- `.local-data*`、SQLite smoke data、cache、build 與 dist 不提交。
- 不提交使用者帳務資料、備份、匯出或絕對機器路徑。
- schema 變更必須新增 migration，不可直接假設新資料庫。

## 效能

禁止以 Python 載入全部交易後排序或搜尋。新增常用篩選時先確認 query plan 與索引。

## 相容模組

`application/transactions.py` 與舊 PyQt6 UI 檔只保留 Phase 2 相容參考；新功能放在 `transaction_service.py` 與 PySide6 v2 UI。
