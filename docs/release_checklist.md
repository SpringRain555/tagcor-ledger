# Release Checklist

## 功能

- 快速記帳、交易列表、餘額盤點、待確認、操作設定、系統設定可啟動。
- 帳戶、類別、項目可新增、重新命名、封存、恢復、刪除未使用。
- 手動備份、驗證、還原、重製與 CSV 匯出可用。
- 資料路徑與備份路徑可分開設定，危險路徑會被拒絕。
- UI 不出現「對象／商家」「分類」「細項」。
- UI 固定深色主題可讀；分頁、下拉選單、表格、備份清單、彈窗與狀態列不出現文字/背景同色。
- 側邊欄與備份清單使用不同 objectName，避免 `QListWidget` 樣式污染。

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

## 文件

- README、AGENTS、Roadmap、Changelog、Requirements、Architecture 互相一致。
- `.\Verify.ps1` 全過（含路徑漂移檢查、錯誤碼目錄同步、文件連結、繁體中文守門）。
- 有新錯誤碼的話，`docs/architecture/error-codes.md` 已同步（測試會擋）。
- 有新狀態或新轉移的話，`docs/architecture/state-machines.md` 已同步。
- 有新用詞的話，`docs/architecture/glossary.md` 已同步。
- 踩到坑的話，`docs/lessons.md` 已追加一筆。
- Markdown 以 UTF-8 儲存；當前規格文件不得出現 mojibake 或替換字元。
- `docs/archive/phase-0-2/` 僅供追溯，不作為目前規格來源。

## 效能

```powershell
$env:TAGCOR_RUN_PERFORMANCE = "1"
python -m pytest -q tests\performance\test_large_ledger.py
```

目標：新增交易 < 200ms、最近交易頁 < 300ms、常用篩選 < 500ms。
