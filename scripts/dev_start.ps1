[CmdletBinding()]
param(
    [int]$ApiPort = 8000,
    [int]$FrontendPort = 8501
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$RunDir = Join-Path $Root ".run"
$LogsDir = Join-Path $Root "logs"
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Missing venv Python: $Python"
}

foreach ($dir in @(
    $RunDir,
    (Join-Path $LogsDir "api"),
    (Join-Path $LogsDir "worker"),
    (Join-Path $LogsDir "frontend")
)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

function Start-DocWiseProcess {
    param(
        [string]$Name,
        [string]$FilePath = $Python,
        [string[]]$ArgumentList,
        [string]$LogSubdir,
        [string]$ProcessWorkDir = $Root
    )

    $pidPath = Join-Path $RunDir "docwise-$Name.pid"
    if (Test-Path -LiteralPath $pidPath) {
        $oldPid = [int](Get-Content -LiteralPath $pidPath -Raw)
        if (Get-Process -Id $oldPid -ErrorAction SilentlyContinue) {
            Write-Host "$Name already running with PID $oldPid"
            return
        }
        Remove-Item -LiteralPath $pidPath -Force
    }

    $outLog = Join-Path $LogsDir "$LogSubdir\docwise-$Name.out.log"
    $errLog = Join-Path $LogsDir "$LogSubdir\docwise-$Name.err.log"
    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $ProcessWorkDir `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog `
        -PassThru `
        -WindowStyle Hidden
    Set-Content -LiteralPath $pidPath -Value $process.Id -Encoding ascii
    Write-Host "Started $Name with PID $($process.Id)"
    Write-Host "  stdout: $outLog"
    Write-Host "  stderr: $errLog"
}

Start-DocWiseProcess `
    -Name "api" `
    -LogSubdir "api" `
    -ArgumentList @("-m", "uvicorn", "src.api.app:app", "--host", "127.0.0.1", "--port", "$ApiPort")

Start-DocWiseProcess `
    -Name "worker" `
    -LogSubdir "worker" `
    -ArgumentList @("-m", "arq", "src.tasks.worker.WorkerSettings")

Start-DocWiseProcess `
    -Name "frontend-legacy" `
    -LogSubdir "frontend" `
    -ArgumentList @("-m", "streamlit", "run", "src/frontend/app.py", "--server.address=127.0.0.1", "--server.port=$FrontendPort")

New-Item -ItemType Directory -Force -Path (Join-Path $LogsDir "web") | Out-Null
Start-DocWiseProcess `
    -Name "web" `
    -FilePath "npm.cmd" `
    -ArgumentList @("run", "dev") `
    -LogSubdir "web" `
    -ProcessWorkDir (Join-Path $Root "web")
