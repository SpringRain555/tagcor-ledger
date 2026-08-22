# CODEX.md

> **歷史文件，不是規格。** 這是 SQLite 穩固核心版之前的 CSV／PyQt6 時代規劃，
> 已被 [`docs/index.md`](../../index.md) 指向的現行文件取代。
> grep 撈到這裡的話，你要的答案在別的地方。

## 專案定位

TagCor Ledger 是一個以四層標籤為核心的本機桌面記帳工具。第一階段目標是用 Python + PyQt6 建立鍵盤優先的快速記帳流程，資料先以 CSV + JSON 保存，並透過清楚的 repository 介面保留未來切換 SQLite 的可能。

目前 repo 仍在規劃階段，主要依據文件為：

- `docs/計劃書.md`：產品範圍、架構、資料模型、里程碑與驗收。
- `docs/資料格式規格.md`：CSV/JSON schema、長期保存規則、manifest、backup、audit 與 migration。
- `docs/模組化與階段實作.md`：模組邊界、依賴方向、打包保留空間與階段性實作內容。
- `README.md`：簡介與入口說明。

## 開發原則

1. 先遵守 `docs/計劃書.md` 的分層設計，不把 UI、資料存取與業務規則混在一起。
2. 所有資料修改必須經過 Application Use Case。
3. UI 不得直接讀寫 CSV/JSON。
4. 金額必須使用 `Decimal`，禁止使用 float 表示帳務金額。
5. 所有檔案寫入必須使用 atomic writer。
6. 所有使用者資料操作必須寫入 audit log。
7. 長時間 IO 或批次操作必須背景化，避免 PyQt UI 凍結。
8. 新增或修改 schema 時，必須同步更新 migration、範例資料與測試。

## 建議架構

```text
src/tagcor_ledger/
├── __main__.py
├── main.py
├── app/
├── domain/
├── application/
├── infrastructure/
├── ui/
└── resources/
```

責任分工：

- `app/`：啟動流程、dependency wiring、使用者資料目錄、資源讀取。
- `domain/`：純業務模型與規則，例如 `Transaction`、`Money`、`TagPath`。
- `application/`：使用者操作流程，例如新增交易、管理標籤、備份還原。
- `infrastructure/`：CSV/JSON、檔案鎖、原子寫入、備份、logging、manifest、migration。
- `ui/`：PyQt6 視窗、表單、對話框、樣式與焦點行為。
- `resources/`：QSS、icon 等打包時需要的靜態資源。

MVP 階段採中等顆粒模組化；不要為每個小 use case 或每個小 widget 各自建立檔案。詳細規劃以 `docs/模組化與階段實作.md` 為準。

## 資料模型重點

- Ledger 內部儲存 Tag ID 與 tag name snapshot；Tag ID 用於關聯，snapshot 用於保存交易當下語意。
- Tag 改名只更新 `tags.json`，不重寫 ledger snapshot。
- 只有 tag 合併、拆分或批次轉換才需要 dry-run、備份、背景任務與還原策略。
- `default_amount` 等 Decimal 值在 JSON 中以字串保存。
- 所有 schema 檔案都要具備 `schema_version`。
- 已使用 tag 與交易不得實體刪除，使用 `archived` / `voided` 狀態。

## Use Case Result

Application Use Case 應統一回傳類似結構：

```text
success: bool
error_code: string | null
message: string
details: dict
correlation_id: string
```

UI 顯示 `message` 與 `correlation_id`；詳細例外寫入 `error.log`。

## 測試要求

新增功能時至少考慮：

- Domain 單元測試：金額、TagPath、交易驗證。
- Application 單元測試：成功、驗證失敗、repository 例外。
- Infrastructure 整合測試：CSV/JSON 讀寫、atomic writer、backup/restore。
- UI 關鍵手動驗收：Tab 順序、快捷鍵、模板套用、錯誤提示。

## 文件維護

文件放置原則：

- `README.md` 留在根目錄，作為專案入口。
- `CODEX.md` 留在根目錄，讓 Codex 優先讀取。
- 企劃、架構、規格、測試計畫等長文件集中放在 `docs/`。

當變更以下內容時，請同步更新 `docs/計劃書.md`：

- 分層架構。
- 資料 schema。
- 使用者流程。
- 里程碑與驗收條件。
- 重大技術決策。

當變更以下內容時，請同步更新 `docs/模組化與階段實作.md`：

- 模組邊界與依賴方向。
- 階段性實作內容。
- 打包入口、資源讀取、使用者資料目錄策略。
- 拆分時機與模組顆粒。

當變更以下內容時，請同步更新 `docs/資料格式規格.md`：

- CSV/JSON 欄位。
- schema version。
- ID、時間、金額、狀態 enum 規則。
- backup、manifest、audit、migration 格式。

當開始新增實作後，也請更新 `README.md`，補上安裝、啟動、測試與資料位置說明。
