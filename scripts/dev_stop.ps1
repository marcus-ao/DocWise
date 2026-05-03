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
        Stop-Process -Id $pidValue -Force
        Write-Host "Stopped $($_.BaseName) with PID $pidValue"
    }
    Remove-Item -LiteralPath $pidPath -Force
}
