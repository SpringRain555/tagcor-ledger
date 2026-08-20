# 失敗紀錄

**這是 append-only 的檔案。** 目的是不要重蹈覆轍 —— 新的一筆加在最上面，舊的不刪不改。

每筆的格式：

```
## YYYY-MM-DD 一句話標題

**情境**：當時在做什麼。
**做了什麼**：實際採取的做法。
**為什麼失敗**：根因，不是症狀。
**結論**：現在的做法。
**不要再做**：具體的禁止事項。
```

---

## 2026-08-20 UI 測試量的是「有沒有設定」，畫面上的兩個毛病照樣過關

**情境**：Stage 3 做完資產總覽，11 條版面測試與 6 條頁面測試全綠，才去截實機的圖。

**做了什麼**：截圖上兩個問題一眼就看到 ——

1. 帳戶表只有三列，底下卻留著約 200 px **有框線但沒有內容**的空白。
   `fit_content` 只收寬度，高度仍然是預設的 expanding。
2. 「今天還沒記錄「現金」的目前金額。」在右邊**還有 700 px 空白**的情況下斷成兩行。

**為什麼失敗**：兩個都是「設定值對、算出來的幾何不對」。

第 2 點的根因值得記下來：`QHBoxLayout` 裡 `label + addStretch() + button` 這種排法，
標籤拿到的是它的 `sizeHint` 寬度；而**開了 `setWordWrap(True)` 的 QLabel**，
sizeHint 是一個「排成大致方形」的啟發值，跟旁邊還剩多少空間無關。所以空間再多也會斷行。

第一版的守門測試也踩了同一類錯：想用 `label.height() < 兩行高` 判斷有沒有斷行，
但那一列的高度是**旁邊那顆按鈕**決定的，標籤在垂直方向被拉滿，量到 48 px 卻與斷行無關。

**結論**：這一類 UI 缺陷只有**算出來的幾何**看得見。斷行要比
`label.width() >= fontMetrics().horizontalAdvance(text)`；高度要比
`header + 列數 × 列高`。短的單行說明放在有 stretch 的列裡時，`setWordWrap(False)`。

**不要再做**：不要用 `assert widget.wordWrap() is False` 這種「檢查設定值」的測試 ——
它證明的是程式碼寫了什麼，不是使用者看到什麼。**每加一頁就截一次實機圖**，
測試全綠不等於畫面對。

---

## 2026-08-20 用截圖驗收 UI 時，抓錯東西會憑空生出兩個不存在的 bug

**情境**：Stage 1 換掉側邊欄之後，要確認選取狀態與徽章真的畫出來了。

**做了什麼**：兩次都用不可靠的取樣方式，兩次都得到「選取沒有被畫出來」的結論，開始往
程式裡找根因 —— 分別懷疑過 size policy、item delegate、`clearSelection()` 的順序。

**為什麼失敗**：

1. **對子 widget 呼叫 `grab()`**。`QListWidget` 是 `QAbstractScrollArea`，巢狀在還沒
   完成佈局的視窗裡時，單獨 grab 出來的內容不等於它在視窗裡的樣子。
2. **用 `viewport().mapTo(window, rect)` 換算座標**去取像素。換算結果偏掉，取樣點落在
   項目外面，於是每一格都讀到底色。
3. `w.show()` 之後只 `processEvents()` 一次就 `grab()`，畫面還沒重繪 ——
   截到的是切頁**之前**的內容，看起來像「按了沒反應」。

**結論**：截圖驗收一律**抓最上層視窗**、用 `QTimer.singleShot` 在事件迴圈裡觸發、
grab 之前先 `repaint()`。要判斷「某個顏色有沒有出現」就對整張圖做色彩直方圖，
不要挑單一像素。真正的狀態一律另外用 `currentRow()` / `selectedItems()` /
`currentWidget()` 印出來對照。

**不要再做**：不要單獨 grab 巢狀的子 widget，不要用 `mapTo` 算出來的座標取單點像素當
證據。**發現「畫面不對」時，先確認量測方式是對的，再去懷疑程式。**

---

## 2026-08-19 QSS 的 `color` 會蓋掉 model 的顏色，而 model 層的測試看不出來

**情境**：交易列表要把支出標紅、收入標綠，顏色由 `RowsModel` 的 `ForegroundRole` 提供。

**做了什麼**：實作完，測試（讀 `index.data(ForegroundRole)`）全綠，就當作做好了。實際畫面上**每個金額都是白的**。

