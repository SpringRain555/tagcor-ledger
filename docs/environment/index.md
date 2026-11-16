# 環境：怎麼建、怎麼驗證、怎麼更新

**這個專案靠 conda 環境 `tagcor-ledger`（Python 3.12）跑；PySide6 由 conda 管。**
專案裡沒有 `.venv`、沒有 Node。每條版本上下界**為什麼是那個範圍**、哪幾條要一起動，
在 [versions.md](versions.md)。這一份是 CONVENTIONS §12 的「專案環境文件」——
環境的散文權威，六個段落固定。

> **機器可讀的定義不在這一區。** `environment.yaml` 是 `conda env create -f` 的
> 慣例位置，`pyproject.toml` 是 pip 的 —— 那是外部工具規定的，不是我們選的。
> 這一區裝的是散文。

## 1. runtime 與版本

| | |
|---|---|
| 直譯器 | conda env `tagcor-ledger`，Python **≥ 3.12.16、< 3.13**（`environment.yaml` 的安全地板） |
| GUI | PySide6 6.x，**由 conda 安裝**；`pyproject.toml` 刻意不列它（理由見 [versions.md](versions.md)） |
| 共用啟動套件 | `local-qt-app` **0.1.0**，由 repo 內 `vendor/` 的 wheel 安裝 |
| 版本界線 | `requires-python >=3.12`；檢查工具四條有上界，理由在 [versions.md](versions.md) |
| 機器可讀的定義 | `environment.yaml`（環境）＋ `pyproject.toml`（套件與 `[dev]`），都在根目錄 |
| **PATH 上那個能不能用** | **不能。** PATH 上的 `python` 幾乎一定是別的直譯器（開發機上是 msys 的 3.14，裸的），沒有 PySide6。一律用 conda 環境的**完整路徑**：`tools\Launch.ps1`／`tools\Verify.ps1` 會自己找，找不到時設 `TAGCOR_PYTHON`（見 §5） |

`environment.yaml` 明列 `nodefaults`：全域 condarc 是 defaults＋flexible，沒有這一列時，
未指定來源的相依可能從 defaults 安裝；目前環境約有 20 個套件來自 defaults。

## 2. 怎麼建

第一次：

```powershell
conda env create -f environment.yaml
conda activate tagcor-ledger
python -m pip install -e ".[dev]"
```

`environment.yaml` 會安裝 conda 版 PySide6，並從 `vendor/local_qt_app-0.1.0-py3-none-any.whl`
安裝共用啟動套件；`pip install -e ".[dev]"` 只安裝本專案的 editable package 與非 Qt 的
Python 相依。**不要用 pip 裝或升 PySide6** —— Windows 下混用
conda／pip 版會讓 Qt DLL 搜尋路徑混亂，症狀是
`ImportError: DLL load failed while importing QtWidgets`。已經混裝的話重建環境（§4）。

**agent 在工具 shell 裡不要 `conda activate`**：那種 shell 以 `-NonInteractive` 啟動、不載入
profile，`conda activate` 會回報成功、退出碼 0、實際上什麼都沒換（2026-08-18 實測）。
一律用完整路徑：

```powershell
& $env:TAGCOR_PYTHON -m tagcor_ledger --json
```

## 3. 怎麼驗證

```powershell
.\tools\Verify.ps1               # 路徑漂移 → Qt 型別 stub → agent 檔同步 → 版本地板 → ruff → mypy --strict → pytest
.\tools\Verify.ps1 -Ui           # 加跑 tests\ui（自動設 QT_QPA_PLATFORM=offscreen；改過 UI 就用這個）
.\tools\Verify.ps1 -Performance  # 加跑 20 萬筆的效能測試
```

全綠長這樣：每一段 `OK`，最後一行「全部通過。」，exit 0。**最常紅的是路徑漂移** ——
`.claude\settings.json` 的清單與指標檔的 `data_root` 對不上（改資料路徑是三步，見 `AGENTS.md`）；
還沒設定過資料路徑的機器用 `-SkipDrift`。

要單獨跑某一段：

```powershell
python -m ruff check --no-cache .
python -m mypy --no-incremental src
python -m pytest -q
python -m tagcor_ledger --data-dir .\.local-data-check --init-data --json
```

`tests\ui` 需要 `QT_QPA_PLATFORM=offscreen`；**要看實機畫面**（截圖驗收）時改用 `windows`，
offscreen 沒有中文字型，中文會渲染成豆腐塊。

