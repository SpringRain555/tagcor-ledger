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

# 查找邏輯與 Launch.ps1 共用同一份，見 tools\Resolve-TagcorPython.ps1。
. (Join-Path $ProjectRoot 'tools\Resolve-TagcorPython.ps1')
$Python = Resolve-TagcorPython
if (-not $Python) {
    Write-Host ''
    Write-Host '  失敗  找不到 conda 環境 tagcor-ledger 的 python.exe' -ForegroundColor Red
    Write-Host '        先建立環境：conda env create -f environment.yaml' -ForegroundColor Yellow
    Write-Host '        或指定位置：$env:TAGCOR_PYTHON = "X:\...\envs\tagcor-ledger\python.exe"' -ForegroundColor Yellow
    Write-Host ''
    exit 1
}

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

function Test-QtTypeStubs {
    <#
        conda-forge 的 pyside6 **有 49 個 .pyi 但沒有 py.typed**，而依 PEP 561
        少了那個標記檔，整包 stub 就會被忽略 —— 於是 `mypy --strict` 把所有 Qt
        互動都當成 `Any`，等於這一層對整個 ui/ 幾乎沒有在檢查。

        這不是假設。2026-09-01 加上 CI（裝的是有 py.typed 的 pip 版）之後，第一次
        跑就報出五個本機從來沒看過的錯誤，其中 `reorder_dialog` 的 `self.children`
        **蓋掉了 `QObject.children()` 這個 Qt 方法**。

        標記檔補上去就好：stub 本身是上游 PySide6 就有的，conda-forge 只是沒把
        標記一起打包。補完之後本機會抓到與 CI 一模一樣的錯誤（實測過）。

        pip 版本來就有這個檔，所以這段對 pip/uv 裝的環境是 no-op。
    #>
    Write-Section 'Qt 型別 stub'

    # python.exe 的父目錄就是環境根目錄（Windows 的 conda 佈局；不要再往上一層）。
    $pySide = Join-Path (Split-Path -Parent $Python) 'Lib\site-packages\PySide6'
    if (-not (Test-Path -LiteralPath $pySide)) {
        Write-Note "略過：找不到 PySide6（$pySide）。"
        return
    }

    $marker = Join-Path $pySide 'py.typed'
    if (Test-Path -LiteralPath $marker) {
        Write-Pass 'PySide6 有 py.typed，mypy 看得到 Qt 的型別'
        return
    }

    if (-not (Test-Path -LiteralPath (Join-Path $pySide 'QtWidgets.pyi'))) {
        Add-Failure 'PySide6 既沒有 py.typed 也沒有 .pyi —— mypy 完全檢查不到 Qt。'
        return
    }

    New-Item -ItemType File -Path $marker -ErrorAction SilentlyContinue | Out-Null
    if (Test-Path -LiteralPath $marker) {
        Write-Pass '已補上 PySide6 的 py.typed（conda-forge 沒打包這個標記檔）'
        Write-Note 'mypy 從這一次起才真的會檢查 Qt 的型別。'
    } else {
        Add-Failure "無法建立 $marker —— mypy 會把整個 Qt 當成 Any，ui/ 幾乎不受檢查。"
    }
}

