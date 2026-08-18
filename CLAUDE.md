# CLAUDE — TagCor Ledger

**規則的正本是 [`AGENTS.md`](AGENTS.md)，先讀那一份。** 這裡只放不屬於通用 agent 規則的 Claude Code 專屬事項。

## 兩件動手前一定要先確認的事

1. **資料在專案外**：`<資料根目錄>\`。`<私人資料樹>\` 底下**其他**資料夾不可讀也不可寫，`.claude\settings.json` 有對應的 deny 規則。完整規則見 `AGENTS.md` 的「資料位置與讀取邊界」。
2. **用專案的 conda 直譯器**，不要用 PATH 上的 python：
   `<conda-root>\envs\tagcor-ledger\python.exe`

## deny 規則擋不住 shell

`.claude\settings.json` 的 deny 攔得住 Read／Glob／Grep／Edit／Write，**攔不住 Bash 與 PowerShell** —— `Get-Content`、`cat`、`Select-String` 都能讀檔。用 shell 時要自己遵守 `AGENTS.md` 的邊界規則。
