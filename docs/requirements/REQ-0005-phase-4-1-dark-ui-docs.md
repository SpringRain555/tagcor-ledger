# REQ-0005：Phase 4.1 深色主題、UI 可讀性與文件重整

## 目標

Phase 4.1 修正 Phase 4 後的 UI 可讀性問題，將桌面介面統一為深色主題，並整理文件入口，讓使用者與維護者能從 README 與 docs index 讀到一致規格。

## 功能需求

1. PySide6 應用固定使用深色主題，不在本階段提供亮色／暗色切換。
2. 主題入口為 `tagcor_ledger.ui.theme.apply_dark_theme(app)`，統一設定 `Fusion` style、QPalette、字體與 QSS。
3. 背景使用深灰藍／墨藍，不使用純黑作主要內容背景。
4. 主要操作按鈕使用 `primaryButton`；刪除、作廢、重製、還原等高風險操作使用 `dangerButton`。
5. `QTabWidget/QTabBar` 必須明確定義 selected、unselected、hover、disabled 狀態，避免文字與背景同色。
6. 側邊欄 `QListWidget` 使用 `sidebarNavigation`；備份清單使用 `backupList`；不得用全域 `QListWidget` 樣式混用不同用途清單。
7. 表格、下拉選單、清單、訊息框、狀態列與捲軸都需符合深色主題。
8. 字體採本機 fallback，不打包字型檔：`Segoe UI Variable`、`Segoe UI`、`Microsoft JhengHei UI`、`Microsoft JhengHei`、`Noto Sans TC`、sans-serif。
9. README、CODEX、Roadmap、Changelog、Architecture 與 Release Checklist 需同步說明 Phase 4.1。
10. Markdown 文件以 UTF-8 儲存，當前規格文件不得出現 mojibake、替換字元或不可讀歷史段落。

## 驗收

- `styles.qss` 包含深色主題 token、`QTabBar::tab`、`sidebarNavigation`、`backupList`、`primaryButton` 與 `dangerButton`。
- UI smoke 可驗證主視窗套用深色 stylesheet，且側邊欄與備份清單使用不同 objectName。
- README 的第一屏先說明專案定位、版本與目前功能，再列 UI 主題規範。
- docs index 可導向所有目前需求文件；archive 僅保留歷史，不作為目前規格來源。
- Ruff、strict mypy、pytest 與 offscreen UI smoke 通過。

## 邊界

- 本階段不加入主題切換、動畫、大型版面重設或字型檔打包。
- 本階段不重新設計帳務流程或資料模型。
