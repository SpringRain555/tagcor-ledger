# 版本界線與它們的理由

**一條沒有理由的版本界線，下一個人不知道能不能動，於是它永遠不會被動。**
這一份回答三件 `environment.yaml` 與 `pyproject.toml` 各自回答不了的事：

1. **每條界線在哪裡宣告**（有幾條宣告在**兩個**檔案裡）；
2. **哪幾條必須一起動**；
3. **怎麼升，以及升完要跑什麼**。

> **界線本身的權威仍然是那兩個檔案**（`conda env create -f` 與 pip 讀的是它們）。
> 這一份是散文，**不是定義** —— 兩邊不一致時以那兩個檔案為準，然後回來修這一份。
> 分界線是「誰在讀它」：工具讀的留根目錄，人讀的進 `docs/`（CONVENTIONS §12）。

---

## 宣告在哪

| 套件／項目 | `environment.yaml` | `pyproject.toml` | `verify.yml` | `tools/env_floors.json` | 為什麼 |
|---|---|---|---|---|---|
| `python` | ✅ `>=3.12.16,<3.13` | ✅ `requires-python >=3.12` | — | ✅ 實際版本檢查 | conda 安全地板比套件通用下界嚴；pip 安裝時仍以 Python 3.12 為最低支援線 |
| `pyside6`／Qt | ✅ `>=6.11.3` | ❌ **刻意不寫** | ✅ `PySide6==6.11.3` | ✅ PySide6 與 Qt 檢查 | Windows 下混用 conda／pip 的 PySide6 會讓 Qt DLL 載入失敗；CI 是乾淨 Linux venv |
| `openssl` | ✅ `>=3.5.9,<3.6` | — | — | ✅ | Python 3.12 的 conda 環境使用的 OpenSSL 安全地板 |
| `libexpat` | ✅ `>=2.9.0` | — | — | ✅ | conda Python 實際連結的 Expat 安全地板 |
| `libsqlite` | ✅ `>=3.54.0` | — | — | ✅ | SQLite 安全地板；App 使用 FTS5 |
| `pip`／`setuptools` | ✅ | setuptools ✅ build-system | — | ✅ | 建置工具的安全地板 |
| `filelock` | ✅ `>=3.20.3` | ✅ `>=3.20.3` | — | ✅ | 執行期相依，conda 與純 pip 安裝都要拿得到 |
| `platformdirs`／`tzdata` | ✅ | ✅ | — | — | 執行期相依，conda 環境與純 pip 安裝都要拿得到 |
| `pytest`／`pytest-qt`／`ruff`／`mypy` | ✅ | ✅ `[dev]` | CI 使用 `[dev]` | — | **兩邊都宣告，所以兩邊要一致** —— 見下一節 |
| 版本地板清單 | — | — | — | ✅ | `check_env_floors.py` 的機器可讀設定；測試比對它與其他宣告 |

## 安全下界

**下界是安全地板：等於最後一個修掉已知漏洞的版本。** 實際探測目前執行中的直譯器，
結果由 `tools/check_env_floors.py` 讀取 `tools/env_floors.json` 檢查。

| 套件 | 下界 | 為什麼 | 宣告在哪 |
|---|---|---|---|
| Python | `>=3.12.16,<3.13` | CVE-2026-115557（ssl 撤銷外洩的 eMudhra 中繼 CA）、CVE-2026-114583（tarfile `tar_filter` 連結覆蓋）、CVE-2024-3220（Windows 預設讀取 `mimetypes.knownfiles`） | `environment.yaml` |
| libexpat | `>=2.9.0` | CVE-2026-77214、CVE-2026-102633；conda 的 Python 連的是這份 libexpat，不是 Python 原始碼內附的版本 | `environment.yaml` |
| OpenSSL | `>=3.5.9,<3.6` | 3.6 線於 2026-11-01 停止支援後不再接收 CVE 修補；3.5 是 LTS（支援至 2030-04-08）；Python 3.12 的 conda build 要求 `<4` | `environment.yaml` |
| libsqlite | `>=3.54.0` | CVE-2026-119378（R-Tree use-after-free）、CVE-2026-119374（FTS5 secure-delete 溢位）；3.53.2 修補 CVE-2026-11822／CVE-2026-11824。App 使用 FTS5 | `environment.yaml` |
| PySide6（含 Qt） | `>=6.11.3` | Qt 6.11.2／6.11.3 修補 CVE-2026-19248、CVE-2026-78253、CVE-2026-76151、CVE-2026-105946、CVE-2026-79616、CVE-2026-105923 | `environment.yaml`；CI 的 `verify.yml` 固定同版 |
| pip | `>=26.2` | 修補 CVE-2026-1703、CVE-2026-6357、CVE-2026-8643、CVE-2026-13346 | `environment.yaml` |
| setuptools | `>=78.1.1` | 修補 CVE-2025-47273 | `environment.yaml`、`pyproject.toml` 的 build-system |
| filelock | `>=3.20.3` | 修補 CVE-2025-68146、CVE-2026-22701 | `environment.yaml`、`pyproject.toml` |