**為什麼失敗**：`styles.qss` 裡有 `QTableView::item { color: #E8E8EA; }`。Qt 的樣式表優先於 model 的 `ForegroundRole`，所以 model 照樣回報紅色、畫面照樣畫白色。**測試讀的是 model，不是畫面**，於是那個 bug 在測試裡完全隱形 —— 後來實際注入驗證過：把 `color` 加回去，model 層的測試仍然通過。

**結論**：表格的 QSS 不設 `color` 也不設 `selection-color`，顏色交給 model。新增一條**看像素**的測試：把儲存格 `grab()` 成 QImage，取「離背景最遠」的那顆像素當文字色（反鋸齒讓邊緣是混色，不能直接比對色碼）。那條測試在注入後會紅。

**不要再做**：不要用「model 回傳什麼」證明「畫面長什麼樣」。凡是**畫出來才成立**的性質（顏色、對齊、有沒有被蓋掉），就要看畫出來的東西 —— `window.grab().save(...)` 存成 PNG 直接看是最快的方法。

---

## 2026-08-19 `python - <<EOF` 跑到別的專案的 venv，把失敗誤讀成「守門有效」

**情境**：想證明新加的守門測試在注入 bug 之後真的會失敗。

**做了什麼**：用 `python - <<'PY'` 寫一段腳本，裡面用 `sys.executable` 去跑 pytest。看到 exit code 1 就當成「守門有效」。

**為什麼失敗**：heredoc 開頭那個 `python` 是 **PATH 上的**，解析到 `D:\Projects\caption-lingo\.venv`。`sys.executable` 因此是別的專案的直譯器，錯誤其實是 `No module named pytest`。**退出碼 1 是真的，理由是假的。**

**結論**：注入驗證的腳本一律用完整路徑 `<conda-root>\envs\tagcor-ledger\python.exe` 起頭，並在輸出裡印出 `sys.executable` 確認。

**不要再做**：不要只看退出碼就宣告守門有效。**要看到那條斷言的失敗訊息**，確認它失敗的理由正是你注入的那個 bug。

---

## 2026-08-18 注入違規驗證守門，結果被自己的 `.pyc` 騙了

**情境**：Stage 7 新增版本一致性守門，照慣例把 `__version__` 改回舊值、確認測試會紅、再改回來。

**做了什麼**：改回來之後測試**繼續紅**，`--json` 也還印舊版號，而 `__init__.py` 檔案裡明明是新版號。一度以為是 editable 安裝的 metadata 蓋過原始碼。

**為什麼失敗**：CPython 判斷 `.pyc` 是否過期看的是來源檔的 **mtime（秒）＋ 檔案大小**。`"0.10.0"` 與 `"0.11.0"` 長度一模一樣，而注入與還原相差 0.2 秒 —— **同一秒、同一大小**，於是那份用舊值編出來的 `.pyc` 被視為仍然有效。真正在跑的是快取，不是磁碟上的檔案。

**結論**：刪掉 `src/tagcor_ledger/__pycache__/` 底下對應的 `.pyc` 就恢復正常。注入驗證只要改到會被 import 的模組，還原後就順手清一次 `__pycache__`。

**不要再做**：不要在「檔案內容明明是對的，行為卻是舊的」時先去懷疑安裝方式。先確認跑的是不是快取 —— `python -c "import m; print(m.__file__)"` 只會告訴你來源檔在哪，**不會**告訴你它是不是重新編譯過的。

---

## 2026-08-18 schema 加了兩個欄位，只有一半的文件跟上

**情境**：v0.9.1 加 schema v7（`deposit_contracts.rate_type` 與 `deposit_terms.effective_rate_ppm`）。

**做了什麼**：程式、測試與 `glossary.md` 都同步了，`data-model.md` 沒有 —— 它的 migration registry 停在 v5，連 v6 的三張定存表都沒有。三個 Stage 之後的收尾才發現。

**為什麼失敗**：`release_checklist.md` 有「有新用詞的話 glossary 已同步」這一條，卻沒有對應的 data-model 條目。於是「加了新表要更新哪裡」靠的是記得，而不是清單。**沒有進清單的步驟遲早會漏。**

**結論**：`release_checklist.md` 的 Schema 一節加上「加了新表或新欄位就更新 data-model 的 migration registry」。

**不要再做**：不要以為改完 schema 就結束了。權威文件是 `data-model.md`，`glossary.md` 只管用詞 —— 兩份都要動。

---

