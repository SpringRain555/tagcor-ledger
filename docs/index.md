# TagCor Ledger 文件索引

目前規格以本索引列出的文件為準；`docs/archive/phase-0-2/` 僅保留歷史紀錄，**不是規格**。

## 兩條閱讀路線

**人類第一次接觸**：README → 這份索引 → [go-live runbook](operations/go-live-2026-09.md) → 開始用。
規格文件在需要時再查。

**LLM 或新的維護者要動程式**，照這個順序，**不要跳**：

1. [`AGENTS.md`](../AGENTS.md) —— 硬規則與邊界。**沒讀這份就動手一定會踩到東西**
2. [狀態機](architecture/state-machines.md) —— 有哪些狀態、哪些轉移合法、哪裡刻意不做推論
3. [資料模型](architecture/data-model.md) —— 表與欄位
4. [錯誤碼目錄](architecture/error-codes.md) —— 每個錯誤的成因與使用者該怎麼做
5. [用詞對照表](architecture/glossary.md) —— 什麼該叫什麼，以及**不該叫什麼**
6. [失敗紀錄](lessons.md) —— 別人踩過的坑。**動 migration 或路徑之前必讀**
7. 才是相關的 REQ 與 ADR

## 每份文件的權威範圍

一件事只在一個地方是權威的。其他地方提到它時只能是摘要與連結，不能是第二份規格。

| 文件 | 對什麼有權威 |
|---|---|
| [`AGENTS.md`](../AGENTS.md) | agent 規則、架構邊界、硬性禁令、環境與編碼 |
| [`README.md`](../README.md) | 使用者能做什麼、怎麼安裝與啟動 |
| [狀態機](architecture/state-machines.md) | 所有狀態值與合法轉移 |
| [資料模型](architecture/data-model.md) | 表、欄位、索引、migration 版本 |
| [儲存配置](architecture/storage-layout.md) | 檔案位置、`data_root` 約束、備份格式 |
| [錯誤碼目錄](architecture/error-codes.md) | 每個錯誤碼的成因與處理 |
| [用詞對照表](architecture/glossary.md) | 中文用詞與程式識別字的對應 |
| [UI 流程](architecture/ui-workflows.md) | 側邊欄順序與各頁的操作流程 |
| [架構總覽](architecture/overview.md) | 分層與資料流 |
| REQ-XXXX | 該功能的需求、邊界與驗收條件 |
| ADR-XXXX | 該決定的理由與後果。**決定改了要新增 ADR，不要改舊的** |
| [失敗紀錄](lessons.md) | 踩過的坑。append-only |
| [研究](research/market-scan.md) | 市面產品的判讀，**附抓取日期** |
| [維護者筆記](maintainer_notes.md) | **對什麼都沒有權威。** 它是「這件事的規則寫在哪」的查詢表 |

## 快速入口

- [README](../README.md)｜[AGENTS](../AGENTS.md)（agent 規則正本，`CLAUDE.md` 指向它）
- [九月上線 runbook](operations/go-live-2026-09.md)
- [Roadmap](roadmap.md)｜[Changelog](changelog.md)｜[Release checklist](release_checklist.md)
- [失敗紀錄](lessons.md) —— 踩過的坑與「不要再做」清單
- [維護者筆記](maintainer_notes.md)（規則在哪的查詢表）｜[環境](environment.md)

## Requirements

| | 狀態 |
|---|---|
| [REQ-0001 穩固核心](requirements/REQ-0001-stable-core.md) | 已實作 |
| [REQ-0002 Phase 1–2](requirements/REQ-0002-phase-1-2.md) | 已實作 |
| [REQ-0003 餘額盤點](requirements/REQ-0003-balance-snapshots.md) | 已實作 |
| [REQ-0004 Phase 4 設定與路徑](requirements/REQ-0004-phase-4-settings-paths-terms.md) | 已實作 |
| [REQ-0005 Phase 4.1 深色 UI](requirements/REQ-0005-phase-4-1-dark-ui-docs.md) | 已實作 |
| [REQ-0006 資料與程式分離](requirements/REQ-0006-data-program-separation.md) | 已實作 |
| [REQ-0007 郵局定存](requirements/REQ-0007-time-deposits.md) | 已實作（schema v6–v7） |
| [REQ-0008 法規參考庫](requirements/REQ-0008-reference-db.md) | 已實作 |
| [REQ-0009 例外處理與可觀測性](requirements/REQ-0009-observability.md) | 已實作 |
| [REQ-0010 對帳缺口](requirements/REQ-0010-reconciliation-gap.md) | **刻意尚未實作** |

## Decisions

- [ADR-0001 文件制度與歷史保存](decisions/ADR-0001-documentation-history.md)
- [ADR-0002 SQLite 作為 canonical store](decisions/ADR-0002-sqlite-canonical-store.md)
- [ADR-0003 使用 PySide6](decisions/ADR-0003-pyside6.md)
- [ADR-0004 資料與程式位置分離](decisions/ADR-0004-data-program-separation.md)
- [ADR-0005 法規庫唯讀且離線](decisions/ADR-0005-reference-db-offline.md)
- [ADR-0006 一律手動輸入](decisions/ADR-0006-manual-entry-only.md)
- [ADR-0007 定存建模](decisions/ADR-0007-time-deposit-modelling.md)
- [ADR-0008 AGENTS.md 是唯一正本](decisions/ADR-0008-agents-md-canonical.md)
- [ADR-0009 UI 維持 PySide6](decisions/ADR-0009-keep-pyside6.md)

## Architecture

- [總覽](architecture/overview.md)｜[資料模型](architecture/data-model.md)｜[狀態機](architecture/state-machines.md)
- [儲存配置](architecture/storage-layout.md)｜[UI 流程](architecture/ui-workflows.md)
- [錯誤碼目錄](architecture/error-codes.md)｜[用詞對照表](architecture/glossary.md)

## Research

證據，不是規格。每個判讀都附抓取日期，**過期的結論要重查而不是沿用**。

- [市面產品對照](research/market-scan.md)：借什麼、不借什麼、為什麼。
- [問題拆解與來源地圖](research/questions.md)｜[查詢紀錄](research/query-log.md)｜[未解決清單](research/open-questions.md)
