# ADR-0008 AGENTS.md 是 agent 規則的唯一正本

## 狀態

已接受（2026-08-18）。取代 `CODEX.md`，該檔已刪除。

## 決策

`AGENTS.md` 是給所有 agent（Codex、Claude Code 等）的唯一正本。
`CLAUDE.md` 只留指向它的一行，加上 Claude Code 專屬事項。

## 理由

同一套規則寫成三份一定會漂移，而且漂移的時候沒有人知道哪一份是對的。
`AGENTS.md` 是跨工具的通用慣例，Codex 現在也讀這一份。

## 後果

- 動任何規則只改 `AGENTS.md`。
- 工作區的 `D:\Projects\CLAUDE.md` 已同步更新（原本寫 tagcor-ledger 有 `CODEX.md`）。
- `docs/index.md`、`maintainer_notes.md`、`release_checklist.md` 裡的 CODEX 引用都已改掉。
- 舊的 `docs/archive/phase-0-2/CODEX-old.md` 是歷史檔案，**保持原狀不動**。