## 2026-08-18 加了日誌，一鍵啟動器就壞了 —— 因為它把兩條串流接在一起

**情境**：Stage 4 加上日誌之後，雙擊一鍵啟動器出現「啟動資訊無法解析」。

**做了什麼**：`Launch.ps1` 的前置檢查寫 `& $python @jsonArgs 2>&1`，把 stdout 與 stderr 合成一份文字再 `ConvertFrom-Json`。

**為什麼失敗**：`configure_logging` 會裝一個寫到 stderr 的 handler，所以啟動時多了一行 `INFO ... startup version=0.8.0`。**程式本身完全正確** —— `--json` 的 stdout 仍然是純 JSON，日誌走的是 stderr 這個正確的管道。壞掉的是啟動器：它一開始就不該把兩條串流混在一起。

值得注意的是這個缺陷**跨了兩個元件**：改的是 Python 這邊，壞的是 PowerShell 那邊，而兩邊各自的測試都是綠的。整合點沒有測試，就沒有人守著那個契約。

**結論**：改用 `Start-Process -RedirectStandardOutput/-RedirectStandardError` 分開收兩條串流（順帶避開 PS 5.1 把原生 stderr 包成 ErrorRecord 的坑），並設 `PYTHONIOENCODING=utf-8` 避免導向檔案時退回 cp950。新增 `tests/integration/test_cli_output.py` 把「`--json` 的 stdout 必須是純 JSON」釘成測試。

**不要再做**：不要用 `2>&1` 合併之後再解析結構化輸出。**stdout 是資料、stderr 是說明**，這條界線兩邊都要守。跨元件的契約要有屬於契約本身的測試，不能靠兩邊各自的單元測試。

---

## 2026-08-18 守門測試「通過」了，但它其實什麼都抓不到

**情境**：Stage 4 加 `EXPLAIN QUERY PLAN` 守門，禁止熱查詢退化成全表掃描。七個測試全綠。

**做了什麼**：`_full_scans()` 列出會長大的資料表（`transactions`、`account_postings`…），檢查計畫裡有沒有 `SCAN <表名>`。

**為什麼失敗**：**SQLite 的計畫報的是查詢裡的別名，不是表名。** 實際輸出是 `SCAN t`，不是 `SCAN transactions`。所以那個清單永遠比對不到任何東西 —— 七個測試不是「檢查過而通過」，是「什麼都沒檢查而通過」。把 `idx_transactions_status_occurred` 整個 `DROP` 掉再跑，守門照樣全綠。

發現的方式是刻意注入違規：建一份資料庫、拿掉索引、再跑一次守門。**沒有這一步，這七個測試會以「已經有效能守門了」的身分留在專案裡好幾年。**

**結論**：改成允許清單 —— 除了 FTS 虛擬表與幾個大小固定的小表以外，**任何** `SCAN` 都算違規。重跑注入驗證：有索引時通過，拿掉索引時抓到 `SCAN t`。

**不要再做**：不要用「列出不該出現的東西」當作守門的比對方式 —— 漏列一種寫法就等於沒守。能用允許清單就用允許清單。**而且每個守門都要注入一次真的違規，確認它會紅。**

---

## 2026-08-18 兩個環境都「啟動成功」，`python` 卻是第三個

**情境**：照 README 開程式 —— `conda activate tagcor-ledger` 之後 `python -m tagcor_ledger --gui`，得到 `No module named tagcor_ledger`。

**做了什麼**：那個終端機裡本來就開著另一個專案的 venv，提示字元是 `(.venv) (base)`。`conda activate` 之後變成 `(.venv) (tagcor-ledger)`。

**為什麼失敗**：venv 啟動時把自己的 `Scripts` 放在 PATH **最前面**，`conda activate` 之後它仍然排在前面。**兩個都回報成功、提示字元也都顯示著，但 `python` 解析到的是 venv 那一個。** 錯誤訊息說「沒有這個模組」，指向的方向完全是錯的 —— 模組裝得好好的，只是裝在另一個直譯器裡。

同一個根因還有第二種形態：agent 的工具 shell 以 `-NonInteractive` 啟動、不載入 `profile.ps1`，`conda init powershell` 的 hook 因此沒生效，`conda activate` 會跑在子 process 裡改不到父層環境 —— **回報成功、退出碼 0、實際上什麼都沒換**。

