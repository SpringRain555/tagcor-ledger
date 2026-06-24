# 開發環境

## 建立

```powershell
conda env create -f environment.yaml
conda activate tagcor-ledger
python -m pip install -e ".[dev]"
```

## 更新

```powershell
conda env update -f environment.yaml --prune
python -m pip install -e ".[dev]"
```

## 驗證

```powershell
python -m ruff check --no-cache .
python -m mypy --no-incremental src
python -m pytest -q
python -m tagcor_ledger --data-dir .\.local-data-check --init-data --json
```

Python 版本固定為 3.12。GUI dependency 為 PySide6，不應重新加入 PyQt6。
