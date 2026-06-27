# CODEX Project Context

## UI 樣式規範（Phase 4.1）

- 專案固定使用深色主題，由 `tagcor_ledger.ui.theme.apply_dark_theme(app)` 套用 `Fusion` style、字體、palette 與 `styles.qss`。
- 新增 PySide6 UI 元件時，不要用過寬的全域 QSS selector 污染不同用途元件；共用元件若用途不同，需指定 objectName。
- 側邊欄 `QListWidget` 必須使用 `sidebarNavigation`；備份清單使用 `backupList`；內容堆疊使用 `contentStack`。
- 主要操作按鈕使用 `primaryButton`；刪除、作廢、重製、還原等高風險操作使用 `dangerButton`。
- 分頁必須由 QSS 覆蓋 `QTabWidget/QTabBar` 的 selected、unselected、hover、disabled 狀態，避免回到 Qt/Windows 預設顏色。
- 字體不打包進專案，使用本機 fallback：`Segoe UI Variable`、`Segoe UI`、`Microsoft JhengHei UI`、`Microsoft JhengHei`、`Noto Sans TC`、sans-serif。
- UI 變更至少跑 `tests/ui` smoke；樣式資源變更需同步更新 `tests/unit/test_resources.py`。

請先閱讀：

1. `README.md`
2. `docs/index.md`
3. `docs/requirements/REQ-0001-stable-core.md`
4. `docs/requirements/REQ-0002-phase-1-2.md`
5. `docs/requirements/REQ-0003-balance-snapshots.md`
6. `docs/requirements/REQ-0004-phase-4-settings-paths-terms.md`
7. `docs/requirements/REQ-0005-phase-4-1-dark-ui-docs.md`
8. `docs/architecture/overview.md`
9. `docs/architecture/data-model.md`
10. `docs/architecture/ui-workflows.md`
11. `docs/architecture/storage-layout.md`
12. `docs/roadmap.md`
13. `docs/changelog.md`

## 專案定位

TagCor Ledger 是 Windows-first、本機優先的個人記帳工具。主資料庫是 SQLite；CSV 只作交換格式。介面固定使用繁體中文與 PySide6。

## 架構邊界

- `domain/`：Money、帳戶、類別、交易、模板、排程、餘額盤點模型；不得依賴 Qt 或 SQLite。
- `application/`：use case、Result、設定、備份/還原/重製協調；不得直接寫 UI。
- `infrastructure/`：SQLite migration、store、backup、CSV export。
- `ui/`：PySide6 視圖與 controller；不得直接撰寫 SQL。
- 系統路徑設定不存放在 ledger SQLite，使用外部 JSON 設定檔。

## 重要規則

- 金額一律使用 `Money(amount_minor: int, currency: str)`，禁止 float。
- 目前固定 TWD 與 Asia/Taipei。
- UI 用詞：`類別` 表示第一層，`項目` 表示第二層；不要再用「分類／細項」。
- Phase 4 已移除「對象／商家」欄位，不得新增 payee model、payees table 或 payee UI。
- 備份只能由使用者手動建立；啟動流程不得自動備份。
- 還原/重製前保護備份必須由使用者明確勾選。
- 刪除設定項只允許未被任何歷史資料引用；否則使用封存。
- 盤點不建立交易、不建立 posting、不改變帳戶餘額。

## 驗證指令

```powershell
python -m ruff check --no-cache .
python -m mypy --no-incremental src
python -m pytest -q
```

如需 UI 測試：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest -q tests\ui
```

如需效能測試：

```powershell
$env:TAGCOR_RUN_PERFORMANCE = "1"
python -m pytest -q tests\performance\test_large_ledger.py
```

## 文件維護

任何功能變更都要同步更新 README、requirements、architecture、roadmap、changelog。Markdown 一律使用 UTF-8；舊 Phase 0–2 文件只保留於 archive，不作為目前規格來源。