三層閘門各擋不同的東西：`.githooks/pre-commit`（ruff ＋ mypy，約 2 秒）、
`.githooks/pre-push`（加全部測試，約 70 秒）、GitHub Actions（同 pre-push，少了量像素的那幾條）。
第一次 clone 要跑一次 `git config core.hooksPath .githooks`。

## 4. 怎麼更新

`conda env update -f environment.yaml --prune` 不會升級傳遞相依（例如 libexpat、OpenSSL），
也不會把已從 defaults 安裝的套件換成 conda-forge 版本。更新安全版本時，重建環境
（`conda env remove -n tagcor-ledger` 後 `conda env create -f environment.yaml`），
或執行 `conda update -n tagcor-ledger --all`。**每次升版本號之後都要重跑**
`python -m pip install -e ".[dev]"`，否則 editable 安裝 metadata 可能與 `pyproject.toml` 不同，
版本地板檢查會失敗。

1. **升一個套件**：改 `environment.yaml`（**與 `pyproject.toml` 的 `[dev]` 同一條要一起改** ——
   四條檢查工具兩邊都宣告，只改一邊本機與 CI 就會不同，[versions.md](versions.md)），然後
   ```powershell
   conda env update -f environment.yaml --prune
   python -m pip install -e ".[dev]"
   ```
2. **換一代 Python**：`environment.yaml` 的 `python=`、`pyproject.toml` 的 `requires-python`、
   [versions.md](versions.md) 的理由，三處一起動；然後重建環境。
3. **環境已經混裝 conda／pip 版 PySide6**：不要修，重建 ——
   ```powershell
   conda deactivate
   conda env remove -n tagcor-ledger
   conda env create -f environment.yaml
   conda activate tagcor-ledger
   python -m pip install -e ".[dev]"
   ```
4. **升級共用啟動套件**：換掉 `vendor/` 的 wheel，並同步改 `environment.yaml` 與
   `.github/workflows/verify.yml` 的 wheel 檔名。從 repo 根目錄重裝後跑 Verify：
   ```powershell
   $wheel = Get-ChildItem .\vendor\local_qt_app-*.whl
   python -m pip install --no-deps --force-reinstall $wheel.FullName
   .\tools\Verify.ps1 -Ui
   ```
   wheel 只從 repo 內安裝；不要在 `pyproject.toml` 用套件名稱宣告，也不要指向共用原始碼資料夾。
5. 其他更新完跑 `.\tools\Verify.ps1 -Ui`。**升 `ruff` 或 `mypy` 之後要看的不是「有沒有紅」，
   是「紅的是什麼」** —— 新版開了新規則屬於預期。

## 5. 環境變數

