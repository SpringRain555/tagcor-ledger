# 開發環境

## 建立

```powershell
conda env create -f environment.yaml
conda activate tagcor-ledger
python -m pip install -e ".[dev]"
```

`environment.yaml` 會安裝 Conda 版 PySide6。`python -m pip install -e ".[dev]"` 只安裝本專案 editable package 與非 Qt Python dependency。Windows 下混用 Conda/Pip 版 PySide6 會讓 Qt DLL 搜尋路徑混亂，可能導致 `ImportError: DLL load failed while importing QtWidgets`。

## 更新

```powershell
conda env update -f environment.yaml --prune
python -m pip install -e ".[dev]"
```

若環境已經混裝 Conda/Pip 版 PySide6，優先重建環境：

```powershell
conda deactivate
conda env remove -n tagcor-ledger
conda env create -f environment.yaml
conda activate tagcor-ledger
python -m pip install -e ".[dev]"
```

## 驗證

**平常一律跑 `Verify.ps1`**，它把路徑漂移檢查、ruff、mypy --strict 與 pytest 串在一起：

```powershell
.\Verify.ps1          # 不含 tests\ui
.\Verify.ps1 -Ui      # 含 tests\ui（改過 UI 就用這個）
.\Verify.ps1 -Performance   # 20 萬筆的效能測試
```

要單獨跑某一段時：

```powershell
python -m ruff check --no-cache .
python -m mypy --no-incremental src
python -m pytest -q
python -m tagcor_ledger --data-dir .\.local-data-check --init-data --json
```

`tests\ui` 需要 `QT_QPA_PLATFORM=offscreen`；**要看實機畫面**（截圖驗收）時改用
`windows`，offscreen 沒有中文字型，中文會渲染成豆腐塊。

Python 版本固定為 3.12。GUI dependency 為 Conda 版 PySide6，不應重新加入 PyQt6，也不要用 pip 在此環境升級 `PySide6`。
