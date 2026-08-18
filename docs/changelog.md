# Changelog

## 0.10.0 - 稅務與金融法規參考庫

側邊欄新增「法規參考」頁。**收 6 部法規、17 條精選條文**，涵蓋綜合所得稅、郵政儲金、
電子票證與電子支付、勞健保與贈與稅四個主題。

- 每一條都有**白話摘要 ＋ 對這個帳本的意義 ＋ 條文原文**，並附來源網址、修正日期、
  抓取時間與原始檔 SHA-256。摘要與原文不符時以原文為準，這句話寫在每一篇裡。
- **App 完全不連網。** 抓取是 `tools/law_sync/` 的外掛工具，用 research runtime 手動執行，
  依賴不進 `environment.yaml`。有一個測試用 AST 掃 `src/`，確認 App 不依賴任何網路函式庫。
- 法規庫以 `mode=ro` **唯讀開啟** —— 它是產生物，任何寫入都是 bug，應該當場失敗。
  測試會實際嘗試 DELETE 並斷言失敗。
- **法規庫不存在是正常狀態**，記帳完全不受影響，法規頁顯示怎麼建立而不是報錯。
- 中文全文搜尋改用**逐字索引**：`unicode61` 會把整串中文當成一個 token，
  導致搜「儲蓄投資」找不到「儲蓄投資特別扣除」。索引與查詢兩邊都逐字加空白，
  任何長度的子字串都找得到。不用 trigram tokenizer 是因為它要求關鍵字至少三個字，
  而「定存」「贈與」只有兩個字。
- `reviewed_at` 超過**六個月**標「需複查」。只是提示，程式不會自動抓取也不會自動改內容。
- 抓取紀律：同網域間隔 4 秒、**一部法規一個請求**（抓全文再自行切條）、429／503 立即全停。
  `--reparse` 可以只重新解析已存的原始檔，一個網路請求都不發。
- 繁中守門移除三個**兩用字**：`准`、`佣`、`划`。`佣` 是掃到所得稅法第 88 條原文才發現的 ——
  官方法律條文用了這個字，沒有比這更硬的證據。抓下來的原文與由它產生的 corpus
  一律不納入繁中掃描：引用的法條必須逐字照抄，不該去「修正」別人的法律。

**硬性非目標**：App 不計算稅額、不做申報、不依法規自動調整任何帳務數字。

## 未發布 - 定存的修改與機動利率（schema v7）

實機試用後的五項修正。

- **修正一鍵啟動器把「喚回既有視窗」誤報成失敗。** `Start-Process -PassThru` 的
  `ExitCode` 有時是 `$null`，而 PowerShell 裡 `$null -ne 0` 為真 —— 畫面上印出的是
  「程式啟動後隨即結束（exit code ）」，括號裡空的就是線索。既有視窗完全沒受影響，
  只有訊息是錯的。
- **修正日曆彈出視窗跑版。** 之前沒有任何 `QCalendarWidget` 樣式，導致全域的
  `QSpinBox` padding 撐爆年份輸入框、`QAbstractItemView` 的 padding 讓日期格容不下
  兩位數而全部顯示成「...」。新增一整節專屬樣式把日曆從全域規則隔開。
- **定存新增「利率類型」（固定／機動）。** 機動利率**不預先填數字** —— 存的當下填的值，
  到期時多半已經不是那個值了，「看起來精確但其實是舊的」比留空更糟。
- **新增從實際利息反推年利率。** 到期照存摺輸入實際利息，程式算出這一期實際等於年利率
  多少並存起來。反推用二分搜尋套用正推函式，所以**反推與正推必定一致**，
  進位規則變了兩邊會一起變。
- **補上定存的修改與刪除。** 合約可改名稱、到期轉存方式、利息轉入帳戶
  （計息方式與期長鎖住 —— 它們決定了已產生事件的形狀）；期可改本金、利率、日期。
  **這是 go-live runbook 裡「查到牌告利率再回來補」的實作路徑** —— 在此之前
  runbook 寫了一個不存在的操作。
- 新增定存合約的對話框可以直接開新帳戶，不必中途跳去「帳戶」分頁。
- schema v7：`deposit_contracts.rate_type`、`deposit_terms.effective_rate_ppm`。
  **必須是新的一版而不是改 v6** —— 使用者的資料庫已經跑過 v6，改 v6 對它毫無效果。

## 0.9.0 - 郵局定存（schema v6）

三種計息方式 × 四種到期轉存方式**全部實作**，共十二種組合各有測試。

- Schema v6：`deposit_contracts`、`deposit_terms`、`deposit_events` 三張表。
  `deposit_events` 的 `UNIQUE (term_id, event_type, due_date)` 讓「產生到期項目」
  可以重複按而不會產生重複列。
- **年利率用 `annual_rate_ppm` 整數存**（1.6% = 16000），延續「禁止 float」的規則。
  **可以留空** —— 還沒查到牌告利率不該擋住把定存記下來，只是算不出建議金額。
- **續約產生新的一期，不改寫舊的那一期**，所以每次續存當時的利率都留得下歷史。
  新一期的利率刻意留空，不沿用上一期 —— 續存是照當時牌告，沿用等於捏造事實。
- **程式不自動入帳。** 到期與每月領息只產生待確認項目，
  `test_generating_events_never_writes_a_posting` 斷言產生事件後 posting 一列都沒增加。
- 到期**提前七天**出現在待確認，讓「不自動轉存」來得及去郵局處理。
- 利息記成**收入**而非轉帳 —— 利息是新產生的錢，記成轉帳會讓總資產憑空不變。
- 試算永遠只是**建議值**，實際金額以存摺為準且可覆寫；覆寫的值才寫進
  `actual_interest_minor`。計息基準（複利／單利、進位規則）已列為 Stage 6 的查證項目。
- 起存日**允許早於帳本第一筆交易** —— 既有定存本來就比開始記帳早。
- UI：操作設定新增「定存」分頁（合約與每一期）；到期處理一律在「待確認」頁，
  不另開第二個入帳入口。
- 錯誤碼新增 13 個定存相關條目。

## 0.8.0 - 例外處理與可觀測性

- **第二次啟動改成把既有視窗叫到最前面**，不再跳「程式已經開著了」警告。使用者按捷徑的
  意思是「我要用這個程式」，正確的回應是把視窗給他。用 `QLocalServer` 具名管道
  （不是網路連線，沒有連接埠），並在 Windows 上先 `AllowSetForegroundWindow` 讓出前景權，
  否則通常只會看到工作列閃爍。等對方回 ack 才算成功 —— 「回報成功卻什麼都沒發生」比
  直接顯示警告更糟。叫不動時仍退回原本的對話框。
- 修正啟動失敗對話框把標題重複顯示兩次。
- 診斷資訊匯出改用 **UTF-8 with BOM**：這是「寫檔一律無 BOM」的例外，因為它是給人雙擊
  打開的 `.txt`，Windows 上沒有 BOM 的中文純文字會被編輯器猜成 cp950 而整份亂碼。

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