| 變數 | 誰讀 | 做什麼 |
|---|---|---|
| `TAGCOR_PYTHON` | `tools\Resolve-TagcorPython.ps1`（`tools\Launch.ps1`、`tools\Verify.ps1` 共用）、`.githooks\resolve-python.sh`、`.vscode\settings.json` | 指定 conda 環境的 `python.exe`，優先於自動偵測。conda 裝在非標準位置時設一次：`setx TAGCOR_PYTHON "X:\path\to\envs\tagcor-ledger\python.exe"` |
| `TAGCOR_RUN_PERFORMANCE` | `tests\`（效能測試的開關） | `1` 才跑 20 萬筆那條；`tools\Verify.ps1 -Performance` 會自己設 |
| `QT_QPA_PLATFORM` | Qt | `offscreen` 跑 UI 測試（`tools\Verify.ps1` 會自己設）；截圖驗收用 `windows` |
| `PYTHONIOENCODING` | Python | `tools\Launch.ps1` 設成 `utf-8`：導向檔案時 Python 會用系統地區編碼（cp950），路徑含中文會亂碼 |
| `TAGCOR_LEDGER_DATA_DIR` | `src/tagcor_ledger/app/paths.py` | **開發與測試用的覆寫**：有值時直接當資料根，**完全不讀指標檔**（跟 `--data-dir` 同一條路）。`tests/integration/test_startup_failures.py` 會先把它刪掉，才測得到指標檔那條路 |
| `TAGCOR_REFERENCE_DB` | `src/tagcor_ledger/application/reference.py` | 換掉法規參考庫的位置（預設是 repo 的 `reference\reference.sqlite3`，它是公開資訊、不是帳務資料）。UI 測試用它指到暫存檔 |
| `TAGCOR_TAX_DATA` | `src/tagcor_ledger/application/tax/loader.py` | 換掉稅務資料的位置（預設是 repo 的 `reference\tax\dataset.json`，它是公開資訊、不是帳務資料）；測試用它指到假資料 |

資料根平常來自指標檔 `%LOCALAPPDATA%\TagCor\TagCorLedger\system_paths.json`；沒有指標檔時依序找程式資料夾的
`userdata`、使用者資料夾，都沒有帳本就在第一次啟動時問（[儲存配置](../architecture/storage-layout.md)、ADR-0018）。`--data-dir` 與
`TAGCOR_LEDGER_DATA_DIR` 是開發與測試用的覆寫 —— **不要把後者設成使用者層環境變數**：它會被每一個行程繼承，
包括測試（`D:\Projects\_meta\CONVENTIONS.md` §11）。

## 6. 已知的坑

只放環境層的；程式邏輯的坑在 [`lessons.md`](../lessons.md)。

- **終端機裡開著別的專案的 venv 時 `conda activate tagcor-ledger` 會靜靜地失敗**：
  venv 的 `Scripts` 排在 PATH 最前面，兩個環境名都出現在提示字元上，`python` 卻是 venv 那一個，
  症狀 `No module named tagcor_ledger`。`(Get-Command python).Source` 可以確認；先 `deactivate`
  或直接雙擊 `start_tagcor-ledger.cmd`（它不碰 PATH）。
- **工具 shell 的 `conda activate` 回報成功但什麼都沒換**（§2）。
- **conda／pip 混裝 PySide6 → `DLL load failed`**（§2、§4）。
- **`tzdata` 在純 pip venv 上會缺**：conda 的 Python 附了它，所以這個相依一直是隱形的；
  純 pip 環境 29 個測試直接 collection error（2026-09-01）。已無條件列進相依，[versions.md](versions.md)。
- **PySide6 的 `py.typed` 標記**：少了它 mypy 會安靜地把整個 Qt 當成 `Any`，`--strict` 什麼都沒在檢查。
  `tools\Verify.ps1` 的「Qt 型別 stub」那一段會補標記並驗 `QtWidgets.pyi` 在。
- **編碼**：`.ps1` 必須有 UTF-8 BOM（PS 5.1 否則當 Big5 讀，中文全毀）；`.md`／`.json` 不要 BOM；
  `.cmd` 純 ASCII（cmd.exe 的字碼頁不可靠）。行尾由 `.gitattributes` 管，與 BOM 是兩回事。
- **`core.autocrlf = true` 的機器上，工作樹的行尾不是統一的**：git 存 LF、簽出多半 CRLF，但有些檔案
  簽出來就是 LF。腳本要「改一下再還原」某個檔案時一律走 bytes，片段裡的 `\n` 換成那個檔案自己的換行；
  「內容到底有沒有變」用 `git hash-object` 比，不看 `git status` 的 ` M`（[`lessons.md`](../lessons.md) 2026-08-22）。
- **不要用 `conda.bat` 傳含 `>`、`<` 的版本規格**：PowerShell 呼叫 `.bat` 會經過 `cmd.exe`，
  `pkg>=1.2` 的 `>` 會被當成輸出重導向，在目前目錄建立以版本號命名的檔案，指令本身不會印出內容
  （2026-11-08 在 repo 根目錄曾產生 6 個檔案）。改用 `Scripts\conda.exe`，或把規格寫進
  `environment.yaml`。
- **research runtime 的安全修補（2026-11-09 記、2026-11-16 處理）。** `tools\law_sync\fetch_laws.py`、`tools\fetch.py`
  用的 research runtime 原本是 Python 3.12.13＋certifi 2026.7.22，現在是 **3.12.16**（python.org 2026-10-25
  的加急安全版：`ssl` 擋下外洩的 eMudhra 中繼 CA 金鑰等）＋ certifi 2026.10.23。`D:\Claude_Workspace\claude-skills`
  的治理工具改成 Python 釘到 patch、裝在 `~\.claude\runtimes\_python` 這個獨立目錄，所以升 patch 不再連帶換掉
  掛在 uv 共用 3.12 連結上的其他 venv（`sandbox-spectrum` 的 `.venv` 也改成直接連 3.12.13）。做法與踩到的坑
  寫在那個 repo 的 README〈Python 的 pin 與安裝位置〉。抓回來的稅務數字照舊一律經使用者看過差異與出處才 commit（REQ-0011）。

## 環境快照

`docs\environment\snapshots\` 是 `-Report` 類產生物的位置（目前這個專案的 `tools\Verify.ps1`
**沒有** `-Report`，所以這個資料夾還不存在）。要加的時候照 `_meta\templates\tools\Verify.ps1`
那一段：**去識別化，而且產快照前先把它要抓的東西塞回去驗一次**。
