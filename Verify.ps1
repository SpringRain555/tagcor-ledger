#Requires -Version 5.1
<#
.SYNOPSIS
    TagCor Ledger 的本機驗證閘門。

.DESCRIPTION
    依序跑：路徑漂移檢查 -> ruff -> mypy --strict -> pytest。
    任何一項失敗都會讓整支腳本以非零 exit code 結束，並在最後列出所有失敗項。

    這支腳本刻意「只報矛盾、不自動修」。漂移檢查發現的問題要由人決定怎麼處理。

.PARAMETER Ui
    加跑 tests\ui（自動設定 QT_QPA_PLATFORM=offscreen）。

.PARAMETER Performance
    加跑 20 萬筆的效能測試（自動設定 TAGCOR_RUN_PERFORMANCE=1）。

.PARAMETER SkipDrift
    略過路徑漂移檢查。只在還沒設定過資料路徑時使用。

.EXAMPLE
    .\Verify.ps1
    .\Verify.ps1 -Ui -Performance
#>
[CmdletBinding()]
param(
    [switch]$Ui,
    [switch]$Performance,
    [switch]$SkipDrift
)

$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$Python = '<conda-root>\envs\tagcor-ledger\python.exe'

$script:Failures = New-Object System.Collections.ArrayList

function Write-Section {
    param([string]$Name)
    Write-Host ''
    Write-Host "=== $Name" -ForegroundColor Cyan
}

function Add-Failure {
    param([string]$Message)
    [void]$script:Failures.Add($Message)
    Write-Host "  FAIL  $Message" -ForegroundColor Red
}

function Write-Pass {
    param([string]$Message)
    Write-Host "  OK    $Message" -ForegroundColor Green
}

function Write-Note {
    param([string]$Message)
    Write-Host "        $Message" -ForegroundColor DarkGray
}

function ConvertTo-RulePath {
    param([string]$Path)
    return ($Path -replace '\\', '/').TrimEnd('/')
}

function Test-PathDrift {
    Write-Section '路徑漂移檢查'

    $pointer = Join-Path $env:LOCALAPPDATA 'TagCor\TagCorLedger\system_paths.json'
    if (-not (Test-Path -LiteralPath $pointer)) {
        Add-Failure "找不到指標檔 $pointer —— 先在 App 的『系統設定 → 記帳資料路徑』設定一次。"
        return
    }

    try {
        $pointerData = Get-Content -LiteralPath $pointer -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        Add-Failure "指標檔無法解析為 JSON：$pointer"
        return
    }

    $dataRoot = $pointerData.data_root
    if ([string]::IsNullOrWhiteSpace($dataRoot)) {
        Add-Failure "指標檔沒有 data_root 欄位（舊格式）。在 App 重新儲存一次路徑設定即可補上。"
        return
    }
    Write-Pass "資料根目錄 $dataRoot"

    if (-not (Test-Path -LiteralPath $dataRoot)) {
        Add-Failure "data_root 指向的資料夾不存在：$dataRoot"
    }

    $claudeSettings = Join-Path $ProjectRoot '.claude\settings.json'
    if (-not (Test-Path -LiteralPath $claudeSettings)) {
        Add-Failure "找不到 $claudeSettings"
        return
    }

    try {
        $config = Get-Content -LiteralPath $claudeSettings -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        Add-Failure "無法解析 .claude\settings.json —— JSON 壞掉時整份設定會被靜默忽略。"
        return
    }

    $allow = @($config.permissions.allow)
    $deny = @($config.permissions.deny)
    $expected = "Read($(ConvertTo-RulePath $dataRoot)/**)"

    if ($allow -contains $expected) {
        Write-Pass "allow 清單與 data_root 一致"
    } else {
        Add-Failure "allow 清單沒有對應 data_root 的規則。"
        Write-Note "應該要有：$expected"
        Write-Note "目前有  ：$($allow -join ', ')"
    }

    # data_root 之外、<私人資料樹> 底下的任何資料夾都應該被 deny 列舉到。
    # 只報告，不推論該怎麼處理。
    $financeDir = Split-Path -Parent $dataRoot
    $personalDir = Split-Path -Parent $financeDir
    $onAllowedChain = @($dataRoot, $financeDir, $personalDir)

    $unlisted = New-Object System.Collections.ArrayList
    foreach ($scope in @($personalDir, $financeDir)) {
        if (-not (Test-Path -LiteralPath $scope)) { continue }
        foreach ($child in (Get-ChildItem -LiteralPath $scope -Directory -Force -ErrorAction SilentlyContinue)) {
            if ($onAllowedChain -contains $child.FullName) { continue }
            $rule = ConvertTo-RulePath $child.FullName
            $covered = $false
            foreach ($entry in $deny) {
                if ($entry -like "*($rule*") { $covered = $true; break }
            }
            if (-not $covered) { [void]$unlisted.Add($child.FullName) }
        }
    }

    if ($unlisted.Count -eq 0) {
        Write-Pass "<私人資料樹> 底下沒有未列入 deny 的資料夾"
    } else {
        Add-Failure "以下資料夾在保護範圍內但沒有 deny 規則，agent 可能讀得到："
        foreach ($item in $unlisted) { Write-Note $item }
        Write-Note '把它們加進 .claude\settings.json 的 permissions.deny。'
    }
}

function Invoke-Step {
    param(
        [string]$Name,
        [string[]]$Arguments
    )
    Write-Section $Name
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        Add-Failure "$Name 失敗（exit code $LASTEXITCODE）"
    } else {
        Write-Pass $Name
    }
}

Push-Location $ProjectRoot
try {
    if (-not (Test-Path -LiteralPath $Python)) {
        Write-Host "找不到專案的 conda 直譯器：$Python" -ForegroundColor Red
        Write-Host '請先跑 conda env create -f environment.yaml' -ForegroundColor Red
        exit 1
    }

    if (-not $SkipDrift) { Test-PathDrift }

    Invoke-Step -Name 'ruff' -Arguments @('-m', 'ruff', 'check', '--no-cache', '.')
    Invoke-Step -Name 'mypy --strict' -Arguments @('-m', 'mypy', '--no-incremental', 'src')

    $env:QT_QPA_PLATFORM = 'offscreen'
    if ($Performance) { $env:TAGCOR_RUN_PERFORMANCE = '1' }

    if ($Ui -or $Performance) {
        Invoke-Step -Name 'pytest（含 ui/效能）' -Arguments @('-m', 'pytest', '-q')
    } else {
        Invoke-Step -Name 'pytest' -Arguments @('-m', 'pytest', '-q')
    }

    Write-Host ''
    if ($script:Failures.Count -eq 0) {
        Write-Host '全部通過。' -ForegroundColor Green
        exit 0
    }

    Write-Host "有 $($script:Failures.Count) 項失敗：" -ForegroundColor Red
    foreach ($failure in $script:Failures) { Write-Host "  - $failure" -ForegroundColor Red }
    exit 1
} finally {
    Pop-Location
}
