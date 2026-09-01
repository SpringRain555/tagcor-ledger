# AGENTS — TagCor Ledger

> **這份與 `CLAUDE.md` 是平級的兩份完整規則**（Codex 只自動載入 `AGENTS.md`，
> Claude Code 只自動載入 `CLAUDE.md`）。**改任何一份就要同步改另一份。**
> 唯一該有的差異是「工具專屬」那一節。
>
> 產生器會比對兩份最後被改的 commit，不一致就報 `agent-doc-drift`。
>
> 2026-08-30 之前 `CLAUDE.md` 只是一份指向這裡的指路檔 —— 也就是說 Claude Code
> 自動載入到的只有那幾行，底下這一整份規則要靠它自己去跟。

## 工具專屬

**Codex**（讀這一份）：沒有額外規則，往下讀就好。

**Claude Code**（讀 `CLAUDE.md`）：

- **用專案的 conda 直譯器**，不要用 PATH 上的 python：
  `<conda-root>\envs\tagcor-ledger\python.exe`。
  工具 shell 不載入 profile，`conda activate` 會回報成功卻什麼都沒換。
- `.claude\settings.json` 的 deny **攔不住 Bash 與 PowerShell**（`Get-Content`、
  `cat`、`Select-String` 都能讀檔）。用 shell 時靠的是下面「資料位置與讀取邊界」
  的成文規則，不是設定檔。
- 主要 shell 是 PowerShell 5.1，沒有 `&&`／`||`／三元運算子。

## 專案定位

Windows-first、**純本機、完全不連網**的個人記帳工具。主資料庫是 SQLite，CSV 只作交換格式。介面固定使用繁體中文與 PySide6。

每一筆帳都由使用者手動輸入 —— 這是刻意的設計，不是還沒做的功能。手動輸入才讓使用者感受得到花費的程度。

## 資料位置與讀取邊界

**「運作的地方」與「儲存的地方」是分開的**，這樣專案日後若推上 remote，只會公開程式，不會公開任何個人財務資料。

| | 位置 |
|---|---|
| 程式（可公開） | 這個 repo 的資料夾 |
| 資料（絕不公開） | `<資料根目錄>` |
| 指標檔 | `%LOCALAPPDATA%\TagCor\TagCorLedger\system_paths.json` |