function Test-PathDrift {
    Write-Section '路徑漂移檢查'

    # 全新 clone 本來就沒有指標檔（那是 App 第一次設定路徑時才寫的），所以這是
    # **跳過**不是失敗 —— 讓一個沒設定過的環境第一次跑就看到紅色，紅的是環境不是程式碼。
    $pointer = Join-Path $env:LOCALAPPDATA 'TagCor\TagCorLedger\system_paths.json'
    if (-not (Test-Path -LiteralPath $pointer)) {
        Write-Note "略過：還沒有指標檔（$pointer）。"
        Write-Note "在 App 的『系統設定 → 記帳資料路徑』設定一次之後，這項才有東西可以比對。"
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

    # `.claude\settings.json` 不進版控（裡面是本機的 <私人資料樹> 路徑規則），
    # 所以新 clone 沒有它是正常的 —— 同上，跳過而不是失敗。
    $claudeSettings = Join-Path $ProjectRoot '.claude\settings.json'
    if (-not (Test-Path -LiteralPath $claudeSettings)) {
        Write-Note "略過：沒有 .claude\settings.json。從 .claude\settings.example.json 複製一份即可。"
        return
    }

    try {
        $config = Get-Content -LiteralPath $claudeSettings -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        Add-Failure "無法解析 .claude\settings.json —— JSON 壞掉時整份設定會被靜默忽略。"
        return
    }

    $allow = @($config.permissions.allow)
    $ask = @($config.permissions.ask)
    $deny = @($config.permissions.deny)
    $expected = "Read($(ConvertTo-RulePath $dataRoot)/**)"

    if ($allow -contains $expected) {
        Write-Pass "allow 清單與 data_root 一致"
    } else {
        Add-Failure "allow 清單沒有對應 data_root 的規則。"
        Write-Note "應該要有：$expected"
        Write-Note "目前有  ：$($allow -join ', ')"
    }

    # ── <私人資料樹> 的保護：檢查「基線在不在」，不是「清單全不全」──────────────
    #
    # 2026-09-06 之前，這裡列舉 <私人資料樹> 底下的每一個資料夾，要求每一個都出現在
    # **這個專案**的 deny 清單裡。那個做法有三個問題，而且當天三個都真的發生了：
    #
    #   1. **它是一份手維護的跨專案清單，所以會漂。** 檢查當天它同時「少了兩個新的
    #      資料根」與「擋著一個已經改名、根本不存在的資料夾」—— 兩個方向一起錯。
    #      而且每次**別的**專案新增資料根，這個專案就會紅一次。
    #   2. **它的失敗訊息是假的。** 使用者層基線已經把整棵樹的讀寫設成 `ask`，
    #      所以沒被列舉到的資料夾不是「agent 讀得到」，是「agent 要先問」。
    #      **一個把後果講錯的驗證器比沒有驗證器更糟。**
    #   3. **它會把私人資料夾的名字印到終端機上**，而這支腳本在公開 repo 裡。
    #
    # 現在檢查的是真正在保護的那個東西：**基線在不在**。規則在
    # `D:\Projects\_meta\CONVENTIONS.md` §11 —— 整棵私人樹 `ask`，硬擋只用
    # 「該擋的葉子」（備份與資料庫檔），而那些 pattern **不綁專案名，所以不會漂**。
    $financeDir = Split-Path -Parent $dataRoot
    $personalDir = Split-Path -Parent $financeDir
    $tree = ConvertTo-RulePath $personalDir

    # 基線在使用者層（「你，每個專案」），不管從哪個目錄啟動都生效 ——
    # 而**專案層只在從專案目錄啟動時載入**，所以真正要硬擋的東西不能只寫在這裡。
    $rules = @{ ask = @($ask); deny = @($deny) }
    $userSettings = Join-Path $env:USERPROFILE '.claude\settings.json'
    if (Test-Path -LiteralPath $userSettings) {
        try {
            $baseline = Get-Content -LiteralPath $userSettings -Raw -Encoding UTF8 | ConvertFrom-Json
            $rules.ask += @($baseline.permissions.ask)
            $rules.deny += @($baseline.permissions.deny)
        } catch {
            Add-Failure "無法解析使用者層 $userSettings —— JSON 壞掉時整份設定會被靜默忽略。"
        }
    } else {
        Write-Note "沒有使用者層 $userSettings —— 下面兩項只看得到專案層。"
    }

    $wantAsk = @('Read', 'Glob', 'Grep', 'Edit', 'Write') | ForEach-Object { "$_($tree/**)" }
    $missingAsk = @($wantAsk | Where-Object { $rules.ask -notcontains $_ })
    if ($missingAsk.Count -eq 0) {
        Write-Pass "<私人資料樹> 整棵是 ask"
    } else {
        Add-Failure "<私人資料樹> 沒有被 ask 涵蓋 —— 讀寫不會先問過使用者就直接放行。"
        foreach ($item in $missingAsk) { Write-Note "    缺：`"$item`"" }
    }

    # 葉子 deny 一定要用 /** 結尾。單一 * 在 glob 裡只 match 一層，
    # 會涵蓋資料夾本身卻涵蓋不到裡面的檔案。
    $wantDeny = @()
    foreach ($verb in @('Edit', 'Write')) {
        foreach ($leaf in @('**/backups/**', '**/*.sqlite', '**/*.db')) {
            $wantDeny += "$verb($tree/$leaf)"
        }
    }
    $missingDeny = @($wantDeny | Where-Object { $rules.deny -notcontains $_ })
    if ($missingDeny.Count -eq 0) {
        Write-Pass "備份與資料庫檔的寫入是 deny"
    } else {
        Add-Failure "該硬擋的葉子沒有 deny —— 備份或資料庫檔可能被寫壞。"
        foreach ($item in $missingDeny) { Write-Note "    缺：`"$item`"" }
    }

    # **這三項都攔不住 shell**（`Get-Content`、`cat`、`Select-String`）。
    # 成文規則（`AGENTS.md` 的資料邊界那一節）才是界線，設定檔只是把守規矩的那條路
    # 標示出來。這一行留在這裡，是為了不讓上面三個 OK 讀起來像「滴水不漏」。
    Write-Note '提醒：以上三項都攔不住 shell —— 成文規則才是界線（AGENTS.md）。'
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

    # 要在 mypy 之前 —— 它決定了那一步到底有沒有在檢查 Qt。
    Test-QtTypeStubs

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
