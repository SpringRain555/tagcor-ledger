<#
.SYNOPSIS
    把 docs 裡的 mermaid 區塊算成 SVG，並記下每一段原始碼的 SHA-256。

.DESCRIPTION
    **人手動跑，不進 Verify.ps1。** 第一次執行會讓 npx 下載 mermaid-cli 與它帶的
    Chromium（約數百 MB，需要網路）。App 的「永遠不連網」規則約束的是 `src/`；
    `tools/` 本來就是手動離線工具，`tools/law_sync/` 是同樣的形狀。

    產出的 SVG **會進版控** —— 否則沒裝 node 的人（含日後讀這份專案的 LLM）看不到圖。

    改了任何一段 mermaid 就要重跑，否則 tests/unit/test_diagrams_drift.py 會紅。
    那條測試只比對 SHA-256，**不需要 node**，所以 Verify.ps1 照樣跑得動。

.EXAMPLE
    .\tools\diagrams\Render-Diagrams.ps1
    .\tools\diagrams\Render-Diagrams.ps1 -Check   # 只檢查有沒有過期，不重算
#>
[CmdletBinding()]
param(
    [switch]$Check
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$docsDir = Join-Path $root 'docs\architecture'
$outDir = Join-Path $docsDir 'diagrams'
$manifestPath = Join-Path $outDir 'manifest.json'
$themePath = Join-Path $PSScriptRoot 'mermaid-config.json'

if (-not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir | Out-Null
}

function Get-Blocks {
    param([string]$Path)

    $lines = [System.IO.File]::ReadAllLines($Path)
    $blocks = @()
    $current = $null
    foreach ($line in $lines) {
        if ($null -eq $current) {
            if ($line.TrimEnd() -eq '```mermaid') { $current = @() }
            continue
        }
        if ($line.TrimEnd() -eq '```') {
            $blocks += , ($current -join "`n")
            $current = $null
            continue
        }
        $current += $line
    }
    if ($null -ne $current) {
        throw "$Path 裡有一個 ``````mermaid 區塊沒有收尾"
    }
    # **一定要標成 `[string[]]`，而且呼叫端要用 `@()` 包起來。**
    #
    # PowerShell 回傳陣列時會攤平，於是有兩個都會咬人的邊界：
    #   - 只有一張圖 → 攤成**字串**，`$blocks[0]` 變成它的第一個字元
    #     （「No diagram type detected ... for text: e」，erDiagram 的 e）
    #   - 一張圖都沒有 → 寫 `, $blocks` 的話會回傳「裝著一個空陣列的陣列」，
    #     於是沒有任何 mermaid 的文件（例如 error-codes.md）會被當成有一張空白圖
    #
    # 標型別 ＋ 呼叫端 `@()` 兩件事一起做，0 張與 1 張才都對。
    return [string[]]$blocks
}

function Get-Sha256 {
    param([string]$Text)

    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return -join ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') })
    }
    finally {
        $sha.Dispose()
    }
}

$entries = @()
$stale = @()
$existing = @{}
if (Test-Path $manifestPath) {
    $loaded = Get-Content $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($item in $loaded.diagrams) { $existing[$item.svg] = $item.sha256 }
}

foreach ($doc in (Get-ChildItem -Path $docsDir -Filter '*.md' | Sort-Object Name)) {
    $blocks = @(Get-Blocks -Path $doc.FullName)
    for ($i = 0; $i -lt $blocks.Count; $i++) {
        $source = $blocks[$i]
        $hash = Get-Sha256 -Text $source
        $name = '{0}-{1}.svg' -f $doc.BaseName, ($i + 1)
        $svgPath = Join-Path $outDir $name
        $entries += [ordered]@{
            document = $doc.Name
            index    = $i + 1
            svg      = $name
            sha256   = $hash
        }

        $upToDate = (Test-Path $svgPath) -and $existing.ContainsKey($name) -and ($existing[$name] -eq $hash)
        if ($Check) {
            if (-not $upToDate) { $stale += $name }
            continue
        }
        if ($upToDate) {
            Write-Host "  skip  $name（沒有變）"
            continue
        }

        $tmp = New-TemporaryFile
        $mmd = [System.IO.Path]::ChangeExtension($tmp.FullName, '.mmd')
        # mermaid-cli 讀的是 UTF-8；中文標籤沒有 BOM 也沒問題，有 BOM 反而會被當成內容。
        [System.IO.File]::WriteAllText($mmd, $source, (New-Object System.Text.UTF8Encoding($false)))
        try {
            Write-Host "  render $name"
            # **npx 會往 stderr 寫東西（npm notice 之類），那不是錯誤。**
            # PowerShell 5.1 會把原生指令的 stderr 包成 ErrorRecord，配上
            # `$ErrorActionPreference = 'Stop'` 就會在「其實成功了」的時候中斷。
            # 這裡只認 `$LASTEXITCODE`。
            $previous = $ErrorActionPreference
            $ErrorActionPreference = 'Continue'
            try {
                & npx -y '@mermaid-js/mermaid-cli@11' -i $mmd -o $svgPath -c $themePath -b transparent
            }
            finally {
                $ErrorActionPreference = $previous
            }
            if ($LASTEXITCODE -ne 0) { throw "mermaid-cli 失敗（$name），exit=$LASTEXITCODE" }
        }
        finally {
            Remove-Item $mmd -ErrorAction SilentlyContinue
            Remove-Item $tmp.FullName -ErrorAction SilentlyContinue
        }
    }
}

if ($Check) {
    if ($stale.Count -gt 0) {
        Write-Host ''
        Write-Host "這些圖過期了：" -ForegroundColor Yellow
        $stale | ForEach-Object { Write-Host "  $_" }
        Write-Host "跑 .\tools\diagrams\Render-Diagrams.ps1 重新產生。"
        exit 1
    }
    Write-Host "所有圖都是最新的。"
    exit 0
}

$manifest = [ordered]@{
    note     = '產生物。改了 .md 裡的 mermaid 就重跑 tools/diagrams/Render-Diagrams.ps1。'
    diagrams = $entries
}
# .json 一律 UTF-8 無 BOM。
$json = $manifest | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($manifestPath, $json, (New-Object System.Text.UTF8Encoding($false)))

Write-Host ''
Write-Host ("完成：{0} 張圖 -> {1}" -f $entries.Count, $outDir)
