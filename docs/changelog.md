# Changelog

## 0.8.0 - 例外處理與可觀測性

- **修正一鍵啟動器被新日誌打斷**：`Launch.ps1` 原本用 `2>&1` 把兩條串流合起來再解析 JSON，
  Stage 4 的啟動日誌一寫到 stderr 就讓它解析失敗。程式本身沒問題（`--json` 的 stdout
  仍是純 JSON），是啟動器不該混串流。改用 `Start-Process` 分開收，並新增
  `tests/integration/test_cli_output.py` 把這個契約釘住。

出錯時看得到訊息，也留得下紀錄。在這之前是**全專案零日誌、零 crash 處理**。

- **啟動失敗的六種分支全部實作**（`app/startup.py`）：設定檔損毀、路徑越界、資料夾不可用、
  磁碟滿、資料庫被鎖／損毀、schema 太新、已有實例在跑。每一種都給**可執行的**繁中指示 ——
  例如設定檔損毀會明講「刪掉它會退回預設路徑，不會損失帳務資料」。
  `--gui` 用 Qt 對話框，Qt 起不來就退回 stderr。
- **日誌**（`app/logging_setup.py`）：`logs/app.log`，1 MB × 5 輪替，UTF-8 無 BOM。
  **不記金額也不記備註**，只記操作名稱、錯誤碼、`correlation_id`、時間，所以可以直接交出去。
  日誌路徑分兩段決定：解析得出 `AppPaths` 就寫進去，解析不出來（設定檔壞了正是最常見的
  啟動失敗原因）就退回作業系統標準位置，避免最需要紀錄的那次失敗剛好沒有紀錄。
- **全域例外攔截**（`ui/error_handler.py`）：Qt slot 丟出的例外不再讓視窗無聲消失，
  改成寫日誌 ＋ 顯示含 `correlation_id` 的對話框，**可以繼續使用**。
- **單一實例守門**（`app/single_instance.py`）：用 `filelock` 在 `ledger_dir` 放 advisory
  lock。這把原本宣告了卻沒人用的依賴變成有用的依賴。鎖綁在 `ledger_dir` 上，
  所以指向不同資料夾的實例互不干擾；殘留的鎖檔不會擋住下次啟動。
- **診斷資訊匯出**（系統設定 → 備份與還原）：版本、schema 版本、七個路徑、
  `integrity_check`、各表筆數、最近 200 行日誌。**不含任何金額、備註或帳戶名稱。**
- 新增 24 個測試：REQ-0009 的五種驗收故障、日誌與診斷檔的隱私守門、
  以及熱查詢的 `EXPLAIN QUERY PLAN` 守門。
- 錯誤碼目錄新增「啟動失敗」與「診斷資訊」兩節，共 10 個新錯誤碼（總計 93）。
- 錯誤碼抽取器現在也看 `StartupFailure(...)` 與 `error_code=` 關鍵字。
- 架構守門的 Qt 檢查範圍改成「`ui/` 以外全部」—— 原本只掃四個子套件，
  根目錄的 `main.py` 漏掉了，而 Stage 4 正好差點在那裡 import PySide6。

## 未發布 - 一鍵啟動與快速記帳欄位修正

- **修正快速記帳與模板／排程對話框的孤兒標籤**：流向不是轉帳時仍會顯示「轉入帳戶」標籤。
  成因是 `QFormLayout` 的標籤是獨立 widget，舊寫法只對欄位 `setVisible`，改用 `setRowVisible`
  一起收掉整列。這是 Phase 1–2 就存在的缺陷，2026-08-18 實機試用時發現。
  `tests/ui/test_main_window.py` 已加測試鎖住，並實際退回舊寫法確認測試會失敗。

- 新增 `啟動 TagCor Ledger.cmd` 與 `Launch.ps1`：雙擊即可開程式，不需要先開終端機或
  `conda activate`。用絕對路徑呼叫環境直譯器，並清掉繼承來的 `VIRTUAL_ENV`／`PYTHONPATH`。
  已在乾淨環境與刻意重現的 venv 污染環境下各實測通過。
- `Launch.ps1 -CreateShortcut` 可在桌面建立捷徑；`TAGCOR_PYTHON` 可覆寫直譯器位置。
- **修正 `[project.gui-scripts]` 指向錯誤的函式。** 它原本指向 `main:main`，而 `main()`
  少了 `--gui` 只會印文字然後結束 —— `gui-scripts` 產生的 exe 沒有主控台，所以雙擊
  `tagcor-ledger.exe` 的實際效果是「什麼都沒發生」。改指向新的 `main_gui()`。
- 新增 `tests/unit/test_entrypoints.py` 守住上述兩者，以及 `.ps1` 的 BOM 與 `.cmd` 的純 ASCII。

## 0.7.0 - 徹底重構（行為零改變）

**這一版沒有任何功能變更。** 50 個既有測試斷言一個字都沒改，全部通過 —— 那是「純搬移」的證明。

- `ui/main_window_phase12.py`（2,114 行、13 個畫面類）拆成 `ui/pages/` 底下 12 個檔案，
  一個檔案一個畫面；共用的表格與表單 helper 移到 `ui/widgets/`，顯示字串集中到 `ui/formatting.py`。
  `MainWindow` 移到 `ui/main_window.py`，檔名不再帶 `phase12` 這種歷史痕跡。
- `infrastructure/sqlite_store.py`（1,381 行）依聚合拆成 `infrastructure/stores/` 底下的
  `base`／`accounts`／`categories`／`transactions`／`balance`。`LedgerStore` 對外的方法一個沒少。
- 新增 `tests/unit/test_architecture.py`：用 AST 守住分層邊界（domain 不得認得 Qt／SQLite／其他層、
  只有 `ui/` 可以 import PySide6、依賴方向只能由外往內、`ui/` 不得出現 SQL），
  以及單一模組 700 行上限。四個守門都實際注入違規驗證過會失敗。
- mypy 的 PySide6 放寬範圍縮小：從整個 `main_window_phase12` 改成只放寬真的碰 Qt 的模組，
  且改用 `disallow_subclassing_any = false` 取代整組 `misc`。`ui/controller.py` 與
  `ui/formatting.py` 現在維持完整 `--strict`。
- 移除 `package-data` 指向不存在的 `resources/icons/`。
- 繁體中文守門字表改用專案外的 204 個繁體 Markdown 驗證，移除三個誤報：`承`、`殖`、`璃`。

## 未發布 - 文件骨架

- 新增 `docs/architecture/state-machines.md`：八個狀態機的完整轉移表，含刻意不做的推論。
  記錄了 `EntryType.ADJUSTMENT` 自 v1 起空置至今，作為「先加著以後再說」的實例。
- 新增 `docs/architecture/error-codes.md`：**83 個錯誤碼**全部有成因與「使用者該怎麼做」。
  由 `tests/unit/test_error_codes.py` 用 AST 掃描比對，程式與文件不同步會讓測試失敗。
- 新增 `docs/architecture/glossary.md`：用詞對照表，含「不要叫成什麼」與「刻意不存在的詞」。
- 新增 `docs/operations/go-live-2026-09.md`：九月上線操作清單，不需寫任何程式。
- 新增 REQ-0006～REQ-0010 與 ADR-0004～ADR-0009。
- `docs/index.md` 改寫：加入人類與 LLM 兩條閱讀路線，以及每份文件的權威範圍。
- 新增 `docs/research/`：市面產品調查（Stage 1），17 個來源含 SHA-256 與抓取時間。
- 新增 `tools/fetch.py`：有節奏紀律與出處紀錄的擷取器，Stage 6 法規庫沿用。

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
