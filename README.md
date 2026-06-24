# TagCor Ledger

TagCor Ledger 是 Windows-first、本機優先的個人記帳桌面應用程式。核心目標是讓使用者快速記錄收入、支出與帳戶轉帳，同時保有清楚的帳戶餘額、分類搜尋、備份與資料可攜性。

目前版本以 SQLite 作為唯一帳務真實來源，CSV 僅用於舊資料匯入與人類可讀匯出。介面使用 PySide6，所有主要操作與訊息使用繁體中文。

## 核心能力

- 「流向 → 帳戶 → 分類 → 細項」快速記帳。
- 帳戶、兩層分類、對象／商家與備註分開儲存。
- 收入、支出、同幣別轉帳、交易編輯與作廢。
- SQLite WAL、外鍵、索引、FTS5 搜尋與 keyset pagination。
- 舊 CSV/JSON 啟動遷移：先備份、單一交易匯入、可重跑且不重複。
- SQLite 一致性備份、SHA-256 manifest 與 UTF-8 BOM CSV 匯出。

## 安裝

```powershell
conda env create -f environment.yaml
conda activate tagcor-ledger
python -m pip install -e ".[dev]"
```

## 啟動

```powershell
python -m tagcor_ledger --gui
```

指定測試資料目錄：

```powershell
python -m tagcor_ledger --data-dir .\.local-data --init-data --gui
```

預設資料庫位於使用者資料目錄的 `data/ledger.sqlite3`。

## 驗證

```powershell
python -m ruff check --no-cache .
python -m mypy --no-incremental src
python -m pytest -q
```

## 文件

完整入口請見 [docs/index.md](docs/index.md)。重要文件包括：

- [需求規格](docs/requirements/REQ-0001-stable-core.md)
- [架構總覽](docs/architecture/overview.md)
- [資料模型](docs/architecture/data-model.md)
- [UI 流程](docs/architecture/ui-workflows.md)
- [Roadmap](docs/roadmap.md)
- [改動歷史](docs/changelog.md)
- [CODEX.md](CODEX.md)

## 目前邊界

首輪僅支援 TWD 與同幣別轉帳。預算、週期交易、拆分交易 UI、銀行同步、匯率與正式對帳流程列入後續規劃。
