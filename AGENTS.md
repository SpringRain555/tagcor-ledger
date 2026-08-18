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
- 備份只能由使用者手動建立；啟動流程不得自動備份。
- 還原/重製前的保護備份必須由使用者明確勾選。
- 刪除設定項只允許未被任何歷史資料引用；否則使用封存。
- 盤點不建立交易、不建立 posting、不改變帳戶餘額。
- **`ledger_dir`、`backup_dir` 必須都在 `data_root` 底下**，且彼此不得相同或互相包含。違反時丟 `PATH_OUTSIDE_DATA_ROOT` / `LEDGER_BACKUP_PATH_SAME` / `LEDGER_BACKUP_PATH_NESTED`。
- **搬移資料的順序不可調換**：先複製到新位置 → 確認成功 → 寫指標檔 → 才刪舊檔。反過來會在搬移失敗時留下「指標指向新位置、資料還在舊位置」，下次啟動就在新位置建一個空資料庫，看起來像資料全部消失。
- 「從外部檔案還原」會讀取使用者從對話框挑選的任意路徑。這是**刻意保留**的例外（否則無法從外接硬碟還原），由使用者主動觸發。

## 不做的事（非目標，不是待辦）

- 不做銀行同步、不串接電子發票載具、不做任何自動匯入。
- 不連網。App 永遠不發出網路請求。
- 不做多幣別與匯率、不做預算、不做雲端同步。
- 不重新加入 PyQt6、TagPath、CSV/JSON runtime store 或 importer。

## UI 樣式規範

- 固定深色主題，由 `tagcor_ledger.ui.theme.apply_dark_theme(app)` 套用 `Fusion` style、字體、palette 與 `styles.qss`。
- 不要用過寬的全域 QSS selector 污染不同用途元件；共用元件若用途不同，需指定 objectName。
- 側邊欄 `QListWidget` 用 `sidebarNavigation`；備份清單用 `backupList`；內容堆疊用 `contentStack`。
- 主要操作按鈕用 `primaryButton`；刪除、作廢、重製、還原等高風險操作用 `dangerButton`。
- 分頁必須由 QSS 覆蓋 `QTabWidget/QTabBar` 的 selected、unselected、hover、disabled 狀態。
- 字體不打包，使用本機 fallback：`Segoe UI Variable`、`Segoe UI`、`Microsoft JhengHei UI`、`Microsoft JhengHei`、`Noto Sans TC`、sans-serif。
- UI 變更至少跑 `tests/ui` smoke；樣式資源變更需同步更新 `tests/unit/test_resources.py`。

## 環境與驗證

**用專案自己的 conda 環境，不要用 PATH 上的 python。**

```powershell
<conda-root>\envs\tagcor-ledger\python.exe
```

PySide6 由 `environment.yaml` 的 conda dependency 管理，**不能**放回 `pyproject.toml` 讓 pip 安裝 —— Windows 下混用 conda/pip 的 PySide6 會造成 Qt DLL 載入失敗。

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
