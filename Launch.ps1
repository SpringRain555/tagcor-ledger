#Requires -Version 5.1
<#
.SYNOPSIS
    啟動 TagCor Ledger 桌面程式，不依賴 PATH 也不需要先 conda activate。

.DESCRIPTION
    這個腳本存在的唯一理由是「PATH 上的 python 不可信」。

    實際踩過的情形：終端機裡開著別的專案的 venv，再 `conda activate tagcor-ledger`，
    兩個都回報成功、提示字元變成 `(.venv) (tagcor-ledger)`，但 venv 的 Scripts 仍排在
    PATH 前面，所以 `python` 解析到的是別的專案的直譯器，得到
    `No module named tagcor_ledger`。錯誤訊息完全指不到真正的原因。

    所以這裡一律用**絕對路徑**呼叫 conda 環境的直譯器，並在啟動前把繼承來的
    VIRTUAL_ENV / PYTHONHOME / PYTHONPATH 清掉。

.PARAMETER CreateShortcut
    在桌面建立捷徑，之後雙擊捷徑即可，不用再進專案資料夾。

.PARAMETER DataDir
    覆寫這一次執行的資料根目錄。平常不要用 —— 正式資料路徑由「系統設定 → 資料路徑」管理。

.PARAMETER ReadyTimeoutSeconds
    最多等主視窗幾秒。程式在 `window.show()` 之後會寫一個標記檔，這個腳本等的是那個檔案
    出現，不是固定秒數 —— 這個數字只是「等到什麼時候該說出來還沒看到」的上限。

.EXAMPLE
    .\Launch.ps1
    .\Launch.ps1 -CreateShortcut
#>
[CmdletBinding()]
param(
    [switch]$CreateShortcut,
    [string]$DataDir,
    [int]$ReadyTimeoutSeconds = 90
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvName = 'tagcor-ledger'

function Write-Step  ([string]$Text) { Write-Host "`n=== $Text" -ForegroundColor Cyan }
function Write-Ok    ([string]$Text) { Write-Host "  OK    $Text" -ForegroundColor Green }
function Write-Bad   ([string]$Text) { Write-Host "  失敗  $Text" -ForegroundColor Red }

# 原生程式的輸出經過 2>&1 之後，stderr 那幾行會變成 ErrorRecord 物件。直接 Out-String
# 會把 PowerShell 的位置資訊（At ...Launch.ps1:127 char:11、CategoryInfo…）一起印出來，
# 那些對使用者毫無意義。這裡只取真正的訊息文字。
function ConvertTo-PlainText {
    param([object[]]$Output)
    $lines = foreach ($item in $Output) {
        if ($item -is [System.Management.Automation.ErrorRecord]) {
            $item.Exception.Message
        } else {
            [string]$item
        }
    }
    ($lines -join [Environment]::NewLine).TrimEnd()
}

function Read-TextFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return '' }
    $text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if ($null -eq $text) { return '' }
    return $text.TrimEnd()
}

function Stop-WithMessage {
    param([string]$Title, [string[]]$Lines)
    Write-Host ''
    Write-Bad $Title
    foreach ($line in $Lines) { Write-Host "        $line" -ForegroundColor Yellow }
    Write-Host ''
    Read-Host '按 Enter 關閉'
    exit 1
}

# --- 找到 conda 環境的直譯器 -------------------------------------------------
# 查找邏輯在 tools\Resolve-TagcorPython.ps1，與 Verify.ps1 共用同一份 ——
# 兩邊各寫一份的話，改了一邊沒改另一邊會變成「啟動得起來但驗證跑不了」。
. (Join-Path $ProjectRoot 'tools\Resolve-TagcorPython.ps1')

Write-Step "尋找 conda 環境 $EnvName"
$python = Resolve-TagcorPython -EnvName $EnvName
if (-not $python) {
    Stop-WithMessage "找不到 conda 環境 $EnvName 的 python.exe" @(
        '請先建立環境：',
        '    conda env create -f environment.yaml',
        '    conda activate tagcor-ledger',
        '    python -m pip install -e ".[dev]"',
        '',
        '若 conda 裝在非標準位置，設定環境變數指向它即可：',
        '    setx TAGCOR_PYTHON "X:\path\to\envs\tagcor-ledger\python.exe"'
    )
}
Write-Ok $python