資料根目錄底下固定五個平輩資料夾：`ledger\`、`backups\`、`exports\`、`logs\`、`tmp\`。

> **`<資料根目錄>` 與 `<私人資料樹>` 是佔位符**，因為這個 repo 是公開的 ——
> 把私人資料夾的實際名稱寫進版控，等於把那份清單一起發佈出去。
> 實際路徑有兩個權威來源：指標檔 `system_paths.json` 的 `data_root`，
> 以及本機那份 `.claude/settings.json`（**不進版控**，範本是
> `.claude/settings.example.json`）。要知道現在指到哪，跑
> `& $env:TAGCOR_PYTHON -m tagcor_ledger --json`。

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

- `domain/`：Money、帳戶、類別、交易、模板、餘額盤點、定存模型；**不得依賴 Qt 或 SQLite**，也不得 import 其他任何一層。
- `application/`：use case、Result、設定、備份/還原/重製協調；**不得直接寫 UI**。
- `infrastructure/`：SQLite migration、store、backup、CSV export。**store 一律放在 `infrastructure/stores/`，一個聚合一個檔**，`LedgerStore` 在 `sqlite_store.py` 用繼承把它們組起來（唯一的例外是 `LedgerStore` 自己，它只負責組裝）。`stores/__init__.py` 的 `__all__` 必須與 `LedgerStore` 的基底一致。兩條都有測試守著。
- **「一筆交易長什麼樣」只有一個地方說了算**：`StoreBase._write_transaction()` / `_write_transfer()`。它們收 `connection` 而不是自己開，所以「就寫這一筆」與「建交易＋改別的表的狀態」兩種情境都能用同一份實作。`transactions`、`transaction_fts`、`audit_events` 三張表**只能有一個寫入點**（`stores/base.py`），`tests/unit/test_architecture.py` 會擋。要寫交易就呼叫那兩個，不要再開一條路 —— 分岔過一次，代價寫在 `docs/lessons.md`。
- `ui/`：PySide6 視圖與 controller；**不得直接撰寫 SQL**。一個檔案一個畫面放在 `ui/pages/`，頁面之間不互相 import，跨頁連動一律集中在 `ui/main_window.py`。
- **`LedgerController` 由 `ui/controller/` 底下的 section 用繼承組起來**，比照 `LedgerStore`。`__init__.py` 只放組裝、不得定義任何方法；section 之間**彼此不呼叫對方**（唯一的例外是 `OverviewSection`，它明說自己是聚合層）。有測試守著。
- **`DepositService` 由 `application/deposits/` 底下的 section 用繼承組起來**，同一套做法。它**沒有**聚合層例外 —— section 之間完全不互相呼叫，`test_no_deposit_section_calls_another_section` 守著。
- **「一列長什麼樣」只由 `ui/formatting/` 決定**，`ui/pages/` 不得自己定義會 `return [...]` 的 `*_values`。同一個狀態有兩個拼法，兩張表就會對同一筆資料講不同的話。
- 系統路徑設定不存放在 ledger SQLite，使用外部 JSON 設定檔（資料庫路徑本身不能可靠地存在資料庫裡）。
- **`application/` 的 `except` 只能用 `failures.py` 的兩個具名常數**，見下一節。

**這幾條由 `tests/unit/test_architecture.py` 用 AST 守著**，不是只寫在文件上。同一份測試還會擋檔案過大：`src/` **700 行**、`tests/` **1200 行**（測試本來就比實作長，但 2026-08-22 拆掉的那個 UI 測試檔已經 2,153 行 66 條、橫跨八個頁面，因為當時只掃 `src/`）。完整的檔案地圖見 `docs/architecture/overview.md`。

### `application/` 怎麼接例外

**只用 `application/failures.py` 的兩個常數**，不要自己拼 tuple：

| 常數 | 內容 | 用在哪 |
|---|---|---|
| `STORE_FAILURES` | `(ValueError, NotFoundError, sqlite3.Error)` | **單層** handler —— 包一個 store 呼叫，整包交給 `failure()` |
| `DOMAIN_FAILURES` | `(ValueError, NotFoundError)` | **兩層寫入路徑**的第一層 |

**`NotFoundError` 繼承 `RuntimeError` 不是 `ValueError`**，所以 `except (ValueError, sqlite3.Error)` 接不到它。2026-08-22 盤點時，這一層有 70 個 handler、17 種形狀，其中 **15 個包著會丟 `NotFoundError` 的 store 方法卻沒有列它** —— 真的觸發時使用者看到的是全域錯誤對話框，不是中文。`MoneyError`（繼承 `ValueError`）與 `sqlite3.IntegrityError`（繼承 `sqlite3.Error`）**不要另外列**，那只是雜訊。

**兩層寫入路徑**是刻意的，不要為了整齊把它壓成一層：交易與餘額盤點的寫入要分開講「內容有問題」（第一層，`failure()` 保留原碼）與「內容沒問題但寫不進去」（第二層，`except sqlite3.Error` ＋ 一句「什麼都沒變」）。守門用**結構**認第二層（同一個 `try` 裡第一個 handler 是 `DOMAIN_FAILURES`），不靠名單。

三種**允許不一樣**的情形，都要在 `test_architecture.py` 的名單裡帶一句理由：

1. **還沒碰到 store** —— 解析金額、建列舉。那是輸入驗證，不是寫入層失敗。
2. **刻意收窄** —— `catalogs.create` 的 `(ValueError, sqlite3.IntegrityError)`：走到那裡表示上面三道重名檢查都沒攔到，放寬會把真正的 bug 藏成一句客氣的中文。
3. **整個模組不經過 store** —— `diagnostics.py`（自己開連線跑 PRAGMA）、`reference.py`（另一個唯讀資料庫）。

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
- **禁止把資料撈進 Python 再排序或搜尋。** 篩選、排序、分頁、加總一律在 SQL 裡做 —— 帳本會長大，而「先全部載入」的寫法在資料少的時候完全看不出問題。新增常用查詢時先看 `EXPLAIN QUERY PLAN`，並在 `tests/integration/test_query_plans.py` 加一條。
- **`ORDER BY` 只能由 `stores/base.py` 的 `order_by()` 組，欄位只能來自各 store 的白名單**（`CATEGORY_SORT_FIELDS`／`ACCOUNT_SORT_FIELDS`／`TEMPLATE_SORT_FIELDS`）。那是整個專案唯一把字串拼進 SQL 的地方：畫面永遠只送 key，認不出來的那一層直接跳過，整份都認不出來就退回該清單的預設。白名單的值裡**不得出現引號、分號、`%`、`{`** —— `tests/unit/test_order_by.py` 會掃。合法的字面值（`COALESCE(x, '')`）本來就可以改寫成不需要引號的形式，放行引號等於讓「哪一個引號是安全的」變成要逐一判斷。
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

## 對外轉帳慣例

**這是記帳慣例，不是功能。** 記帳頁的「轉帳」底下有三種對象，但**資料庫只有一種轉帳**：

| 轉帳對象 | 存成 | 為什麼 |
|---|---|---|
| 我的帳戶之間 | `transfer`，兩筆 posting | 錢沒有離開你，只是換了地方 |
| 別人轉入 | **收入** ＋ 類別／項目 | 錢進入你的總資產 |
| 轉出給別人 | **支出** ＋ 類別／項目 | 錢離開你的總資產 |

判準是**總資產有沒有變**。這與「利息記成收入，不是轉帳」是同一條原則。

- 建議自己建一個類別「轉帳」，底下放「他人轉入」「轉出給他人」這類項目。
  **程式不自動建立任何類別** —— 名字該叫什麼是使用者的事。
- 「轉給誰」寫在備註。**不得**因此重新引入 payee model。
- **不得新增 `transfer_in` / `transfer_out` 這類 `entry_type`。** 理由與被否決的
  兩個替代方案寫在 [`ADR-0010`](docs/decisions/ADR-0010-external-transfers.md)；
  要改變這個取捨就新增一份 ADR 推翻它，不要順手加一個列舉值。

### 提款也是轉帳

從郵局領現金＝錢在自己的兩個帳戶之間移動，**總資產不變** —— 同一條判準，所以它就是
**轉帳・我的帳戶之間**（轉出帳戶＝郵局、轉入帳戶＝現金），一筆交易兩筆 posting。

- **不要記成「郵局一筆支出 ＋ 現金一筆收入」。** 總資產碰巧會對，但支出總額與收入
  總額各被灌水一次，類別統計也跟著髒掉 —— 而那兩個數字才是記帳想看的東西。
- **不新增「提款」流向。** 按下「轉帳」之後「轉帳對象」預設就停在「我的帳戶之間」
  （`ui/pages/entry.py` 的 `scope_buttons`），第四顆按鈕**省不到任何一次點擊**，
  代價卻與 ADR-0010 否決的「方案甲」一模一樣。
- 嫌每次選兩個帳戶麻煩的話，去「操作設定 → 模板」建一個「郵局提款」模板
  （轉帳型、金額留空），之後按「填入記帳頁」只要打金額。**這是使用者自己建的資料，
  程式不預先建立任何模板。**

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
- **圖表也是灰階，沒有例外。** 資產占比圓環的色階是 `colors.CHART_SLICES`（六階，由淺到深），
  占比由圖例上的數字講，色階只負責讓人看出哪一片比較大。三條硬規則：
  1. **它刻意不在 `ALL_TOKENS` 裡。** 那個集合是 **QSS 的允許清單**，而圓環與圖例色塊
     是 `QPainter` 畫的、一個字都不經過樣式表。加進去等於在 QSS 那一側開六個沒人用的洞。
  2. **每一階對底色的對比 >= 3.0**（WCAG 1.4.11 圖形物件）。實算過 `#5C5C66` 只有 2.73、
     `#45454E` 只有 1.90 —— **梯度不能再往深處延伸**，而「再加一階就好」是最容易順手做的事。
  3. **片數少的時候要在整條梯度上平均取樣**（`slice_colors()`），不是拿前 N 個 ——
     拿前三階的話最大與第二大只差一個色階，實機上看起來就是兩片一樣的淺灰。
  `tests/unit/test_resources.py` 三條都守著。
- 所有「文字／底色」組合的 WCAG 對比 >= 4.5，而且要拿**選取列**（最亮的底）去算。
- 不要用過寬的全域 QSS selector 污染不同用途元件；共用元件若用途不同，需指定 objectName。
- 側邊欄外框用 `sidebarRail`（`QFrame`，右框線畫在這一層）、兩個導覽清單用 `sidebarNavigation`；備份清單用 `backupList`；內容堆疊用 `contentStack`；每一頁的置中容器用 `pageContent`；狀態訊息用 `statusLabel`（帶 `state` 屬性）；流向切換用 `segmentButton`；資產總覽的大數字用 `totalAmount`。
- **側邊欄裡不得有任何點不動的東西。** 分組不放標題，靠位置表達（日常在上、設定沉底，中間留白）。這條路用「程度差異」試過兩次都失敗，第三次是把標籤整個移除；理由見 `ui/navigation.py` 的模組說明與 `docs/lessons.md`。有測試守著。
- **側邊欄兩組清單的 current row 必須一直是有效的**，而且「現在是哪一頁」由 `Sidebar._current` 記，不從 widget 狀態反推。把 current row 設成 `-1`，`QAbstractItemView::focusInEvent` 就會自己把它設成第 0 列並發出 `currentRowChanged` —— 焦點一碰到側邊欄，畫面就換頁。**不要把 `currentRowChanged` 當成「使用者選了什麼」。**
- **導覽用 `PageId`，不得拿顯示文字當 key。** 頁面身分在 `ui/navigation.py` 的 `PageId`，顯示文字在 `LABELS`；改 `LABELS` 不影響任何查表。側邊欄順序的唯一正本是 `DAILY_PAGES` / `SETTINGS_PAGES`，改了要同步 `docs/architecture/ui-workflows.md`（`tests/unit/test_docs_drift.py` 會逐字比對）。
- **版面走 `widgets/layout.py` 的 `page_layout(self, width=...)`**，不要各頁自己 `QVBoxLayout(self)`。寬度上限：表單 `FORM_WIDTH`、摘要 `SUMMARY_WIDTH`、有資料表的 `TABLE_WIDTH`。
- **欄位少的表格用 `fit_content=True` 收寬**；操作設定裡的表格另外用 `fit_rows=SETTINGS_TABLE_ROWS` 收高度，而且該分頁最後要有 `addStretch()`，否則 layout 會把多餘高度平均塞進元件之間。
- **有自由文字欄（名稱、備註）的表要同時指定 `stretch_column`，讓那一欄讓路。** 收寬設的是 `setMaximumWidth`，那是**上限不是保證** —— 名稱一長，`ResizeToContents` 的欄寬總和就超過分頁能給的寬度，欄位照樣溢出、底下冒出橫向捲軸；而這些表是固定高度，捲軸會從那個高度裡扣掉自己的厚度，**最後一列被切掉**，看起來像資料沒載完。指定之後空間夠時 stretch 欄分到的剛好是自己的內容寬度（畫面不變），不夠時只有它被壓縮成 `…`。`setup_table` 另外關掉 `wordWrap` —— 列高釘死成單行，折行只會讓省略看起來像壞掉。
- **UI 用詞與資料表名稱可以不同**（例如使用者看到「項目」，schema 是 `categories` 的第二層）。已淘汰的 UI 用詞列在 `tests/unit/test_architecture.py` 的 `RETIRED_UI_WORDS`，該測試掃 `ui/` 與 `application/` 的字串常數（docstring 與註解不算）。**已移除的功能名稱也在那份名單上** —— 一顆通往不存在功能的按鈕比錯的用詞更糟。
- 主要操作按鈕用 `primaryButton`；刪除、作廢、重製、還原等高風險操作用 `dangerButton`。
- **有些字串照抄程式外面的正本，不得縮短。** `domain/deposits.py` 的
  `MATURITY_ACTION_NAMES` 四個名字逐字照郵局定期儲金存單（`REQ-0007` §列舉 是文件側的
  正本）—— 使用者在那個下拉選單前面做的事就是把實體單據上的打勾抄過來，
  文字不逐字相同他每次都要自己重新推導對應關係。縮短一個 UI 字串之前先問：
  **它在程式外面有沒有一個正本？**
- **表格不得在 QSS 設 `color` 或 `selection-color`。** 那會蓋掉 model 的 `ForegroundRole`，金額的紅綠會被壓成同一個白。顏色由 `widgets/table.py` 的 `amount_color` 決定。
- **勾選框的已勾選狀態要有勾號，不能只靠填色。** 實心白對空心黑的對比有 14:1，兩個狀態絕不會看成一樣 —— 但「**哪一個代表開**」仍然要靠慣例。五個勾選框裡有兩個守著不可逆的操作（`還原前先建立備份`、`重製前先建立備份`），那兩個不該要求使用者知道慣例。與下面兩條是同一個原則的三次套用：第二個線索要用**形狀**。
- **選取列靠底色 ＋ 上下橫線，不是只靠底色。** `SELECTED` 對一般列底 `SURFACE` 的對比只有 1.34，
  而那是上限 —— 再亮一階，支出紅對選取列的對比就掉到 4.5 以下（`test_resources.py` 會紅）。
  深色主題的明度空間本來就窄，第二個線索要用**形狀**。
  **加框線就一定要同步收 `padding`**：Qt 的 `::item` 是 content-box，而列高被
  `defaultSectionSize(34)` 釘死，直接加 2px 框線等於從文字的可用高度裡扣，中文會被切到。
  7px 配 0 框線 ＝ 6px 配 1px 框線，`test_selecting_a_row_does_not_squeeze_the_text` 逐項對算。
- **對所選項目動作的按鈕一律用 `bind_selection` 綁選取狀態。** 沒選取就停用，不要讓使用者按下去什麼都不發生。（注意停用會讓焦點跑掉 —— 焦點跑到哪裡都不該有副作用。）
- **一個錯誤碼只能代表一件事。** 寫入層丟的是 `raise ValueError("SOME_CODE")`（訊息就是碼），應用層用 `application/failures.py` 的 `failure()` 把它翻成中文：**認得出來的碼就用那個碼**，認不出來才退回呼叫端給的 `fallback_code`。碼的中文說法只寫在 `ERROR_MESSAGES` 一個地方，情境需要不同說法時用 `overrides=`。
- **`details["reason"]` 是廢除的 key，加回來 `tests/unit/test_failure_messages.py` 會紅。** 它曾經有 51 個出處，而 `result_message()` 會把它用括號接在畫面訊息後面 —— 於是英文碼與 SQLite 原文都被印給使用者看。預期外的原文放 `details["detail"]`，**那個 key 永遠不顯示**。
- **例外的訊息就是錯誤碼，不要寫英文散文。** `domain/money.py` 以前丟 `MoneyError("Amount must be greater than zero.")`，那句英文因此出現在全中文的畫面上 —— 而且金額打錯是最常見的操作失誤。UI 自己 `except` 的地方用 `ui/formatting.error_text()`，不要直接印 `str(exc)`。
- 分頁必須由 QSS 覆蓋 `QTabWidget/QTabBar` 的 selected、unselected、hover、disabled 狀態。
- **QSS 一碰 subcontrol，Fusion 就不再畫它自己的圖形。** 這條踩到兩次：
  - **不要覆寫 `QComboBox::drop-down`** —— 箭頭會消失，剩下一塊空白方格。那個很明顯是壞了，所以當場就發現。
  - **`QCheckBox::indicator` 已經覆寫了**（為了方框：Fusion 的外框色是 `palette.window().darker(140)` 推導的，在 `#0D0D0F` 上完全看不見），所以勾號要**自己給圖**，`styles.qss` 的 `:checked` 有一行 `image: url(...)`，路徑由 `theme.py` 的 `resolve_stylesheet()` 在載入時代換。這一次的症狀是一塊**看起來很像設計**的實心白方塊 —— 沒有人發現它壞了。
  - 要給圖只能給 **PNG，而且標準與 `@2x` 兩個尺寸都要**。SVG 需要 Qt SVG image plugin（PySide6 的選配元件，本機的 conda env 就沒有），QSS 的 `url()` 也不吃 `data:` URI —— 兩條都實測過，失敗的樣子都是「那一格靜靜地不畫圖」。圖檔由 `tools/icons/make_check_icon.py` 產生，不要用繪圖軟體改。
- **主字體必須是中文字型**（`Microsoft JhengHei UI` 排第一），12pt、Medium 字重。理由是 `Segoe UI Variable` 沒有中文字形，中文全靠 fallback，而**字重套不到 fallback 字型上** —— 對它設 Medium 只有數字變粗，中文一點都沒變。字體不打包，順序是 `Microsoft JhengHei UI`、`Microsoft JhengHei`、`Noto Sans TC`、`Segoe UI Variable`、`Segoe UI`、sans-serif。
- **日期欄位一律用 `date_field()`，不要用 `QDateTimeEdit`。** 介面只問到「哪一天」；時分秒由 `iso_from_date()` 補上（新建補現在、編輯沿用原值），資料庫存的仍然是完整時間戳。顯示一律用 `display_date()`，**不要把補出來的時分印出來** —— 那不是使用者輸入的東西。
- UI 變更至少跑 `tests/ui` smoke；樣式資源變更需同步更新 `tests/unit/test_resources.py`。
- **`apply_dark_theme()` 要在任何 widget 建出來之前套用**（`MainWindow.__init__` 的第一件事），而且**一個 process 只套一次**（有標記擋著）。`setFont`／`setPalette`／`setStyleSheet` 是 application 層級的操作，Qt 要傳播給當下活著的每一個 widget —— 重複套用的成本隨 widget 數量成長，而且比線性還快。正式執行只開一個視窗所以看不出來；**測試裡會讓整包從幾分鐘變成 32 分鐘**。它換掉整個 application 的字體，而表格在建構當下就會量自己該多寬 —— 順序反了，量到的是預設字體下的寬度，之後就再也不會重算。**UI 測試的 fixture 不要順手多做一次 `refresh()`**：那會把「第一次就要對」這個條件洗掉，而使用者看到的永遠是第一次。
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
& $env:TAGCOR_PYTHON -m tagcor_ledger --json
```

理由是工具 shell 以 `-NonInteractive` 啟動、**不載入 `profile.ps1`**，所以 `conda init powershell` 裝的 hook 沒生效。此時 `conda activate` 會跑在子 process 裡改不到父層環境，**回報成功、退出碼 0、實際上什麼都沒換**（2026-08-18 實測）。接著跑到的會是 PATH 上碰巧排在前面的別的直譯器 —— 那個直譯器多半沒有 PySide6，於是失敗訊息會指向完全無關的方向。

```powershell
.\Verify.ps1                 # 路徑漂移檢查 + ruff + mypy --strict + pytest
.\Verify.ps1 -Ui             # 加跑 tests\ui（offscreen）
.\Verify.ps1 -Performance    # 加跑 20 萬筆效能測試
```

**`git commit` 會自動跑 ruff ＋ mypy**（`.githooks/pre-commit`，約 2 秒）。這個 repo 沒有 remote，所以本機 hook 是唯一能自動化的閘門。**pytest 刻意不在 hook 裡** —— 整包 52 秒會讓人習慣性打 `--no-verify`，而一個被習慣性繞過的閘門比沒有閘門更糟。完整驗證仍然是 `.\Verify.ps1 -Ui`。

hook 沒生效的話跑一次 `git config core.hooksPath .githooks`。

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

任何功能變更都要同步更新 README、requirements、architecture、roadmap、changelog ——
但**每一份只寫屬於它的那一段**，不要同一件事寫三遍：

| 文件 | 寫什麼 | **不要**寫什麼 |
|---|---|---|
| `docs/roadmap.md` | 做過什麼、接下來做什麼。已完成的版本一版**一列** | 那一版怎麼做的、踩到什麼坑 |
| `docs/changelog.md` | 那一版改了什麼、為什麼這樣改 | 未來的計畫 |
| `docs/lessons.md` | 踩到的坑與根因。append-only | 功能說明 |

同一個結論寫在三個地方，改的時候就要記得改三個地方 —— 而漏掉的那一份會繼續
用權威的語氣講一件已經不成立的事。2026-08-22 清掉的就是這種重複：roadmap 每發一版
長出一節「這一版最值得記住的一件事」，內容與 `lessons.md` 重疊，而且長在
「後續候選 Phase」底下。


**改了 `docs/architecture/*.md` 裡的 ` ```mermaid ` 區塊，要跑 `.\tools\diagrams\Render-Diagrams.ps1` 重新產生 SVG**（`tests/unit/test_diagrams_drift.py` 會擋；那條測試不需要 node）。踩到坑要在 `docs/lessons.md` 追加一筆 —— 那是 append-only 的失敗紀錄，目的是不要重蹈覆轍。

**新增或改名一頁時，`docs/architecture/ui-workflows.md` 的頁面地圖要跟著改**，
而且那一列的**「不在這裡做的事」不可以留空** —— 那一欄才是整張表存在的理由。
v0.14.0 之前沒有這張表，症狀是連作者自己都會忘記「待確認」是做什麼的；
一頁說不出自己不做什麼，下一個功能就會被塞進去。名稱由
`tests/unit/test_docs_drift.py` 逐字守著，那一欄的內容只有人看得出來。
