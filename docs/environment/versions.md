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

| | `environment.yaml` | `pyproject.toml` | 為什麼 |
|---|:--:|:--:|---|
| `python` | ✅ `=3.12` | ✅ `requires-python >=3.12` | conda 建環境用前者，pip 安裝時檢查後者 |
| `pyside6` | ✅ | ❌ **刻意不寫** | **Windows 下混用 conda／pip 的 PySide6 會讓 Qt DLL 載入失敗。** 放進 pyproject 就會有人用 pip 裝到第二份 |
| `filelock`／`platformdirs`／`tzdata` | ✅ | ✅ | 執行期相依。conda 環境與純 pip 安裝都要拿得到 |
| `pytest`／`pytest-qt`／`ruff`／`mypy` | ✅ | ✅ `[dev]` | **兩邊都宣告，所以兩邊要一致** —— 見下一節 |

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
# 2. 重建環境
conda env update -f environment.yaml --prune
python -m pip install -e ".[dev]"
# 3. 跑完整閘門，含 UI
.\Verify.ps1 -Ui
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
