# 改動歷史

## Unreleased — 0.2.0

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
