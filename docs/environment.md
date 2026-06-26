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

```powershell
python -m ruff check --no-cache .
python -m mypy --no-incremental src
python -m pytest -q
python -m tagcor_ledger --data-dir .\.local-data-check --init-data --json
```

Python 版本固定為 3.12。GUI dependency 為 Conda 版 PySide6，不應重新加入 PyQt6，也不要用 pip 在此環境升級 `PySide6`。
