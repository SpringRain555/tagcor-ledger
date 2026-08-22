# TagCor Ledger

> **歷史文件，不是規格。** 這是 SQLite 穩固核心版之前的 CSV／PyQt6 時代規劃，
> 已被 [`docs/index.md`](../../index.md) 指向的現行文件取代。
> grep 撈到這裡的話，你要的答案在別的地方。

## 簡介

TagCor Ledger 是一個以四層標籤為核心的本機桌面記帳工具。第一階段規劃使用 Python + PyQt6 建立鍵盤優先的快速記帳體驗，資料先以 CSV + JSON 保存，並預留未來切換 SQLite 的架構。

## 文件

- [計劃書.md](計劃書.md)：產品目標、完整架構、資料模型、核心流程、里程碑與驗收條件。
- [資料格式規格.md](資料格式規格.md)：長期使用導向的 CSV/JSON schema、驗證規則、snapshot、備份、manifest 與 migration 規則。
- [模組化與階段實作.md](模組化與階段實作.md)：適中顆粒的模組邊界、依賴方向、打包保留空間與階段性實作內容。
- [CODEX-old.md](CODEX-old.md)：當時供 Codex 與後續開發者遵循的專案開發指南。

## 開發環境

使用 conda 建立環境：

```powershell
conda env create -f environment.yaml
conda activate tagcor-ledger
python -m pip install -e ".[dev]"
```

## Phase 0/1/2 驗收

Phase 0 完成「專案骨架與可打包入口」，Phase 1 完成「資料核心與基礎設施」，Phase 2 完成「交易主線 MVP」。可用以下指令驗收：

```powershell
python -m pytest -q
python -m tagcor_ledger --json
python -m tagcor_ledger --data-dir .\.local-data --init-data --json
python -m tagcor_ledger --data-dir .\.local-data --gui
```

驗收重點：

- `python -m tagcor_ledger` 可執行。
- 啟動資訊會列出使用者資料目錄、config/data/log/backup/tmp 路徑。
- `--init-data` 會建立資料目錄結構與 Phase 1 初始資料檔。
- `config/settings.json`、`config/tags.json`、`config/templates.json`、年度 `ledger_YYYY.csv`、`config/data_manifest.json` 會被建立。
- GUI 可用 `--gui` 啟動，新增交易後會寫入 ledger、audit log，並更新最近交易列表。
- 測試可通過。

若尚未安裝 pytest，可先用內建 Python 做 smoke check：

```powershell
$env:PYTHONPATH = "src"
python -m compileall -q src tests
python -m tagcor_ledger --data-dir .\.local-data-smoke --init-data --json
python -c "import json, tempfile; from pathlib import Path; from tagcor_ledger.app.paths import resolve_app_paths; from tagcor_ledger.infrastructure.repositories import initialize_data_store; from tagcor_ledger.infrastructure.csv_ledger import CsvLedgerRepository; td=tempfile.TemporaryDirectory(); paths=resolve_app_paths(Path(td.name)/'ledger-data'); written=initialize_data_store(paths); assert written['manifest'].is_file(); assert CsvLedgerRepository(written['ledger']).read_rows() == []; td.cleanup(); print('phase1 smoke check passed')"
python -c "import tempfile; from pathlib import Path; from tagcor_ledger.app.paths import resolve_app_paths; from tagcor_ledger.infrastructure.repositories import initialize_data_store; from tagcor_ledger.application.transactions import AddTransaction, AddTransactionRequest, ListRecentTransactions; from tagcor_ledger.domain.models import TagPath; td=tempfile.TemporaryDirectory(); paths=resolve_app_paths(Path(td.name)/'ledger-data'); initialize_data_store(paths); result=AddTransaction(paths).execute(AddTransactionRequest(occurred_at='2026-05-08T08:30:00+08:00', entry_type='expense', amount='85', tag_path=TagPath('tag_expense','tag_cash','tag_food','tag_711'), description='早餐')); assert result.success, result.message; recent=ListRecentTransactions(paths).execute(); assert recent.details['transactions'][0]['tag_path_name']=='支出 / 現金 / 伙食 / 7-11'; td.cleanup(); print('phase2 transaction smoke check passed')"
```

## 目前狀態

目前已完成 Phase 0、Phase 1 與 Phase 2：專案骨架、package entry point、路徑解析、資源讀取、資料格式 validator、CSV/JSON repository、atomic writer、audit writer、manifest generator、交易新增 use case、最近交易查詢、Tag path snapshot 與最小 PyQt UI。
