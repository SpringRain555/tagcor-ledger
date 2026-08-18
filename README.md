# TagCor Ledger

TagCor Ledger 是 Windows-first、本機優先的個人記帳工具。核心資料使用 SQLite，介面使用 PySide6，目標是快速記錄收支、轉帳、餘額盤點與待確認週期項目，同時保持資料可備份、可還原、可長期維護。

目前版本：0.11.0（郵局定存、法規參考庫、例外處理與可觀測性）。

**帳務資料不在專案資料夾裡。** 程式在 `D:\Projects\tagcor-ledger`，資料在 `<資料根目錄>`，兩者分開，資料永遠不進版控。完整說明見 [Storage layout](docs/architecture/storage-layout.md)。

## 目前功能

- 快速記帳流程：流向 → 帳戶 → 類別 → 項目 → 時間 → 金額 → 備註。
- 收入、支出、同幣別 TWD 轉帳。
- 交易紀錄支援文字、日期、帳戶、類別與狀態篩選，使用 keyset pagination。
- 帳戶、類別與項目可新增、重新命名、封存、恢復、刪除未使用。
- 模板、週期排程、待確認項目與批次確認。
- 餘額盤點與未解釋差額追蹤；盤點不會直接入帳。
- 郵局定存：合約與每一期分開記錄，三種計息方式 × 四種到期轉存方式。
  到期與領息**只產生待確認項目**，由使用者確認才入帳，程式不會自己記帳。
- 法規參考：6 部法規、17 條精選條文的離線查閱庫，含白話摘要與條文原文。
  **App 不連網**，法規庫是離線產生的唯讀檔案。
- 啟動失敗、資料庫被鎖、磁碟不可用等狀況會顯示繁中說明並寫入日誌，不會無聲消失。
- 電子票證（悠遊卡／一卡通／iCash）只記儲值當下的支出，**不建卡片帳戶、不追蹤卡內餘額**。
- 記帳資料路徑與備份路徑可分開設定。
- 備份只在使用者手動按下「建立完整備份」時執行。
- 還原與重製前可勾選「先建立備份」，不再強制自動備份。
- 固定深色主題，採專業深藍、舒適密度與 Windows 本機字體 fallback。
- UTF-8 BOM CSV 匯出供交換與人工閱讀；SQLite 是唯一主資料庫。

## UI 主題

TagCor Ledger 固定採用深色主題，不提供亮色／暗色切換。設計方向是「專業深藍、舒適密度、本機字體優先」：

- 背景以深灰藍與墨藍為主，不使用純黑作主要內容背景。
- 主要操作使用藍色按鈕；刪除、作廢、重製、還原等高風險操作使用紅色危險按鈕。
- 分頁、下拉選單、表格、清單、狀態列與彈窗都使用一致深色樣式，避免文字與背景同色。
- 字體優先順序為 `Segoe UI Variable`、`Segoe UI`、`Microsoft JhengHei UI`、`Microsoft JhengHei`、`Noto Sans TC`、sans-serif；不額外打包字型檔。
- 側邊欄與一般清單分開樣式；備份清單不會被側邊欄樣式污染。

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

### 一鍵啟動（建議）

**雙擊專案根目錄的 `啟動 TagCor Ledger.cmd`。** 不用先開終端機、不用 `conda activate`。

它會自己找到 conda 環境的直譯器（絕對路徑）、清掉繼承來的 `VIRTUAL_ENV`／`PYTHONPATH`、
跑一次前置檢查確認套件與資料路徑可用，然後開視窗。出問題時會停在畫面上說明原因與修法，
不是一閃而過。

想在桌面放捷徑：

```powershell
.\Launch.ps1 -CreateShortcut
```

conda 裝在非標準位置時，設一次環境變數即可：

```powershell
setx TAGCOR_PYTHON "X:\path\to\envs\tagcor-ledger\python.exe"
```

### 從終端機啟動

```powershell
conda activate tagcor-ledger
python -m tagcor_ledger --gui
```

> **注意：終端機裡若已經啟動了別的專案的 venv，這個做法會失敗。**
> venv 的 `Scripts` 排在 PATH 最前面，`conda activate` 之後它仍然排在前面 ——
> 兩個環境的名字都會出現在提示字元上（`(.venv) (tagcor-ledger)`），但 `python` 解析到的
> 是 venv 那一個，症狀是 `No module named tagcor_ledger`。
> 用 `(Get-Command python).Source` 可以確認實際跑的是哪一個；先 `deactivate` 或改用一鍵啟動。

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

「操作設定」包含這些區塊：

- 帳戶：新增、重新命名、封存、恢復、刪除未使用。
- 類別：管理第一層類別。
- 項目：在類別底下管理第二層項目。
- 模板與週期排程：建立模板、建立週期排程、產生待確認項目。
- 定存：定存合約與每一期，含新增、修改、刪除，以及「產生到期與領息項目」。

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

系統設定裡還有「匯出診斷資訊」：版本、schema 版本、七個路徑、`integrity_check`、各表筆數
與最近 200 行日誌。**不含任何金額、備註或帳戶名稱**，所以可以直接交出去問人。

### 法規參考

離線查閱用的稅務與金融法規庫：主題篩選、中文全文搜尋、條文詳情（白話摘要、對這個帳本的意義、
條文原文），每一條都附來源網址、修正日期與抓取時間。

- **App 永遠不連網。** 抓取是 `tools/law_sync/` 的外掛工具，手動執行，見 [reference/README.md](reference/README.md)。
- 法規庫是產生物，**不進版控**。檔案不存在時記帳完全不受影響，該頁會說明怎麼建立。
- **不計算稅額、不做申報、不依法規自動調整任何帳務數字。** 這是查閱用的參考資料，
  不是稅務或法律意見，以主管機關公告為準。

## 驗證

```powershell
.\Verify.ps1                 # 路徑漂移檢查 + ruff + mypy --strict + pytest
.\Verify.ps1 -Ui             # 加跑 tests\ui（offscreen）
.\Verify.ps1 -Performance    # 加跑 200,000 筆效能回歸
```

## 文件入口

完整文件請從 [docs/index.md](docs/index.md) 開始閱讀。歷史 Phase 0–2 文件保留於 `docs/archive/phase-0-2/`，僅供追溯，不再作為目前規格來源。
