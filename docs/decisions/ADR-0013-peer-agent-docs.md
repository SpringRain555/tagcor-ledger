# ADR-0013 AGENTS.md 與 CLAUDE.md 是平級的兩份完整規則

## 狀態

已接受（2026-08-30）。取代 [ADR-0008](ADR-0008-agents-md-canonical.md)。

## 決策

`AGENTS.md` 與 `CLAUDE.md` 各自是**完整**的 agent 規則，地位平等。
兩份開頭都帶同一段同步聲明：改任何一份就要同步改另一份。

唯一該有的差異是**工具專屬**的段落（例如 `.claude/settings.json` 的 deny 行為）。

## 理由

ADR-0008 的前提是「`CLAUDE.md` 只留指向 `AGENTS.md` 的一行就夠了」。
**那個前提是錯的：Claude Code 不會自動載入 `AGENTS.md`。**

實測 Claude Code 2.1.116：自動載入的只有 `CLAUDE.md`；Codex 自動載入的只有 `AGENTS.md`。
所以指路檔的實際效果是「Claude Code 讀到一行『規則在隔壁』，然後**不一定會去讀**」——
這個專案的硬規則（`<私人資料樹>\` 邊界、conda 直譯器要用完整路徑、
`Verify.ps1` 是唯一驗證入口）本來就是「猜錯會出事」的那一類，不能靠 agent 自己想去翻。

ADR-0008 擔心的漂移是真的，但**解法不是少寫一份，是讓漂移被看見**。

## 後果

- `D:\Projects` 全域一致：31 個專案 ＋ 根目錄各有兩份平級的 agent 檔。
- 漂移由機器盯著：registry 的 `agentDocs` 欄位記錄實際存在哪幾份，
  驗證器的 `agent-doc-drift`（info）比對兩份**最後被改的 commit**，不同就報。
  規範在 `D:\Projects\_meta\CONVENTIONS.md`。
- 只改工具專屬段落時兩份本來就會不同步 —— 那是良性例外，所以這條是 info 級、不擋 exit code。
- `docs/archive/phase-0-2/CODEX-old.md` 仍然是歷史檔案，**保持原狀不動**。
