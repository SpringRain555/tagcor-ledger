<#
    template: tools/diagrams/Render-Diagrams.ps1 v3

.SYNOPSIS
    把 docs 裡的 mermaid 區塊算成 SVG，並記下每一段原始碼與配色檔的 SHA-256。

    v2（2026-09-12）：區塊第一行寫 `%% name: <名字>` 就用那個名字當檔名（`<名字>.svg`），
    沒寫的照舊 `<文件名>-<第幾段>.svg`。`%%` 是 mermaid 的註解，渲染時被忽略。
    要固定名字的理由是 dashboard／README 會用路徑引用某一張圖，而序號在前面插一張就會位移。
    同一個 OutDir 裡名字撞到會直接 throw，不會靜默覆蓋。

    v3（2026-09-15）：`-Check` 不建任何資料夾，`DocsDir` 不存在就直接 throw。v2 不管有沒有 `-Check`
    都先建 OutDir —— 在 `D:\Projects` 根目錄不帶參數跑 `-Check`，建出一個空的 `docs\architecture\diagrams`
    （連同上層），然後因為裡面沒有任何 .md 而回報「所有圖都是最新的」。檢查指錯地方要紅，不能是綠的。

.DESCRIPTION
    CONVENTIONS §18：mermaid 寫在 .md 裡是唯一正本，SVG 是產生物但進版控 ——
    否則沒裝 node 的人（含日後讀這份專案的 LLM）看不到圖。

    **人手動跑，不進 Verify.ps1 的必經路徑。** 第一次執行會讓 npx 下載 mermaid-cli 與它帶的
    Chromium（約數百 MB，需要網路）。App 的「永遠不連網」規則約束的是 `src/`；
    `tools/` 本來就是手動離線工具。

    改了任何一段 mermaid 或 `mermaid-config.json` 就要重跑，否則 `-Check` 會紅。
    `-Check` 只比對 SHA-256，**不需要 node**，所以 Verify.ps1 照樣跑得動。

    這份是逐字複製型範本（CONVENTIONS §14）：專案照抄、不改。專案能調的只有旁邊的
    `mermaid-config.json`（配色，骨架型）與呼叫時的參數。要改腳本本身就回
    `_meta\templates\tools\diagrams\Render-Diagrams.ps1` 改，版本號 +1。
    來源是 tagcor-ledger 的 `tools\diagrams\Render-Diagrams.ps1`（2026-09-11），
    參數化了目錄與背景，讓 `_meta` 自己也能用同一支。

.PARAMETER Check
    只檢查有沒有過期，不重算。過期 exit 1。

.PARAMETER DocsDir
    掃哪個資料夾的 .md（不遞迴）。預設 `docs\architecture`。

.PARAMETER OutDir
    SVG 與 manifest.json 放哪。預設 `<DocsDir>\diagrams`。

.PARAMETER Background
    傳給 mermaid-cli 的 -b。預設 transparent；要固定底色就給色碼。

.EXAMPLE
    .\tools\diagrams\Render-Diagrams.ps1
    .\tools\diagrams\Render-Diagrams.ps1 -Check
#>
[CmdletBinding()]
param(
    [switch]$Check,
    [string]$DocsDir,
    [string]$OutDir,
    [string]$Background = 'transparent'
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $DocsDir) { $DocsDir = Join-Path $root 'docs\architecture' }
if (-not $OutDir)  { $OutDir  = Join-Path $DocsDir 'diagrams' }
$manifestPath = Join-Path $OutDir 'manifest.json'
$themePath = Join-Path $PSScriptRoot 'mermaid-config.json'

