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
| 直譯器 | conda env `tagcor-ledger`，Python **3.12**（`environment.yaml` 釘死 `=3.12`） |
| GUI | PySide6 6.x，**由 conda 安裝**；`pyproject.toml` 刻意不列它（理由見 [versions.md](versions.md)） |
| 版本界線 | `requires-python >=3.12`；檢查工具四條有上界，理由在 [versions.md](versions.md) |
| 機器可讀的定義 | `environment.yaml`（環境）＋ `pyproject.toml`（套件與 `[dev]`），都在根目錄 |
| **PATH 上那個能不能用** | **不能。** PATH 上的 `python` 幾乎一定是別的直譯器（開發機上是 msys 的 3.14，裸的），沒有 PySide6。一律用 conda 環境的**完整路徑**：`tools\Launch.ps1`／`tools\Verify.ps1` 會自己找，找不到時設 `TAGCOR_PYTHON`（見 §5） |

## 2. 怎麼建

第一次：

```powershell
conda env create -f environment.yaml
conda activate tagcor-ledger
python -m pip install -e ".[dev]"
```

`environment.yaml` 會安裝 conda 版 PySide6；`pip install -e ".[dev]"` 只安裝本專案的
editable package 與非 Qt 的 Python 相依。**不要用 pip 裝或升 PySide6** —— Windows 下混用
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
.\tools\Verify.ps1               # 路徑漂移 → Qt 型別 stub → agent 檔同步 → ruff → mypy --strict → pytest
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
`.githooks/pre-push`（加全部測試，約 70 秒）、GitHub Actions（同 pre-push，少了量像素的那 21 條）。
第一次 clone 要跑一次 `git config core.hooksPath .githooks`。

## 4. 怎麼更新

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
4. 更新完跑 `.\tools\Verify.ps1 -Ui`。**升 `ruff` 或 `mypy` 之後要看的不是「有沒有紅」，
   是「紅的是什麼」** —— 新版開了新規則屬於預期。

## 5. 環境變數

| 變數 | 誰讀 | 做什麼 |
|---|---|---|
| `TAGCOR_PYTHON` | `tools\Resolve-TagcorPython.ps1`（`tools\Launch.ps1`、`tools\Verify.ps1` 共用）、`.githooks\resolve-python.sh`、`.vscode\settings.json` | 指定 conda 環境的 `python.exe`，優先於自動偵測。conda 裝在非標準位置時設一次：`setx TAGCOR_PYTHON "X:\path\to\envs\tagcor-ledger\python.exe"` |
| `TAGCOR_RUN_PERFORMANCE` | `tests\`（效能測試的開關） | `1` 才跑 20 萬筆那條；`tools\Verify.ps1 -Performance` 會自己設 |
| `QT_QPA_PLATFORM` | Qt | `offscreen` 跑 UI 測試（`tools\Verify.ps1` 會自己設）；截圖驗收用 `windows` |
| `PYTHONIOENCODING` | Python | `tools\Launch.ps1` 設成 `utf-8`：導向檔案時 Python 會用系統地區編碼（cp950），路徑含中文會亂碼 |

程式本身**不讀任何環境變數決定資料位置** —— 資料根只來自指標檔
`%LOCALAPPDATA%\TagCor\TagCorLedger\system_paths.json` 或 `--data-dir`（開發用）。

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

## 環境快照

`docs\environment\snapshots\` 是 `-Report` 類產生物的位置（目前這個專案的 `tools\Verify.ps1`
**沒有** `-Report`，所以這個資料夾還不存在）。要加的時候照 `_meta\templates\tools\Verify.ps1`
那一段：**去識別化，而且產快照前先把它要抓的東西塞回去驗一次**。
