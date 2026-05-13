[CmdletBinding()]
param(
    [int]$ApiPort = 8000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$RunDir = Join-Path $Root ".run"
$LogsDir = Join-Path $Root "logs"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$WebDir = Join-Path $Root "web"
$WebNextDir = Join-Path $WebDir ".next"
$Node = (Get-Command node).Source

function Get-ListeningProcessId {
    param(
        [int]$Port
    )

    $connection = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($connection) {
        return [int]$connection.OwningProcess
    }

    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($connection) {
        return [int]$connection.OwningProcess
    }

    return $null
}

function Assert-PortAvailable {
    param(
        [string]$Name,
        [int]$Port,
        [string]$PidPath
    )

    $listenerPid = Get-ListeningProcessId -Port $Port
    if (-not $listenerPid) {
        return
    }

    if (Test-Path -LiteralPath $PidPath) {
        $registeredPid = [int](Get-Content -LiteralPath $PidPath -Raw)
        if ($registeredPid -eq $listenerPid) {
            throw "$Name already running with PID $listenerPid on port $Port"
        }
    }

    throw "$Name cannot start because port $Port is already in use by PID $listenerPid. Stop the stale process before retrying."
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Missing venv Python: $Python"
}
if (-not $Node) {
    throw "Missing Node.js executable in PATH"
}

foreach ($dir in @(
    $RunDir,
    (Join-Path $LogsDir "api"),
    (Join-Path $LogsDir "worker")
)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

Write-Host "Running Alembic migrations..."
& $Python -m alembic -c (Join-Path $Root "alembic\alembic.ini") upgrade head

function Start-DocWiseProcess {
    param(
        [string]$Name,
        [string]$FilePath = $Python,
        [string[]]$ArgumentList,
        [string]$LogSubdir,
        [string]$ProcessWorkDir = $Root
    )

    $pidPath = Join-Path $RunDir "docwise-$Name.pid"
    if ($Name -eq "api") {
        Assert-PortAvailable -Name $Name -Port $ApiPort -PidPath $pidPath
    }
    elseif ($Name -eq "web") {
        Assert-PortAvailable -Name $Name -Port 3000 -PidPath $pidPath
    }
    if (Test-Path -LiteralPath $pidPath) {
        $oldPid = [int](Get-Content -LiteralPath $pidPath -Raw)
        if (Get-Process -Id $oldPid -ErrorAction SilentlyContinue) {
            Write-Host "$Name already running with PID $oldPid"
            return $false
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
    Start-Sleep -Milliseconds 1200
    if ($process.HasExited) {
        $stderrPreview = ""
        if (Test-Path -LiteralPath $errLog) {
            $stderrPreview = (Get-Content -LiteralPath $errLog -Tail 20 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
        }
        throw "$Name failed to stay running after launch. Check $errLog.$([Environment]::NewLine)$stderrPreview"
    }
    Set-Content -LiteralPath $pidPath -Value $process.Id -Encoding ascii
    Write-Host "Started $Name with PID $($process.Id)"
    Write-Host "  stdout: $outLog"
    Write-Host "  stderr: $errLog"
    return $true
}

Start-DocWiseProcess `
    -Name "api" `
    -LogSubdir "api" `
    -ArgumentList @("-m", "uvicorn", "src.api.app:app", "--host", "127.0.0.1", "--port", "$ApiPort")

Start-DocWiseProcess `
    -Name "worker" `
    -LogSubdir "worker" `
    -ArgumentList @("-m", "arq", "src.tasks.worker.WorkerSettings")

New-Item -ItemType Directory -Force -Path (Join-Path $LogsDir "web") | Out-Null
$env:DOCWISE_API_PROXY_TARGET = "http://127.0.0.1:$ApiPort"
$env:NEXT_PUBLIC_DOCWISE_API_BASE_URL = "/api/v1"
$webPidPath = Join-Path $RunDir "docwise-web.pid"
$webRunning = $false
if (Test-Path -LiteralPath $webPidPath) {
    $webPid = [int](Get-Content -LiteralPath $webPidPath -Raw)
    $webRunning = $null -ne (Get-Process -Id $webPid -ErrorAction SilentlyContinue)
}
if (-not $webRunning -and (Test-Path -LiteralPath $WebNextDir)) {
    Remove-Item -LiteralPath $WebNextDir -Recurse -Force
}
Start-DocWiseProcess `
    -Name "web" `
    -FilePath $Node `
    -ArgumentList @(".\node_modules\next\dist\bin\next", "dev", "--hostname", "127.0.0.1", "--port", "3000") `
    -LogSubdir "web" `
    -ProcessWorkDir $WebDir
