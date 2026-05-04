$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$RunDir = Join-Path $Root ".run"

if (-not (Test-Path $RunDir)) {
    Write-Host "No DocWise dev process registry found."
    exit 0
}

Get-ChildItem -LiteralPath $RunDir -Filter "docwise-*.pid" | ForEach-Object {
    $pidPath = $_.FullName
    $pidValue = [int](Get-Content -LiteralPath $pidPath -Raw)
    $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    if ($process) {
        & taskkill.exe /PID $pidValue /T /F | Out-Null
        Write-Host "Stopped $($_.BaseName) with PID $pidValue"
    }
    if (Test-Path -LiteralPath $pidPath) {
        Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
    }
}
