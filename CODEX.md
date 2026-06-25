# CODEX Project Context

開始修改前依序閱讀：

1. `docs/index.md`
2. `docs/requirements/REQ-0001-stable-core.md`
3. `docs/requirements/REQ-0002-phase-1-2.md`
4. `docs/architecture/overview.md`
5. `docs/architecture/data-model.md`
6. `docs/architecture/ui-workflows.md`
7. `docs/roadmap.md`
8. `docs/changelog.md`

## 產品定位

TagCor Ledger 是 Windows-first、本機個人記帳工具。產品重點是快速輸入、清楚帳戶餘額、可搜尋交易、可靠備份與資料自主，不是企業會計或雲端多人協作系統。

## 架構規則

- `domain/` 不依賴 Qt、SQLite 或檔案系統。
- `application/` 定義使用者操作流程並回傳 `Result`。
- `infrastructure/` 負責 SQLite migration、repository、排程持久化、備份與匯出。
- `ui/` 僅透過 controller/use case 操作資料，不直接執行 SQL。
- SQLite `data/ledger.sqlite3` 是唯一帳務真實來源。
- CSV 僅作為匯出格式；執行期不得重新加入 CSV/JSON store 或 legacy importer。
- 所有帳務寫入與 audit event 必須在同一資料庫交易內完成。

## 資料規則

- 金額使用 `Money(amount_minor: int, currency: str)`，禁止 float。
- 首輪只允許 TWD；跨幣別操作應明確拒絕。
- 支出 posting 為負、收入 posting 為正。
- 轉帳必須產生同額一負一正 posting，總和為零。
- 作廢交易保留資料並從餘額與預設查詢排除。
- 分類為兩層；schema 可支援多筆 allocation，但首輪 UI 只建立一筆。
- 大量交易查詢必須使用索引與 keyset pagination，不可讀取全表後在 Python 排序。

## UI 與文字

- 使用 PySide6。
- 使用者可見文字採繁體中文。
- 「對象／商家」與「備註」是不同欄位。
- 日期顯示格式為 `yyyy/MM/dd HH:mm`，儲存為含 timezone offset 的 ISO 8601。
- 驗證錯誤優先使用行內提示；詳細例外只放在 Result details 或診斷紀錄。

## Migration 與資料安全

- 所有 schema 變更必須加入 ordered migration registry，禁止直接改既有版本。
- migration 必須可重跑，且不得重複建立欄位或資料。
- 0.1.x CSV/JSON 舊資料須先使用 0.2.0 轉成 SQLite；目前 runtime 不負責自動匯入。
- 還原前驗證 SHA-256 與 `PRAGMA integrity_check`，並先備份目前資料庫。
- 排程只產生 snapshot 待確認項目，不得自動入帳。
- 每次漏期生成上限 366 期；`next_due_date` 必須指向下一個尚未生成日期。

## 驗證基準

```powershell
python -m ruff check --no-cache .
python -m mypy --no-incremental src
python -m pytest -q
```

新增資料模型、migration 或 UI 流程時，同步更新 requirements、architecture、roadmap、changelog 與相關測試。