**結論**：新增 `Launch.ps1` 與 `啟動 TagCor Ledger.cmd`，一律用**絕對路徑**呼叫 conda 環境的直譯器，啟動前把繼承來的 `VIRTUAL_ENV`／`PYTHONHOME`／`PYTHONPATH` 清掉，並在啟動前跑一次 `--json` 當前置檢查。已在乾淨環境與刻意重現的 venv 污染環境下各實測通過。

**不要再做**：不要用「`conda activate` 沒報錯」當作環境切換成功的證據。要確認就看 `(Get-Command python).Source`，或者根本不要依賴 PATH。

---

## 2026-08-18 PowerShell 5.1 把原生程式的 stderr 包成例外，錯誤處理因此輪不到

**情境**：寫 `Launch.ps1` 的前置檢查，要在套件沒裝時顯示一句人看得懂的繁中說明。

**做了什麼**：`$ErrorActionPreference = 'Stop'` 之下寫 `$stdout = & $python @jsonArgs 2>&1`，然後 `if ($LASTEXITCODE -ne 0) { 顯示訊息 }`。

**為什麼失敗**：PowerShell 5.1 把**原生程式**被導向的 stderr 每一行包成 `ErrorRecord`（`NativeCommandError`）。在 `Stop` 之下那等於直接丟例外，**底下的 `if` 根本沒執行到**。使用者看到的是 PowerShell 的堆疊與 `At Launch.ps1:127 char:11`，不是我寫的說明。測到這個純粹是因為刻意跑了一次失敗情境 —— 只測成功路徑的話這段程式碼會一直是壞的，而且只在真的出事時才現形。

**結論**：呼叫前後把 `$ErrorActionPreference` 暫時降成 `Continue`，並用 `ConvertTo-PlainText` 只取 `ErrorRecord` 的 `.Exception.Message`，濾掉位置資訊那些雜訊。

**不要再做**：不要在 `$ErrorActionPreference = 'Stop'` 之下對原生程式用 `2>&1`。**錯誤處理路徑沒有實際跑過就等於沒寫**。

---

## 2026-08-18 守門字表的誤報，不拿真的語料跑過就找不到

**情境**：Stage 3 拆檔時在 `sqlite_store.py` 的 docstring 寫了「繼承」，`test_no_simplified_chinese_in_project` 立刻失敗。

**做了什麼**：這個字表在建立時已經對整個專案跑過一次、移掉了五個誤報（`量`、`常`、`伙`、`抽`、`骨`），當時判定為「零誤報」。

**為什麼失敗**：**「對現有檔案跑過沒事」不等於「零誤報」，只等於「現有檔案剛好沒用到那些字」。** `承` 是被當成「繼承」這個詞的一部分收進去的，但被簡化的只有前面那個字，`承` 本身在繁簡是同一個碼位。這類錯誤要等到有人第一次寫到那個字才會現形，而現形的時機一定是在做別的事情的時候。

（本檔不引用簡體字形 —— 唯一可以放簡體字的地方是 `tests/unit/test_traditional_chinese.py`，它會把自己排除在掃描之外。）

**結論**：改成拿**專案以外的真實繁體語料**驗證。對 `D:\Projects\_meta` 與 `D:\Obsidian\Certs` 共 204 個繁體 Markdown 跑一次，一次找出三個誤報：`承`（繼承）、`殖`（繁殖）、`璃`（玻璃），全部移除。字表現有 841 字。

**不要再做**：不要用「以現有專案內容跑過」當作守門零誤報的證據 —— 那是拿被檢查的對象當檢查標準。有語料就用語料，沒有就在 docstring 誠實寫「尚未用外部語料驗證」。

---

## 2026-08-18 指標檔比資料早一步寫入，搬移失敗就等於資料消失

**情境**：把帳務資料從 `%LOCALAPPDATA%` 搬到 `<資料根目錄>` 之前，檢查既有的路徑搬移程式。

**做了什麼**：`LedgerController.save_path_settings` 的順序是「`path_settings.save()` 寫 JSON → `_move_current_database()` 搬資料庫」。

