<#
    template: tools/Sync-AgentDocs.ps1 v2

.SYNOPSIS
    用 CLAUDE.md 的本文重新產生 AGENTS.md，只保留各自可以不同的兩段。

.DESCRIPTION
    兩份 agent 檔是平級的全文（CONVENTIONS §9），內容必須逐字相同 —— 差異只能在
    兩對標記之間：

        <!-- agent-doc:sync-notice -->  … <!-- /agent-doc:sync-notice -->   標題與互指聲明
        <!-- agent-doc:tool-specific --> … <!-- /agent-doc:tool-specific --> 工具專屬段落（可有可無）

    治理層的 `agent-doc-content-drift` 檢查會剝掉這兩對標記再比 hash。
    **那條檢查是 opt-in 的**：沒有 sync-notice 標記它根本不會啟動，所以標記本身不能弄丟。

    做法刻意是「以 CLAUDE.md 為來源」而不是「另外放一份本文」：多一份本文就多一個
    會漂的東西，而且那一份沒有任何工具會自動載入它，所以沒有人會發現它舊了。
    改規則一律改 CLAUDE.md，然後跑這一支；直接改 AGENTS.md 會在下一次同步時被蓋掉。

    這份是逐字複製型範本（CONVENTIONS §14）：專案照抄、不改。要改就回
    `_meta\templates\tools\Sync-AgentDocs.ps1` 改，版本號 +1，各專案由 `template-outdated` 提醒跟上。
    來源是 cyclosa 的 `tools\Sync-AgentDocs.ps1`（2026-09-06），加上 tool-specific 那一對的處理。

.PARAMETER Check
    只比對、不寫檔。不一致時 exit 1 —— 給 tools\Verify.ps1 用。

.EXAMPLE
    .\tools\Sync-AgentDocs.ps1
    .\tools\Sync-AgentDocs.ps1 -Check
#>
[CmdletBinding()]
param(
    [switch]$Check
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$claudePath = Join-Path $root 'CLAUDE.md'
$agentsPath = Join-Path $root 'AGENTS.md'
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Get-Block {
    # 取出一對標記（含標記本身）；沒有那一對回 $null，只有一半就丟。
    param([string]$Text, [string]$Tag, [string]$Path)
    $open = "<!-- agent-doc:$Tag -->"; $close = "<!-- /agent-doc:$Tag -->"
    $s = $Text.IndexOf($open); $e = $Text.IndexOf($close)
    if ($s -lt 0 -and $e -lt 0) { return $null }
    if ($s -lt 0 -or $e -lt 0) { throw "$Path 的 $Tag 標記只有一半（開 $s／關 $e）" }
    if ($e -lt $s) { throw "$Path 的 $Tag 標記順序反了" }
    [pscustomobject]@{ Start = $s; Length = ($e - $s + $close.Length); Text = $Text.Substring($s, $e - $s + $close.Length) }
}

# **一律用 ReadAllText 而不是 Get-Content -Raw。**
# PS 5.1 的 Get-Content 預設用系統 ANSI codepage（這台機器是 Big5），UTF-8 的中文會被讀壞。
$claude = [System.IO.File]::ReadAllText($claudePath, $utf8)
$agents = [System.IO.File]::ReadAllText($agentsPath, $utf8)

$cNotice = Get-Block $claude 'sync-notice' $claudePath
$aNotice = Get-Block $agents 'sync-notice' $agentsPath
if (-not $cNotice -or -not $aNotice) {
    throw "兩份都要有 <!-- agent-doc:sync-notice --> … <!-- /agent-doc:sync-notice --> 這對標記。少了它，agent-doc-content-drift 這條檢查對這個專案是關的。"
}
if ($cNotice.Start -ne 0 -or $aNotice.Start -ne 0) {
    throw 'sync-notice 標記必須在檔案最開頭（第一個字元）—— 它前面的東西沒有地方可以放。'
}

# 本文 ＝ sync-notice 之後的一切（取自 CLAUDE.md）
$body = $claude.Substring($cNotice.Length)

# tool-specific：CLAUDE.md 本文裡那一段換成 AGENTS.md 自己的那一段。
# 兩份要嘛都有、要嘛都沒有 —— 只有一份有，代表結構已經分岔，不能安靜地帶過。
$cTool = Get-Block $body 'tool-specific' $claudePath
$aTool = Get-Block $agents 'tool-specific' $agentsPath
if (($null -ne $cTool) -ne ($null -ne $aTool)) {
    throw '只有一份有 <!-- agent-doc:tool-specific --> 區塊 —— 兩份要同時有或同時沒有（CONVENTIONS §9）。'
}
if ($cTool) {
    $body = $body.Substring(0, $cTool.Start) + $aTool.Text + $body.Substring($cTool.Start + $cTool.Length)
}

$expected = $aNotice.Text + $body

if ($agents -ceq $expected) {
    Write-Host '  OK    兩份 agent 檔的本文逐字相同' -ForegroundColor Green
    exit 0
}

if ($Check) {
    Write-Host '  失敗  AGENTS.md 的本文與 CLAUDE.md 不同' -ForegroundColor Red
    Write-Host '        跑 .\tools\Sync-AgentDocs.ps1 重新產生' -ForegroundColor Yellow
    exit 1
}

# **寫檔一律 UTF-8 無 BOM**（CONVENTIONS §8：.md 不要 BOM、.ps1 才要）
[System.IO.File]::WriteAllText($agentsPath, $expected, $utf8)
Write-Host '  更新  AGENTS.md（本文取自 CLAUDE.md，互指聲明與工具專屬段落保留原本的）' -ForegroundColor Cyan

# v2：寫檔路徑也要明講離開碼。沒有 exit 0 的話，呼叫端拿到的是上一個原生指令的離開碼，
# 而一支「成功但離開碼不確定」的腳本遲早會被寫成閘門。
exit 0
