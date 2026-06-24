# TagCor Ledger 文件入口

本目錄是專案需求、架構、決策、實作進度與維護資訊的單一入口。

## 使用者文件

- [環境設定](environment.md)
- [發布與手動驗收](release_checklist.md)
- [改動歷史](changelog.md)
- [根目錄 README](../README.md)

## 維護者文件

- [穩固核心版需求](requirements/REQ-0001-stable-core.md)
- [架構總覽](architecture/overview.md)
- [資料模型](architecture/data-model.md)
- [儲存配置](architecture/storage-layout.md)
- [UI 操作流程](architecture/ui-workflows.md)
- [SQLite 決策](decisions/ADR-0002-sqlite-canonical-store.md)
- [PySide6 決策](decisions/ADR-0003-pyside6.md)
- [Roadmap](roadmap.md)
- [維護者筆記](maintainer_notes.md)
- [Codex 上下文](../CODEX.md)

## 歷史文件

Phase 0–2 的原始計劃、CSV 規格、模組規劃與舊 README/CODEX 保存在 `archive/phase-0-2/`，僅供追溯，不再作為現行規格。

## 文件放置規則

- 新需求放在 `requirements/`。
- 長期架構與資料規格放在 `architecture/`。
- 重要取捨放在 `decisions/ADR-*.md`。
- 使用者可理解的改動記錄在 `changelog.md`。
- 已被取代但仍需追溯的文件移至 `archive/`。
