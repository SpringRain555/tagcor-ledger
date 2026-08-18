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
