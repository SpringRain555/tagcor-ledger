# Architecture Overview

```text
PySide6 UI
  → LedgerController
  → application services / Result
  → infrastructure stores / SQLite / backup / CSV
  → domain models
```

## 分層

- `domain`：純模型與 Money，不依賴 Qt 或 SQLite。
- `application`：交易、設定、帳戶/類別、模板/排程、盤點、備份/還原/重製 use cases。
- `infrastructure`：SQLite schema migration、store、backup API、CSV export。
- `ui`：PySide6 widgets 與 controller。
- `app`：啟動、路徑、外部系統設定。

## 資料流

UI 不直接操作 SQL。所有 UI 操作透過 controller 呼叫 application service。service 回傳 `Result`，UI 將錯誤顯示為繁體中文訊息。

## Phase 4 邊界

- 系統路徑設定在 SQLite 外部，因為資料庫路徑本身不能可靠存放在資料庫內。
- payee 已移除；「項目」負責描述具體收支項目，備註負責補充說明。
- 備份只由明確手動操作觸發。

## Phase 4.1 UI 主題

- UI 固定使用深色主題，由 `tagcor_ledger.ui.theme.apply_dark_theme(app)` 套用。
- 主題入口負責設定 `Fusion` style、QPalette、字體與 `styles.qss`。
- `styles.qss` 使用專業深藍色系，並明確覆蓋分頁、下拉選單、表格、清單、訊息框、狀態列與捲軸。
- 不同用途的 Qt 元件不可只靠全域 selector；側邊欄使用 `sidebarNavigation`，備份清單使用 `backupList`。
- 字體採本機 fallback，不打包字型檔。