# pythonw.exe 沒有主控台視窗；GUI 用它，前置檢查用 python.exe 才看得到輸出。
$pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) { $pythonw = $python }

# --- 清掉繼承來的環境污染 ----------------------------------------------------
# 從乾淨的 Explorer 雙擊時本來就沒有這些；從已經啟動別的 venv 的終端機執行時才會有。
foreach ($name in 'VIRTUAL_ENV', 'PYTHONHOME', 'PYTHONPATH', 'PYTHONSTARTUP') {
    if (Test-Path "env:$name") { Remove-Item "env:$name" }
}

# --- 前置檢查 ----------------------------------------------------------------
# 直接跑 --json：它同時證明「套件裝好了」「資料路徑可用」，並回報 log 目錄。
Write-Step '檢查套件與資料路徑'
$jsonArgs = @('-m', 'tagcor_ledger', '--json')
if ($DataDir) { $jsonArgs = @('-m', 'tagcor_ledger', '--data-dir', $DataDir, '--json') }

# **兩個串流必須分開收。** `--json` 保證 stdout 是純 JSON，診斷訊息一律走 stderr；
# 用 `2>&1` 合起來再解析的話，只要程式往 stderr 寫任何一行（例如啟動日誌），
# JSON 就解析失敗 —— 這正是 2026-08-18 踩到的：程式沒問題，是啟動器把兩條線接在一起。
#
# 順帶避開 PowerShell 5.1 的另一個坑：對原生程式用 `2>&1` 會把 stderr 每行包成
# ErrorRecord，在 $ErrorActionPreference = 'Stop' 之下直接丟例外。用 Start-Process
# 導向檔案就沒有這個問題。
$stamp = [guid]::NewGuid().ToString('N')
$outFile = Join-Path $env:TEMP "tagcor-preflight-$stamp.out"
$errFile = Join-Path $env:TEMP "tagcor-preflight-$stamp.err"

# 導向檔案時 Python 會用系統地區編碼（本機是 cp950），路徑含中文就會亂碼。
$env:PYTHONIOENCODING = 'utf-8'

try {
    $probe = Start-Process -FilePath $python -ArgumentList $jsonArgs -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput $outFile -RedirectStandardError $errFile
    $exitCode = $probe.ExitCode
    $outputText = (Read-TextFile $outFile)
    $errorText = (Read-TextFile $errFile)
} finally {
    Remove-Item $outFile, $errFile -ErrorAction SilentlyContinue
}

if ($exitCode -ne 0) {
    $outputText = (@($errorText, $outputText) | Where-Object { $_ }) -join [Environment]::NewLine
}
if ($exitCode -ne 0) {
    Stop-WithMessage '程式無法啟動' (
        ($outputText -split "`r?`n") + @(
            '',
            '最常見的原因是套件沒安裝到這個環境。修法：',
            '    conda activate tagcor-ledger',
            '    python -m pip install -e ".[dev]" --no-deps'
        )
    )
}

try {
    $info = $outputText | ConvertFrom-Json
} catch {
    Stop-WithMessage '啟動資訊無法解析' (
        @('程式回報成功，但 stdout 不是預期的 JSON。', '') +
        ($outputText -split "`r?`n")
    )
}
Write-Ok "版本 $($info.version)"
Write-Ok "資料庫 $($info.database_path)"

if ($CreateShortcut) {
    Write-Step '建立桌面捷徑'
    $launcher = Join-Path $ProjectRoot 'Start TagCor Ledger.cmd'
    $linkPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'TagCor Ledger.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($linkPath)
    $link.TargetPath = $launcher
    $link.WorkingDirectory = $ProjectRoot
    $link.Description = 'TagCor Ledger 記帳'
    $link.WindowStyle = 7          # 最小化，避免包裝用的主控台視窗跳出來
    $link.Save()
    Write-Ok $linkPath
}

# --- 啟動 --------------------------------------------------------------------
Write-Step '啟動'
$guiArgs = @('-m', 'tagcor_ledger', '--gui')
if ($DataDir) { $guiArgs = @('-m', 'tagcor_ledger', '--data-dir', $DataDir, '--gui') }

