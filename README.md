# TagCor Ledger

TagCor Ledger 是 Windows-first、本機優先的個人記帳工具。核心資料使用 SQLite，介面使用 PySide6，目標是快速記錄收支、轉帳、餘額盤點與待確認週期項目，同時保持資料可備份、可還原、可長期維護。

目前版本：0.6.0（Phase 4：操作/系統設定重整、資料路徑分離、用詞與記帳欄位精簡）。

## 目前功能

- 快速記帳流程：流向 → 帳戶 → 類別 → 項目 → 時間 → 金額 → 備註。
- 收入、支出、同幣別 TWD 轉帳。
- 交易紀錄支援文字、日期、帳戶、類別與狀態篩選，使用 keyset pagination。
- 帳戶、類別與項目可新增、重新命名、封存、恢復、刪除未使用。
- 模板、週期排程、待確認項目與批次確認。
- 餘額盤點與未解釋差額追蹤；盤點不會直接入帳。
- 記帳資料路徑與備份路徑可分開設定。
- 備份只在使用者手動按下「建立完整備份」時執行。
- 還原與重製前可勾選「先建立備份」，不再強制自動備份。
- UTF-8 BOM CSV 匯出供交換與人工閱讀；SQLite 是唯一主資料庫。

## 安裝

建議讓 Conda 管理 PySide6/Qt，避免 Windows Qt DLL 衝突。

```powershell
conda env create -f environment.yaml
conda activate tagcor-ledger
python -m pip install -e ".[dev]"
```

如果曾用 pip 安裝 PySide6 後遇到 `ImportError: DLL load failed while importing QtWidgets`，請重建環境或執行：

```powershell
conda env update -f environment.yaml --prune
conda activate tagcor-ledger
python -m pip install -e ".[dev]"
```

## 啟動

一般使用：

```powershell
python -m tagcor_ledger --gui
```

開發或測試時指定資料根目錄：

```powershell
python -m tagcor_ledger --data-dir .\.local-data --init-data --gui
```

輸出啟動路徑資訊：

```powershell
python -m tagcor_ledger --data-dir .\.local-data --init-data --json
```

未指定 `--data-dir` 時，程式會使用外部系統設定檔中的路徑。可在「系統設定 → 資料路徑」設定：

- 記帳資料路徑：存放 `ledger.sqlite3`、`ledger.sqlite3-wal`、`ledger.sqlite3-shm`。
- 備份路徑：存放 `backup_YYYYMMDD_HHMMSS_xxxxxx/ledger.sqlite3` 與 `backup_manifest.json`。

備份路徑不可與記帳資料路徑相同，也不可互相包含。

## 操作方式

### 快速記帳

1. 選擇流向：支出、收入或轉帳。
2. 選擇帳戶；支出/收入再選「類別」與「項目」，轉帳改選轉入帳戶。
3. 填寫時間、TWD 整數金額與備註。
4. 按「儲存交易」。

「項目」用來描述具體收支項目，例如早餐、捷運、7-11。備註用來補充當次交易的額外資訊。Phase 4 已移除「對象／商家」欄位。

快捷鍵：

- `Ctrl+N`：回到快速記帳並聚焦金額欄位。
- `Ctrl+S`：儲存快速記帳表單。
- `Esc`：清空快速記帳表單。

### 交易紀錄

- 可用文字、日期區間、帳戶、類別與狀態組合篩選。
- 每頁筆數由「系統設定 → 一般設定」設定為 20、50 或 100。
- 「複製到快速記帳」會使用目前時間，並帶入帳戶、類別/項目、金額與備註。
- 支出與收入可編輯；轉帳採「替換轉帳」：建立新轉帳並作廢舊轉帳，兩者在同一 SQLite transaction 完成。
- 作廢交易不刪除歷史資料，會保留 audit 與餘額可追蹤性。

### 餘額盤點

餘額盤點用來記錄某帳戶當下實際金額，盤點本身不會建立交易，也不會改變帳戶餘額。

差額計算規則：

- 第一筆盤點前，以帳戶期初餘額作為基準。
- 後續盤點以「上一筆有效盤點」作為基準。
- 預期金額 = 上次盤點實際金額 + 兩次盤點間有效 posting 加總。
- 未解釋差額 = 本次盤點實際金額 - 預期金額。

補記、編輯或作廢交易後，差額會依交易時間自動重新計算。

### 操作設定

「操作設定」包含三個區塊：

- 帳戶：新增、重新命名、封存、恢復、刪除未使用。
- 類別：管理第一層類別。
- 項目：在類別底下管理第二層項目。
- 模板與週期排程：建立模板、建立週期排程、產生待確認項目。

刪除只適用完全未被交易、盤點、模板、排程或待確認項目引用的設定項。已有歷史資料者請用封存，以維持帳務一致性。預設帳戶不可刪除，需先切換預設帳戶。

### 待確認

- 排程只產生待確認項目，不會自動入帳。
- 可修改金額、帳戶、類別/項目與備註後確認入帳。
- 可略過單筆，或批次確認仍然有效的項目。
- 帳戶或類別/項目封存、金額未填時，列表會顯示原因。

### 系統設定

「系統設定」包含：

- 一般設定：預設帳戶、預設流向、交易列表每頁筆數、餘額盤點提醒。
- 資料路徑：設定記帳資料路徑與備份路徑，可選「切換到既有資料」或「搬移目前資料」。
- 備份與還原：列出備份、驗證備份、還原備份、選擇外部備份資料夾、匯出 CSV。
- 重製與還原：重製目前記帳資料，回到乾淨預設資料；不刪除備份資料夾。

備份只會在使用者手動按「建立完整備份」時建立。還原與重製前的保護備份必須由使用者勾選。

## 驗證

```powershell
python -m ruff check --no-cache .
python -m mypy --no-incremental src
python -m pytest -q
```

200,000 筆效能回歸：

```powershell
$env:TAGCOR_RUN_PERFORMANCE = "1"
python -m pytest -q tests\performance\test_large_ledger.py
```

## 文件入口

完整文件請從 [docs/index.md](docs/index.md) 開始閱讀。歷史 Phase 0–2 文件保留於 `docs/archive/phase-0-2/`，僅供追溯，不再作為目前規格來源。
