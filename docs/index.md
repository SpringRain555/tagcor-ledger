# TagCor Ledger 文件索引

目前規格以本索引列出的文件為準；`docs/archive/phase-0-2/` 僅保留歷史紀錄。

## 快速入口

- [README](../README.md)：安裝、啟動與使用者操作方式。
- [AGENTS](../AGENTS.md)：給維護者與所有 agent 的專案規則（唯一正本）。`CLAUDE.md` 只是指向它。
- [Roadmap](roadmap.md)：已完成與後續 Phase。
- [Changelog](changelog.md)：階段性變更紀錄。
- [Release checklist](release_checklist.md)：發版前檢查。
- [Lessons](lessons.md)：**失敗紀錄（append-only）**。踩過的坑與明確的「不要再做」清單。

## Research

證據，不是規格。每個判讀都附抓取日期，**過期的結論要重查而不是沿用**。

- [市面產品對照](research/market-scan.md)：借什麼、不借什麼、為什麼。
- [問題拆解與來源地圖](research/questions.md)｜[查詢紀錄](research/query-log.md)｜[未解決清單](research/open-questions.md)

## Requirements

- [REQ-0001 Stable Core](requirements/REQ-0001-stable-core.md)
- [REQ-0002 Phase 1–2](requirements/REQ-0002-phase-1-2.md)
- [REQ-0003 Balance Snapshots](requirements/REQ-0003-balance-snapshots.md)
- [REQ-0004 Phase 4 Settings, Paths, Terms](requirements/REQ-0004-phase-4-settings-paths-terms.md)
- [REQ-0005 Phase 4.1 Dark UI and Docs](requirements/REQ-0005-phase-4-1-dark-ui-docs.md)

## Architecture

- [Overview](architecture/overview.md)
- [Data model](architecture/data-model.md)
- [Storage layout](architecture/storage-layout.md)
- [UI workflows](architecture/ui-workflows.md)

## Decisions

- [ADR-0001 Documentation history](decisions/ADR-0001-documentation-history.md)
- [ADR-0002 SQLite canonical store](decisions/ADR-0002-sqlite-canonical-store.md)
- [ADR-0003 PySide6](decisions/ADR-0003-pyside6.md)
