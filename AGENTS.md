# AGENTS — TagCor Ledger

**這份是給所有 agent（Codex、Claude Code 等）的唯一正本。** `CLAUDE.md` 只是指向這裡的一行。

## 專案定位

Windows-first、**純本機、完全不連網**的個人記帳工具。主資料庫是 SQLite，CSV 只作交換格式。介面固定使用繁體中文與 PySide6。

每一筆帳都由使用者手動輸入 —— 這是刻意的設計，不是還沒做的功能。手動輸入才讓使用者感受得到花費的程度。

## 資料位置與讀取邊界

**「運作的地方」與「儲存的地方」是分開的**，這樣專案日後若推上 remote，只會公開程式，不會公開任何個人財務資料。

| | 位置 |
|---|---|
| 程式（可公開） | `D:\Projects\tagcor-ledger\` |
| 資料（絕不公開） | `<資料根目錄>\` |
| 指標檔 | `%LOCALAPPDATA%\TagCor\TagCorLedger\system_paths.json` |

資料根目錄底下固定五個平輩資料夾：`ledger\`、`backups\`、`exports\`、`logs\`、`tmp\`。

### agent 的讀取規則

- **可讀**：本專案全部 ＋ `<資料根目錄>\**` 底下所有檔案。
- **不可讀、不可寫**：`<私人資料樹>\` 底下**其他任何**資料夾。
- 即使在允許範圍內，**不要主動把實際交易金額與備註貼進對話**，除非使用者要求。談論資料時用筆數、日期範圍、schema 這類不外洩內容的描述。

### `.claude\settings.json` 怎麼設、以及它的三個極限

deny 優先於 allow，而且路徑 pattern **沒有否定語法**，所以做不到「deny 整個 `<私人資料樹>\**` 但 allow 其中一個子樹」—— 那樣寫會連允許的資料夾一起擋掉。因此是三層：

| 層 | 規則 | 作用 |
|---|---|---|
| `deny` | `Edit`／`Write` on `<私人資料樹>/**` | **寫入絕對禁止，無例外。** 資料只由 App 自己寫，agent 永遠不需要寫 |
| `ask` | `Read`／`Glob`／`Grep` on `<私人資料樹>/**` | 讀取一律先問過使用者 |
| `allow` | 同三項 on `<資料根目錄>/**` | 指定資料夾免問 |

新增 deny 條目時**一定要用 `/**` 結尾**。單一 `*` 在 glob 裡只 match 一層，`Read(<私人資料樹>/X/*)` 會涵蓋 `X` 這個資料夾本身卻涵蓋不到 `X\secret.txt`。

**三個極限，不要當成滴水不漏：**

1. **攔不住 shell。** `Get-Content`、`cat`、`type`、`Select-String` 都能讀檔，任意 shell 指令無法可靠地用 pattern 比對。用 shell 時靠的是這一節的成文規則。
2. **改了要重啟才生效。** Claude Code 的設定監看只涵蓋 session 啟動時就存在的設定檔。新建或改動 `.claude\settings.json` 之後，要重開 session（或開一次 `/config`）才會載入。
3. **新資料夾不會自動被擋。** `<私人資料樹>\` 底下新增的資料夾不在 deny 清單裡，只會被 `ask` 攔下來問。`Verify.ps1` 的漂移檢查會列出它們並印出該加的規則字串。

### 改資料路徑是三步，不是一步

路徑寫死在兩個地方，改一個而不改另一個會造成漂移（agent 讀不到真資料夾，或舊路徑仍掛在允許清單上而該位置日後被別的東西佔用）：

1. App「系統設定 → 記帳資料路徑」改路徑。
2. `.claude\settings.json` 的 deny／allow 清單同步改。
3. 跑 `.\Verify.ps1` 確認漂移檢查通過。

## 架構邊界

- `domain/`：Money、帳戶、類別、交易、模板、排程、餘額盤點模型；**不得依賴 Qt 或 SQLite**，也不得 import 其他任何一層。
- `application/`：use case、Result、設定、備份/還原/重製協調；**不得直接寫 UI**。
- `infrastructure/`：SQLite migration、store、backup、CSV export。store 依聚合切在 `infrastructure/stores/`，`LedgerStore` 在 `sqlite_store.py` 把它們組起來。
- `ui/`：PySide6 視圖與 controller；**不得直接撰寫 SQL**。一個檔案一個畫面放在 `ui/pages/`，頁面之間不互相 import，跨頁連動一律集中在 `ui/main_window.py`。
- 系統路徑設定不存放在 ledger SQLite，使用外部 JSON 設定檔（資料庫路徑本身不能可靠地存在資料庫裡）。

**這幾條由 `tests/unit/test_architecture.py` 用 AST 守著**，不是只寫在文件上。同一份測試還會擋單一模組超過 700 行。完整的檔案地圖見 `docs/architecture/overview.md`。

## 重要規則

- 金額一律使用 `Money(amount_minor: int, currency: str)`，**禁止 float**。
- 目前固定 TWD 與 Asia/Taipei。
- UI 用詞：`類別` 表示第一層，`項目` 表示第二層；不要再用「分類／細項」。
- Phase 4 已移除「對象／商家」欄位，**不得**新增 payee model、payees table 或 payee UI。
- **不得為一卡通／悠遊卡／iCash 建立帳戶、餘額欄位，或任何「卡內餘額」概念。** 電子票證只記
  儲值當下的支出，見下一節。
- 備份只能由使用者手動建立；啟動流程不得自動備份。
- 還原/重製前的保護備份必須由使用者明確勾選。
- 刪除設定項只允許未被任何歷史資料引用；否則使用封存。
- 盤點不建立交易、不建立 posting、不改變帳戶餘額。
- **`ledger_dir`、`backup_dir` 必須都在 `data_root` 底下**，且彼此不得相同或互相包含。違反時丟 `PATH_OUTSIDE_DATA_ROOT` / `LEDGER_BACKUP_PATH_SAME` / `LEDGER_BACKUP_PATH_NESTED`。
- **搬移資料的順序不可調換**：先複製到新位置 → 確認成功 → 寫指標檔 → 才刪舊檔。反過來會在搬移失敗時留下「指標指向新位置、資料還在舊位置」，下次啟動就在新位置建一個空資料庫，看起來像資料全部消失。
- 「從外部檔案還原」會讀取使用者從對話框挑選的任意路徑。這是**刻意保留**的例外（否則無法從外接硬碟還原），由使用者主動觸發。

## 電子票證慣例（悠遊卡／一卡通／iCash）

**這是記帳慣例，不是功能。** 不需要任何程式支援，用現有的「支出 ＋ 類別／項目」就能表達。

| 發生什麼 | 怎麼記 |
|---|---|
| 儲值 500 元 | **支出** 500，類別「交通」、項目「電子票證儲值」，帳戶選錢實際離開的那個 |
| 用卡片搭車、買東西 | **不記。** 錢在儲值那一刻就已經離開了 |
| 退卡拿回卡內餘額 | **收入**，同一個類別與項目 |

- **複數張卡共用同一個項目**，不依卡片拆項目、不在備註裡分卡。
- **不建卡片帳戶、不追蹤卡內餘額。** 這條由 `tests/integration/test_phase1_core.py`
  的 `test_schema_never_grows_a_stored_value_card_concept` 掃 schema 守著。

那個測試守的是 **schema**，不是使用者怎麼命名 —— 使用者要把帳戶取名叫「悠遊卡」程式攔不住，
也不該攔。會被擋下來的是「資料庫裡長出卡內餘額這個概念」。

代價是**看不出電子票證的消費結構**，這是知情且接受的。要改變這個取捨的話，
正確做法是新增一份 ADR 推翻 [`ADR-0006`](docs/decisions/ADR-0006-manual-entry-only.md)，
不是「順手」加一個欄位。市面產品幾乎都做卡片歸戶，所以這裡的壓力是持續的。

## 不做的事（非目標，不是待辦）

- 不做銀行同步、不串接電子發票載具、不做任何自動匯入。
- 不連網。App 永遠不發出網路請求。
- 不做多幣別與匯率、不做預算、不做雲端同步。
- 不重新加入 PyQt6、TagPath、CSV/JSON runtime store 或 importer。

## UI 樣式規範

**色票的正本是 `ui/colors.py`。** QSS 裡不得出現那份清單以外的色碼，`test_resources.py` 會掃過去比對。要新增顏色就先去那邊宣告，並且**算過對比**再用。

- 固定深色主題（**中性純灰，零色偏**），由 `tagcor_ledger.ui.theme.apply_dark_theme(app)` 套用 `Fusion` style、字體、palette 與 `styles.qss`。palette 與 QSS 都從 `colors.py` 取值。
- **彩色只留給金額與警示。** 主要按鈕是近白底深字（靠明度，不靠色相），選取列是淺一階的灰，焦點框是中性亮灰。畫面上任何一抹紅或綠都應該是資訊。
- 金額：支出紅 `EXPENSE`、收入綠 `INCOME`、轉帳不上色。顏色**不是唯一線索** —— 一律同時有正負號與右對齊。
- 所有「文字／底色」組合的 WCAG 對比 >= 4.5，而且要拿**選取列**（最亮的底）去算。
- 不要用過寬的全域 QSS selector 污染不同用途元件；共用元件若用途不同，需指定 objectName。
- 側邊欄外框用 `sidebarRail`（`QFrame`，右框線畫在這一層）、兩個導覽清單用 `sidebarNavigation`；備份清單用 `backupList`；內容堆疊用 `contentStack`；每一頁的置中容器用 `pageContent`；狀態訊息用 `statusLabel`（帶 `state` 屬性）；流向切換用 `segmentButton`；資產總覽的大數字用 `totalAmount`。
- **側邊欄裡不得有任何點不動的東西。** 分組不放標題，靠位置表達（日常在上、設定沉底，中間留白）。這條路用「程度差異」試過兩次都失敗，第三次是把標籤整個移除；理由見 `ui/navigation.py` 的模組說明與 `docs/lessons.md`。有測試守著。
- **導覽用 `PageId`，不得拿顯示文字當 key。** 頁面身分在 `ui/navigation.py` 的 `PageId`，顯示文字在 `LABELS`；改 `LABELS` 不影響任何查表。側邊欄順序的唯一正本是 `DAILY_PAGES` / `SETTINGS_PAGES`，改了要同步 `docs/architecture/ui-workflows.md`（`tests/unit/test_docs_drift.py` 會逐字比對）。
- **版面走 `widgets/layout.py` 的 `page_layout(self, width=...)`**，不要各頁自己 `QVBoxLayout(self)`。寬度上限：表單 `FORM_WIDTH`、摘要 `SUMMARY_WIDTH`、有資料表的 `TABLE_WIDTH`。
- **欄位少的表格用 `fit_content=True` 收寬**；操作設定裡的表格另外用 `fit_rows=SETTINGS_TABLE_ROWS` 收高度，而且該分頁最後要有 `addStretch()`，否則 layout 會把多餘高度平均塞進元件之間。
- **UI 用詞與資料表名稱可以不同。** 使用者看到「定期收支」，schema 仍是 `recurring_schedules`。已淘汰的 UI 用詞列在 `tests/unit/test_architecture.py` 的 `RETIRED_UI_WORDS`，該測試掃 `ui/` 的字串常數（docstring 與註解不算）。
- 主要操作按鈕用 `primaryButton`；刪除、作廢、重製、還原等高風險操作用 `dangerButton`。
- **表格不得在 QSS 設 `color` 或 `selection-color`。** 那會蓋掉 model 的 `ForegroundRole`，金額的紅綠會被壓成同一個白。顏色由 `widgets/table.py` 的 `amount_color` 決定。
- **對所選項目動作的按鈕一律用 `bind_selection` 綁選取狀態。** 沒選取就停用，不要讓使用者按下去什麼都不發生。
- 分頁必須由 QSS 覆蓋 `QTabWidget/QTabBar` 的 selected、unselected、hover、disabled 狀態。
- **不要覆寫 `QComboBox::drop-down`。** 一碰那個 subcontrol，Fusion 就不再畫箭頭，而本專案不打包圖檔，結果是一塊空白方格。
- **主字體必須是中文字型**（`Microsoft JhengHei UI` 排第一），12pt、Medium 字重。理由是 `Segoe UI Variable` 沒有中文字形，中文全靠 fallback，而**字重套不到 fallback 字型上** —— 對它設 Medium 只有數字變粗，中文一點都沒變。字體不打包，順序是 `Microsoft JhengHei UI`、`Microsoft JhengHei`、`Noto Sans TC`、`Segoe UI Variable`、`Segoe UI`、sans-serif。
- **日期欄位一律用 `date_field()`，不要用 `QDateTimeEdit`。** 介面只問到「哪一天」；時分秒由 `iso_from_date()` 補上（新建補現在、編輯沿用原值），資料庫存的仍然是完整時間戳。顯示一律用 `display_date()`，**不要把補出來的時分印出來** —— 那不是使用者輸入的東西。
- UI 變更至少跑 `tests/ui` smoke；樣式資源變更需同步更新 `tests/unit/test_resources.py`。
- **改配色或改樣式之後要真的看一眼。** `window.grab().save(...)` 可以在不開視窗的情況下把畫面存成 PNG（用 `QT_QPA_PLATFORM=windows` 才有中文字型）。純看 QSS 看不出「顏色被蓋掉」這種問題。**抓最上層視窗**，用 `QTimer.singleShot` 在事件迴圈裡觸發，grab 之前先 `repaint()` —— 單獨 grab 巢狀子 widget 會憑空生出不存在的 bug（`docs/lessons.md` 2026-08-20）。
- **UI 測試量 geometry，不量設定值，也不用 `isVisible()` 過濾。** `QStackedWidget` 底下的頁在 offscreen 平台上永遠回報 `isVisible() == False`，用它當過濾條件會讓整條守門靜默跳過。斷行要比 `label.width() >= fontMetrics().horizontalAdvance(text)`，高度要比 `header + 列數 × 列高`。**每一個帶 `continue` 的檢查迴圈都要有陽性對照**（`assert checked >= N`）。

## 環境與驗證

環境是 **conda**（`environment.yaml` 的 `tagcor-ledger`），專案裡沒有 `.venv`。
PySide6 由 conda dependency 管理，**不能**放回 `pyproject.toml` 讓 pip 安裝 —— Windows 下混用 conda/pip 的 PySide6 會造成 Qt DLL 載入失敗。

**人要開程式：雙擊 `啟動 TagCor Ledger.cmd`。** 它用絕對路徑呼叫環境直譯器，不碰 PATH。

**人在互動式 PowerShell 裡：先啟動環境。**

```powershell
conda activate tagcor-ledger
python -m tagcor_ledger --gui
```

但**終端機裡若已經啟動了別的專案的 venv，這樣會失敗** —— venv 的 `Scripts` 排在 PATH 最前面，`conda activate` 之後仍然是它贏，兩個環境名稱都出現在提示字元上卻跑到錯的直譯器。先 `deactivate`，或直接用一鍵啟動。

**agent 在工具 shell 裡：一律用完整路徑，不要用 `conda activate`。**

```powershell
<conda-root>\envs\tagcor-ledger\python.exe -m tagcor_ledger --json
```

理由是工具 shell 以 `-NonInteractive` 啟動、**不載入 `profile.ps1`**，所以 `conda init powershell` 裝的 hook 沒生效。此時 `conda activate` 會跑在子 process 裡改不到父層環境，**回報成功、退出碼 0、實際上什麼都沒換**（2026-08-18 實測）。接著跑到的會是 PATH 上碰巧排在前面的別的直譯器 —— 那個直譯器多半沒有 PySide6，於是失敗訊息會指向完全無關的方向。

```powershell
.\Verify.ps1                 # 路徑漂移檢查 + ruff + mypy --strict + pytest
.\Verify.ps1 -Ui             # 加跑 tests\ui（offscreen）
.\Verify.ps1 -Performance    # 加跑 20 萬筆效能測試
```

## 語言與編碼

- **中文一律繁體。** 不得混入簡體字。`tests/unit/test_traditional_chinese.py` 是自動守門，`Verify.ps1` 每次都會跑。它只收「簡體專用」字，繁簡同形的字（量、常、伙、台…）不列入，所以零誤報。
- 介面文字、錯誤訊息、註解、文件全部繁體中文；程式識別字用英文。
- `.md` / `.json`：UTF-8 **無 BOM**。
- `.ps1` / `.psm1`：UTF-8 **必須有 BOM**（PowerShell 5.1 沒有 BOM 會退回 Big5 而整份亂碼）。

## 閱讀順序

**要動程式的話照這個順序，不要跳：**

1. 這一份（`AGENTS.md`）—— 硬規則與邊界
2. `docs/architecture/state-machines.md` —— 有哪些狀態、哪些轉移合法、哪裡刻意不推論
3. `docs/architecture/data-model.md` —— 表與欄位
4. `docs/architecture/error-codes.md` —— 每個錯誤的成因與使用者該怎麼做
5. `docs/architecture/glossary.md` —— 什麼該叫什麼，以及**不該叫什麼**
6. `docs/lessons.md` —— 踩過的坑。**動 migration 或路徑之前必讀**
7. 才是相關的 `docs/requirements/REQ-XXXX` 與 `docs/decisions/ADR-XXXX`

`docs/index.md` 有完整索引與每份文件的權威範圍。
`docs/archive/phase-0-2/` 只是歷史紀錄，**不是**現行規格。

## 文件維護

任何功能變更都要同步更新 README、requirements、architecture、roadmap、changelog。踩到坑要在 `docs/lessons.md` 追加一筆 —— 那是 append-only 的失敗紀錄，目的是不要重蹈覆轍。