更新安全地板時，先查 conda-forge、OSV 與官方公告確認修補版本，再同步核對
`environment.yaml`、`pyproject.toml`、`.github/workflows/verify.yml`、`tools/env_floors.json`
四處各自適用的宣告，重建環境後跑 `.\tools\Verify.ps1 -Ui`。

GitHub Dependabot 只看得到 `pyproject.toml` 的 PyPI 套件；它看不到 conda 原生套件
（Qt、OpenSSL、Expat、SQLite），OSV 也沒有 Conda ecosystem。這一側的版本地板只由
`check_env_floors.py` 檢查。

## 必須一起動的

### 1. 檢查工具的上界：`environment.yaml` ↔ `pyproject.toml` 的 `[dev]`

`pytest`、`pytest-qt`、`ruff`、`mypy` 這四條**同時寫在兩個檔案裡**，
而**真正建出環境的是 `environment.yaml`**。只改 `pyproject.toml` 的話，
新 clone 拿到的 ruff／mypy 可能落在宣告範圍之外，本機與 CI 就會不同。

**2026-09-01 踩過一次**：pyproject 加了上界而 yaml 沒有，兩份對不上。

### 2. `tzdata` 的兩個地方

`zoneinfo.ZoneInfo("Asia/Taipei")` 要有 IANA 時區資料庫，而 **Windows 沒有系統層的
那一份**。conda 的 Python 附了 tzdata，所以這個相依一直是隱形的 ——
2026-09-01 在一個純 pip venv 上實測，**29 個測試直接 collection error**。

**不加 `; sys_platform == "win32"` 標記。**「因為作業系統剛好附了所以能跑」正是那個
bug 的成因，而精簡過的 Linux 容器也可能沒有 tzdata。約 1 MB，無條件裝比較誠實。

### 3. PySide6 安全地板的四處同步

`tools/env_floors.json`、`environment.yaml`、`pyproject.toml`、`.github/workflows/verify.yml`
要共同維護 PySide6 地板的關聯。PySide6 只列在 conda 環境，`pyproject.toml` 明確不列；
CI 的乾淨 Linux venv 固定安裝同一版，而 floor 檔提供本機檢查器的下界。測試會比對這四處，
確保 conda 與 CI 同版，且不把 PySide6 加進 pip 相依。

## 為什麼有上界

**上界是必要的，不是保守。** `[dev]` 那四條原本是 `ruff>=0.4` 這種開放範圍，
於是 CI 裝到最新版而本機是 0.15.x —— 兩邊的預設規則集不同，同一份程式碼
**本機綠、CI 紅**（2026-09-01 第一次跑 CI 就踩到：新版 ruff 預設開了 I001 import 排序）。

**一個會因為別人發新版而變紅的閘門，紅的時候不代表你改壞了什麼**，
而那種紅燈很快就會被學會忽略。

執行期相依（`filelock`、`platformdirs`、`tzdata`）**沒有上界** ——
它們的 API 面很小、也不參與閘門，發新版不會讓測試無故變紅。

## 怎麼升

有意識地做，一次一組：

```powershell
# 1. 兩個檔案的同一條一起抬（檢查工具四條務必兩邊都改）
# 2. 重建環境，讓傳遞相依也換到新版本
conda env remove -n tagcor-ledger
conda env create -f environment.yaml
conda activate tagcor-ledger
python -m pip install -e ".[dev]"
# 3. 跑完整閘門，含 UI
.\tools\Verify.ps1 -Ui
```

**升 `ruff` 或 `mypy` 之後要看的不是「有沒有紅」，是「紅的是什麼」** ——
新版開了新規則屬於預期，要決定的是照著改還是關掉那條規則。

## 刻意不裝的

| | 為什麼 |
|---|---|
| **PyQt6** | 這個專案用 PySide6（[ADR-0003](../decisions/ADR-0003-pyside6.md)、[ADR-0009](../decisions/ADR-0009-keep-pyside6.md)）。兩套 Qt binding 同時存在會讓 DLL 搜尋路徑更亂 |
| **pip 版的 PySide6** | 同上 —— `ImportError: DLL load failed while importing QtWidgets` |
| 任何網路函式庫 | 這個 App **完全不連網**，那是刻意的設計（`AGENTS.md`）|
| `@mermaid-js/mermaid-cli` | 產圖工具，用 `npx` 用到才下載。它會拉 Chromium 進 `node_modules`（數百 MB），為一個月用兩次的東西背著它不划算 |
