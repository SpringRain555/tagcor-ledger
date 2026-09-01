#Requires -Version 5.1
<#
.SYNOPSIS
    找出專案 conda 環境的 python.exe，不依賴 PATH，也不用 `conda activate`。

.DESCRIPTION
    `Launch.ps1` 與 `Verify.ps1` 都需要這件事，而且答案必須一致 —— 所以它只寫在
    這裡一份。兩邊各寫一份的話，改了一邊而沒改另一邊，症狀是「雙擊啟動得起來
    但驗證跑不了」（或反過來），而那種不一致很難聯想到根因。

    為什麼不用 `conda activate`：在沒有載入 PowerShell hook 的情境下（工具 shell
    以 -NonInteractive 啟動，不載入 profile.ps1），它會跑在子 process 裡改不到
    父層環境，**回報成功、退出碼 0、實際上什麼都沒換**。接著跑到的會是 PATH 上
    碰巧排在前面的別的直譯器 —— 那個多半沒有 PySide6，失敗訊息會指向完全無關
    的方向。

    查找順序：`$env:TAGCOR_PYTHON` → 常見的 conda 安裝位置 → 問 PATH 上的 conda
    自己的 base。找不到就回傳 $null，由呼叫端決定要停下來還是跳過。
#>
function Resolve-TagcorPython {
    [CmdletBinding()]
    param(
        [string]$EnvName = 'tagcor-ledger'
    )

    $candidates = New-Object System.Collections.Generic.List[string]

    # 明確指定的優先。conda 裝在非標準位置時，使用者設一次這個變數就好：
    #     setx TAGCOR_PYTHON "X:\path\to\envs\tagcor-ledger\python.exe"
    if ($env:TAGCOR_PYTHON) { $candidates.Add($env:TAGCOR_PYTHON) }

    $bases = @(
        "$env:USERPROFILE\miniconda3",
        "$env:USERPROFILE\anaconda3",
        "$env:LOCALAPPDATA\miniconda3",
        "$env:LOCALAPPDATA\anaconda3",
        "$env:ProgramData\miniconda3",
        "$env:ProgramData\anaconda3",
        'C:\miniconda3',
        'C:\anaconda3'
    )

    # 也問一次 PATH 上的 conda，涵蓋裝在非標準位置的情形。
    $conda = Get-Command conda -ErrorAction SilentlyContinue
    if ($conda) {
        try {
            $base = (& $conda.Source info --base 2>$null | Select-Object -First 1)
            if ($base) { $bases += $base.Trim() }
        } catch {
            # conda 壞掉不是這裡要處理的問題，繼續用固定候選路徑。
        }
    }

    foreach ($base in $bases) {
        if ($base) { $candidates.Add((Join-Path $base "envs\$EnvName\python.exe")) }
    }

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { return $candidate }
    }
    return $null
}
