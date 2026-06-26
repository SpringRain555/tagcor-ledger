# 改動歷史

## Unreleased — 0.5.0

- Schema v4 新增 `balance_snapshots`，支援單一帳戶多次餘額盤點。
- 新增餘額盤點差額計算：上一筆盤點或期初餘額加期間 posting，對比本次實際金額。
- 新增餘額盤點頁，可新增、更新、作廢、查看差額期間交易與匯出 CSV。
- 設定新增啟動後每日盤點提醒開關。
- 修正 Windows/Conda 環境的 PySide6 安裝策略：PySide6 由 Conda 管理，避免 pip 覆蓋 Qt DLL 造成 `QtWidgets` 載入失敗。
- README、requirements、architecture、Roadmap 與 release checklist 加入 Phase 3 說明。

## 0.4.0 — Phase 1–2

- Schema v2 新增轉帳替換關聯，轉帳編輯改為原子建立新交易並作廢舊交易。
- 交易列表新增日期、帳戶、分類、狀態組合篩選及雙向 keyset pagination。
- 新增帳戶與分類恢復、預設帳戶／流向、頁面筆數與啟動備份設定。
- 備份頁新增列舉、驗證、外部 manifest 資料夾與還原前自動備份。
- Schema v3 新增交易模板、週期排程與待確認 occurrence。
- 新增複製交易、payee 自動完成、366 期漏期生成及待確認處理。
- 完全移除 PyQt6、TagPath、CSV/JSON runtime、legacy importer 與舊測試。
- README、CODEX、需求、架構、Roadmap、Changelog 與 release checklist 同步更新。

## 0.2.0 — 穩固核心版

- SQLite 取代年度 CSV 成為 canonical store。
- 新增帳戶 posting、兩層分類、payee、audit 與 FTS5。
- 新增收入、支出、同幣別轉帳、修改、作廢及分頁搜尋。
- 新增交易編輯對話框、帳戶與分類重新命名／封存。
- 新增 legacy CSV/JSON 備份與冪等 migration。
- UI 改用 PySide6，加入側邊導覽、繁中快速記帳與管理頁面。
- 新增 SQLite 一致性備份、checksum manifest 與 CSV 匯出。
- 文件改為 index、requirements、architecture、ADR、roadmap、changelog 結構。

## 0.1.0 — Phase 0–2

- 建立 Python/PyQt6 專案骨架與 Windows 使用者資料目錄。
- 建立 CSV/JSON validator、atomic writer、audit log 與 manifest。
- 完成四層標籤快速新增交易與最近交易原型。
