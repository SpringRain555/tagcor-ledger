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

## 檔案在哪裡

```text
src/tagcor_ledger/
├── domain/            models、money（不 import Qt、sqlite3，也不 import 其他層）
├── application/       use case、Result、settings、balance、automation
├── infrastructure/
│   ├── migrations.py  v1 → v5 的 schema
│   ├── database.py    連線（WAL、FK、busy_timeout）
│   ├── sqlite_store.py  組出 LedgerStore，本身不含 SQL
│   └── stores/        base（共用片段）＋ accounts／categories／transactions／balance
├── ui/
│   ├── controller.py  LedgerController：UI 唯一的入口
│   ├── formatting.py  dict → 顯示字串（唯一決定畫面中文長相的地方）
│   ├── main_window.py 側邊欄、頁面堆疊，以及頁面之間所有的連動
│   ├── pages/         一個檔案一個畫面
│   └── widgets/       table（RowsModel）、forms（下拉與日期）
└── app/               bootstrap、paths、path_settings、resources
```

`LedgerStore` 用繼承把 `stores/` 底下四個聚合組起來，不是委派。理由寫在
`sqlite_store.py` 的 module docstring。

`ui/pages/` 底下的頁面**彼此不 import**：要互動就往上發 Qt Signal，由 `main_window.py`
接起來。所以「按了 A 會影響 B」只會出現在一個檔案裡。

## 這些邊界由測試守著，不只是文件

`tests/unit/test_architecture.py` 用 AST 檢查四件事，違反會讓測試失敗：

| 檢查 | 規則 |
|---|---|
| `test_domain_depends_on_nothing_but_itself` | domain 不得 import Qt、sqlite3 或任何其他層 |
| `test_only_the_ui_layer_knows_about_qt` | 只有 `ui/` 可以 import PySide6 |
| `test_nothing_below_the_ui_imports_the_ui` | 依賴方向只能由外往內 |
| `test_ui_layer_contains_no_sql` | `ui/` 的字串常數不得出現 SQL |

另有 `test_no_module_grows_back_into_a_monolith`：單一模組超過 700 行就失敗。這是煙霧
偵測器不是規矩 —— 2026-08 拆檔前 `main_window_phase12.py` 長到 2,114 行、
`sqlite_store.py` 長到 1,381 行，都是沒人注意就長大的。

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