# v3：掃的資料夾不在就停下來 —— 否則 -Check 會對一個不存在（或剛被建出來的空）資料夾說「所有圖都是最新的」。
if (-not (Test-Path -LiteralPath $DocsDir -PathType Container)) {
    throw "找不到要掃的資料夾：$DocsDir（-DocsDir 指錯了，或這支腳本不在 <專案>\tools\diagrams\ 底下）"
}
# v3：只有真的要算圖才建輸出資料夾；-Check 是唯讀的。
if (-not $Check -and -not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir | Out-Null
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

# **配色檔也要進 manifest。**
#
# 只雜湊 mermaid 原始碼的話，`mermaid-config.json` 改了之後 `-Check` 照樣說
# 「所有圖都是最新的」—— 而已提交的 SVG 全部是用舊配色算的。
# **一張用錯顏色的圖跟一張用對顏色的圖，在過期檢查上長得一樣。**
#
# 行尾先正規化再雜湊：`.gitattributes` 會換行尾，
# 直接雜湊檔案內容的話，同一份設定在兩台機器上會得到兩個 hash。
$themeHash = Get-Sha256 -Text ([System.IO.File]::ReadAllLines($themePath) -join "`n")

$entries = @()
$stale = @()
$existing = @{}
$themeChanged = $true
if (Test-Path $manifestPath) {
    $loaded = Get-Content $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($item in $loaded.diagrams) { $existing[$item.svg] = $item.sha256 }
    $themeChanged = ($loaded.theme -ne $themeHash)
}
if ($themeChanged -and -not $Check) {
    Write-Host '配色檔變了 —— 全部重算。'
}

$taken = @{}
foreach ($doc in (Get-ChildItem -Path $DocsDir -Filter '*.md' -File | Sort-Object Name)) {
    $blocks = @(Get-Blocks -Path $doc.FullName)
    for ($i = 0; $i -lt $blocks.Count; $i++) {
        $source = $blocks[$i]
        $hash = Get-Sha256 -Text $source
        # v2：第一行 `%% name: xxx` 決定檔名；只認第一行，避免把圖裡別處的註解當成命名。
        $firstLine = ($source -split "`n", 2)[0].Trim()
        if ($firstLine -match '^%%\s*name:\s*(?<n>[A-Za-z0-9][A-Za-z0-9._-]*)\s*$') {
            $name = '{0}.svg' -f $Matches['n']
        } else {
            $name = '{0}-{1}.svg' -f $doc.BaseName, ($i + 1)
        }
        if ($taken.ContainsKey($name)) {
            throw "兩段 mermaid 都要輸出成 $name（$($taken[$name]) 與 $($doc.Name) 第 $($i + 1) 段）—— 名字要唯一"
        }
        $taken[$name] = '{0} 第 {1} 段' -f $doc.Name, ($i + 1)
        $svgPath = Join-Path $OutDir $name
        $entries += [ordered]@{
            document = $doc.Name
            index    = $i + 1
            svg      = $name
            sha256   = $hash
        }

        $upToDate = (-not $themeChanged) -and (Test-Path $svgPath) -and $existing.ContainsKey($name) -and ($existing[$name] -eq $hash)
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
                # v2：svg 的 id 用檔名（預設全部叫 my-svg）。把兩張圖內嵌進同一頁 HTML 時，
                # 每張圖的 <style> 都以 #<id> 限定範圍，id 重複就互相套到對方身上。
                $svgId = 'diagram-' + [System.IO.Path]::GetFileNameWithoutExtension($name)
                & npx -y '@mermaid-js/mermaid-cli@11' -i $mmd -o $svgPath -c $themePath -b $Background -I $svgId
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
    note     = '產生物。改了 .md 裡的 mermaid 或 tools/diagrams/mermaid-config.json 就重跑 tools/diagrams/Render-Diagrams.ps1。'
    theme    = $themeHash
    diagrams = $entries
}
# .json 一律 UTF-8 無 BOM。
$json = $manifest | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($manifestPath, $json, (New-Object System.Text.UTF8Encoding($false)))

Write-Host ''
Write-Host ("完成：{0} 張圖 -> {1}" -f $entries.Count, $OutDir)