**為什麼失敗**：搬移會因為目標已存在、磁碟滿、資料庫被鎖等原因失敗，而此時 `system_paths.json` **已經**指向新位置。程式下次啟動會在新位置找不到資料庫，於是初始化一個空的 —— 使用者看到的是「所有帳都不見了」。`except` 只回傳失敗 `Result`，完全沒有回滾。這不是理論風險：資料一放到使用者會改名的 `D:\` 路徑上，觸發機率大幅上升。

**結論**：改成「複製到新位置 → 確認成功 → 寫指標檔 → 才刪舊檔」。任何一步失敗都會刪掉新位置的半成品複本，舊資料與舊指標檔原封不動。指標檔本身也改成寫暫存檔再 `os.replace` 的原子寫入。`tests/integration/test_data_paths.py::test_failed_move_leaves_settings_and_source_database_untouched` 鎖住這個行為。

**不要再做**：不要在資料就位之前寫任何指向新位置的指標。順序不是風格問題，是資料安全問題。

---

## 2026-08-18 從 `ledger_dir.parent` 推導其他資料夾，等於讓路徑深度決定資料長在哪

**情境**：設計 `data_root` 約束時檢查現有的路徑解析。

**做了什麼**：`app/paths.py` 與 `ui/controller.py` 都用 `root = ledger_dir.parent`，再由 `root` 推導 `exports/`、`logs/`、`tmp/`。

**為什麼失敗**：`validate_path_settings` 只檢查 `ledger_dir` 與 `backup_dir` 不相同、不互相包含、可寫，**完全沒有**「這些路徑要在同一個根目錄底下」的概念。所以 `ledger_dir` 少一層（例如設成 `<私人資料樹>\Finance\ledger` 而不是 `<資料根目錄>\ledger`），`root` 就變成 `<私人資料樹>\Finance`，程式會在別人的地盤上長出三個資料夾；`backup_dir` 更是可以設到任何可寫的地方。

**結論**：`system_paths.json` 新增明確的 `data_root`，五個資料夾全部由它推導或驗證必須在它底下，違反丟 `PATH_OUTSIDE_DATA_ROOT`。

**不要再做**：不要用「某個設定值的 parent」當成另一批路徑的基準。要有根目錄就明確存一個根目錄。

---

## 2026-08-18 指標檔就住在準備刪掉的那棵樹裡

**情境**：搬遷完成後要清掉 `%LOCALAPPDATA%\TagCor\TagCorLedger\` 這棵舊資料樹。

**做了什麼**：原本打算整棵 `Remove-Item -Recurse`。

**為什麼失敗**：`platformdirs.user_config_dir` 在 Windows 預設回傳 **LOCALAPPDATA** 而不是 Roaming（`roaming=False` 是預設值），所以 `system_paths.json` 的位置是 `%LOCALAPPDATA%\TagCor\TagCorLedger\system_paths.json` —— 和舊資料同一棵樹。整棵刪會把剛寫好的指標檔一起刪掉，程式下次啟動就退回預設路徑，又指回剛被刪掉的位置。

**結論**：只刪 `data`、`backups`、`config`、`exports`、`logs`、`tmp` 六個子資料夾，保留 `system_paths.json`。

**不要再做**：刪任何目錄樹之前先列出內容確認裡面有什麼。`user_config_dir` 與 `user_data_dir` 在 Windows 上會落在同一個父目錄，不要假設它們分開。

---

## 2026-06-27 conda 與 pip 混裝 PySide6 會讓 Qt DLL 載不起來

**情境**：建置與更新開發環境。

**做了什麼**：把 PySide6 放進 `pyproject.toml` 讓 pip 一起安裝，而環境本身是 conda 建的。

**為什麼失敗**：Windows 下 conda 的 PySide6 與 pip 的 PySide6 各自帶一套 Qt DLL，載入順序衝突，症狀是 `ImportError: DLL load failed while importing QtWidgets`。

**結論**：PySide6 只由 `environment.yaml` 的 conda dependency 管理，不放進 `pyproject.toml`。環境已經混裝的話，重建最乾淨。見 commit `593cc47`。

**不要再做**：不要把 PySide6 加回 `pyproject.toml` 的任何 dependency 區塊。

---

## 2026-06-24 CSV 當主資料庫撐不住帳務語意

**情境**：Phase 0–2 的原始設計用年份切分的 `ledger_YYYY.csv` 加 JSON 做主儲存。

**做了什麼**：新增一筆交易要讀寫整個檔案；沒有索引、外鍵，也沒有跨帳戶的原子交易。

**為什麼失敗**：轉帳要同時寫兩筆 posting，CSV 沒有 transaction 保證，中途失敗就是不平的帳。篩選與分頁只能全量載入後在 Python 裡排序，資料一多就沒救。

**結論**：改用 SQLite 作為唯一帳務真實來源，CSV 降級為匯出格式。見 `docs/decisions/ADR-0002-sqlite-canonical-store.md`。

**不要再做**：不要重新加入 CSV/JSON runtime store 或 importer。0.1.x 的資料用 0.2.0 做一次性轉換。
