# Changelog

## 0.6.2 - 資料與程式位置分離

- 帳務資料移出程式所在位置，改到 `<資料根目錄>`；專案資料夾之後若推上 remote 只會公開程式。
- `system_paths.json` 新增 `data_root` 與 `settings_version`。`ledger_dir` 與 `backup_dir` 現在必須都在 `data_root` 底下，違反時丟 `PATH_OUTSIDE_DATA_ROOT`。
- `exports/`、`logs/`、`tmp/` 改由 `data_root` 推導，不再由 `ledger_dir.parent` 推導 —— 舊做法讓 `ledger_dir` 的深度決定另外三個資料夾長在哪。
- **修正路徑搬移的順序缺陷**：舊版先寫指標檔才搬資料庫，搬移失敗時指標已指向新位置而資料還在舊位置，下次啟動會建一個空資料庫、看起來像資料消失。現在改為「先複製 → 寫指標檔 → 才刪舊檔」，任何一步失敗都會清掉半成品並保持原狀。
- 指標檔改用「寫暫存檔再 `os.replace`」的原子寫入，避免寫到一半損毀。
- 新增 `tests/integration/test_data_paths.py`（7 個測試），涵蓋 `data_root` 約束、舊設定檔相容、搬移失敗回滾，以及 Windows 路徑大小寫語意。
- 移除 `CODEX.md`；`AGENTS.md` 成為 agent 規則的唯一正本，`CLAUDE.md` 指向它。
- 新增 `.claude/settings.json` 的讀寫邊界規則，與 `Verify.ps1` 的路徑漂移檢查。
- 新增 `Verify.ps1`：一鍵跑漂移檢查 ＋ ruff ＋ mypy --strict ＋ pytest。

## 0.6.1 - Phase 4.1

- 將 PySide6 UI 統一為專業深藍深色主題。
- 新增 `apply_dark_theme(app)`，統一設定 `Fusion` style、字體、palette 與 QSS。
- 修正 `QTabWidget/QTabBar` 未選取分頁文字與背景對比不足。
- 側邊欄與備份清單改用不同 objectName，避免全域 `QListWidget` 樣式污染。
- 新增主要/危險按鈕角色樣式與 UI smoke 測試。
- README、CODEX、Roadmap、Requirements、Architecture 與 Release Checklist 依 Phase 4.1 重新整理。
- 清理文件編碼與閱讀順序，當前規格文件維持 UTF-8 可讀內容。

## 0.6.0 - Phase 4

- 側邊欄重整為 6 個主頁：快速記帳、餘額盤點、待確認、交易紀錄、操作設定、系統設定。
- 新增外部系統路徑設定，分離記帳資料路徑與備份路徑。
- 備份改為手動建立；移除啟動自動備份。
- 還原/重製前保護備份改為使用者勾選。
- 新增重製目前記帳資料功能。
- 帳戶、類別、項目新增「刪除未使用」。
- UI 用詞改為「類別／項目」。
- 移除「對象／商家」與 payee schema/runtime/UI/tests。
- Schema v5 重建交易 FTS，只搜尋備註、類別/項目與帳戶。
- README、CODEX 與 docs 依 Phase 4 重新整理。

## 0.4.0 - Phase 3

- 新增餘額盤點與未解釋差額追蹤。
- Schema v4 新增 `balance_snapshots`。
- 新增盤點列表、差額交易列表、盤點 CSV 匯出。
- 啟動後可提醒今日尚未盤點預設帳戶。

## 0.3.0 - Phase 1–2

- 交易列表新增組合篩選與雙向分頁。
- 新增原子轉帳替換。
- 新增帳戶與類別恢復。
- 新增模板、週期排程、待確認項目。
- 新增備份驗證、還原與 CSV 匯出。

## 0.2.0 - Stable core

- SQLite 成為主資料庫。
- 建立帳戶、類別、交易、posting、allocation、audit 與 FTS。
- 移除 CSV/JSON runtime store。

## 0.1.0 - 原型

- 初版快速記帳原型與歷史文件，已封存於 `docs/archive/phase-0-2/`。
