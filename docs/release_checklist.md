# Release Checklist

## 功能

- 快速記帳、交易列表、餘額盤點、待確認、操作設定、系統設定可啟動。
- 帳戶、類別、項目可新增、重新命名、封存、恢復、刪除未使用。
- 手動備份、驗證、還原、重製與 CSV 匯出可用。
- 資料路徑與備份路徑可分開設定，危險路徑會被拒絕。
- UI 不出現「對象／商家」「分類」「細項」。

## Schema

- migration 可從 v1 跑到最新版本。
- 較新 schema 會被拒絕。
- v5 後沒有 payees table 與 payee 欄位。

## 驗證

```powershell
python -m ruff check --no-cache .
python -m mypy --no-incremental src
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest -q
```

## 效能

```powershell
$env:TAGCOR_RUN_PERFORMANCE = "1"
python -m pytest -q tests\performance\test_large_ledger.py
```

目標：新增交易 < 200ms、最近交易頁 < 300ms、常用篩選 < 500ms。