# pythonw 沒有主控台，所以未攔截的例外會無聲消失。先把 stderr 導到檔案，
# 這樣「視窗沒出現」至少留得下線索。（v0.8.0 起另有正式的啟動失敗畫面與日誌，
# 但那要程式跑得起來才有用 —— 這一行守的是那之前就掛掉的情況。）
$errorLog = Join-Path $info.log_dir 'launch-stderr.log'
$startArgs = @{
    FilePath         = $pythonw
    ArgumentList     = $guiArgs
    WorkingDirectory = $ProjectRoot
    PassThru         = $true
}
try {
    New-Item -ItemType Directory -Force -Path $info.log_dir | Out-Null
    $startArgs['RedirectStandardError'] = $errorLog
} catch {
    $errorLog = $null      # log 目錄不可寫不該讓程式開不起來
}

# 程式在 `window.show()` 之後會寫這個標記檔（app/startup_signal.py）。路徑從 --json
# 拿，不在這裡自己拼 —— 拼出來的會是第二份路徑實作，--data-dir 換了資料根之後它會
# 安靜地指錯地方，於是標記永遠等不到。
$marker = [string]$info.ready_marker
if (-not $marker) {
    Stop-WithMessage '啟動資訊缺少 ready_marker' @(
        '這一版的 Launch.ps1 需要程式回報標記檔的位置，請確認套件是同一個版本：',
        '    conda activate tagcor-ledger',
        '    python -m pip install -e ".[dev]" --no-deps'
    )
}
# 上一次留下的標記不能讓這一次以為自己已經成功了。
Remove-Item -LiteralPath $marker -Force -ErrorAction SilentlyContinue

$process = Start-Process @startArgs

# 等兩件事之一：標記檔出現（視窗真的顯示了），或行程結束（成功交棒、或啟動失敗）。
#
# 2026-08-18 到 2026-09-11 之間這裡是「等 5 秒，還活著就當視窗開了」。那擋得住
# 一啟動就死的情形，擋不住另外兩種：視窗第 8 秒才出來（主控台已經說「已開啟」然後
# 關掉，使用者對著空白等）、以及第 6 秒才炸掉（錯誤進了 log，唯一會說話的視窗已經
# 不在了）。固定秒數不是訊號，是猜測 —— CONVENTIONS §16 第 3 題。
#
# **正常結束（0）也會走到這裡。** 第二次啟動時程式會把既有視窗叫到最前面然後以 0 結束，
# 那是成功不是失敗。而 `Start-Process -PassThru` 的 `ExitCode` 有時候是 $null，
# 而 PowerShell 裡 `$null -ne 0` 為真 —— 2026-08-18 的誤報就是這樣來的：
# 畫面上印出「程式啟動後隨即結束（exit code ）」，括號裡是空的。
$deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    if (Test-Path -LiteralPath $marker) { break }
    if ($process.HasExited) { break }
    Start-Sleep -Milliseconds 250
}

if (Test-Path -LiteralPath $marker) {
    Write-Ok '視窗已開啟，可以關閉這個畫面。'
    exit 0
}

if ($process.HasExited) {
    $processExitCode = 0
    if ($null -ne $process.ExitCode) { $processExitCode = [int]$process.ExitCode }
    if ($processExitCode -ne 0) {
        $detail = @()
        if ($errorLog -and (Test-Path -LiteralPath $errorLog)) {
            $detail = Get-Content -LiteralPath $errorLog -Tail 20 -Encoding UTF8
        }
        Stop-WithMessage "程式啟動後隨即結束（exit code $processExitCode）" (
            $detail + @('', "完整訊息：$errorLog")
        )
    }
    # 以 0 結束代表既有視窗已經被叫到最前面，這是第二次啟動的正常路徑。
    Write-Ok '既有視窗已切換到最前面。'
    exit 0
}

# 還在跑，但沒有主視窗也沒有結束。這個程式沒有 watchdog，所以最常見的解釋是
# 畫面上開著一個啟動失敗的對話框（六種啟動結果之一）—— 它在等使用者按掉。
# 不要說「應該沒問題」，把看到的說出來。
Stop-WithMessage "等了 $ReadyTimeoutSeconds 秒還沒看到主視窗，程式仍在執行（PID $($process.Id)）" @(
    '畫面上如果有錯誤對話框，照它的說明處理。',
    "沒有的話看 $errorLog",
    '（要多等一點可以加 -ReadyTimeoutSeconds 180）'
)
