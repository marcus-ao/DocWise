[CmdletBinding()]
param(
    [string]$ApiBaseUrl = $(if ($env:DOCWISE_API_BASE_URL) { $env:DOCWISE_API_BASE_URL } else { "http://127.0.0.1:8000/api/v1" }),
    [string]$AdminToken = $(if ($env:DOCWISE_ADMIN_TOKEN) { $env:DOCWISE_ADMIN_TOKEN } elseif ($env:ADMIN_API_TOKEN) { $env:ADMIN_API_TOKEN } else { "" }),
    [string]$ChatQuery = "Airflow task failure troubleshooting",
    [string]$ChatWorkspace = "public_tech",
    [string]$StreamQuery = "Airflow scheduler failure troubleshooting",
    [string]$StreamWorkspace = "project_airflow",
    [int]$AnswerPreviewChars = 700,
    [int]$BadCaseLimit = 5,
    [switch]$RunEval,
    [switch]$FullJson,
    [switch]$RawSse
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$script:Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $script:Utf8NoBom
$OutputEncoding = $script:Utf8NoBom

function Get-DotEnvValue {
    param([string]$Name)

    $envPath = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..")) ".env"
    if (-not (Test-Path -LiteralPath $envPath)) {
        return ""
    }

    foreach ($line in Get-Content -LiteralPath $envPath -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        $parts = $trimmed.Split("=", 2)
        if ($parts.Count -eq 2 -and $parts[0].Trim() -eq $Name) {
            return $parts[1].Trim().Trim('"').Trim("'")
        }
    }
    return ""
}

function New-JsonBytes {
    param([hashtable]$Body)

    $json = $Body | ConvertTo-Json -Compress -Depth 20
    [byte[]]$bytes = $script:Utf8NoBom.GetBytes($json)
    return ,$bytes
}

function Read-ResponseText {
    param([object]$Response)

    $streamProperty = $Response.PSObject.Properties["RawContentStream"]
    if ($streamProperty -and $streamProperty.Value) {
        $stream = $streamProperty.Value
        if ($stream.CanSeek) {
            $stream.Position = 0
        }
        $reader = [System.IO.StreamReader]::new($stream, $script:Utf8NoBom, $true)
        try {
            return $reader.ReadToEnd()
        }
        finally {
            $reader.Dispose()
        }
    }

    $contentProperty = $Response.PSObject.Properties["Content"]
    if (-not $contentProperty) {
        return ""
    }
    $content = $contentProperty.Value
    if ($content -is [byte[]]) {
        return $script:Utf8NoBom.GetString($content)
    }
    return [string]$content
}

function Read-ErrorResponseText {
    param([System.Management.Automation.ErrorRecord]$ErrorRecord)

    $response = $ErrorRecord.Exception.Response
    if ($null -eq $response) {
        return $ErrorRecord.Exception.Message
    }
    $stream = $response.GetResponseStream()
    if ($null -eq $stream) {
        return $ErrorRecord.Exception.Message
    }
    $reader = [System.IO.StreamReader]::new($stream, $script:Utf8NoBom, $true)
    try {
        $text = $reader.ReadToEnd()
        if ($text) {
            return $text
        }
    }
    finally {
        $reader.Dispose()
    }
    return $ErrorRecord.Exception.Message
}

function Invoke-DocWiseJson {
    param(
        [ValidateSet("GET", "POST")]
        [string]$Method,
        [string]$Path,
        [hashtable]$Body
    )

    $uri = "$ApiBaseUrl$Path"
    $params = @{
        Method = $Method
        Uri = $uri
        Headers = $script:Headers
        UseBasicParsing = $true
    }
    if ($Body) {
        $params["ContentType"] = "application/json; charset=utf-8"
        $params["Body"] = New-JsonBytes $Body
    }

    try {
        $response = Invoke-WebRequest @params
    }
    catch {
        $errorText = Read-ErrorResponseText $_
        throw "HTTP request failed: $Method $uri`n$errorText"
    }

    $text = Read-ResponseText $response
    if (-not $text.Trim()) {
        return $null
    }
    return $text | ConvertFrom-Json
}

function Write-Section {
    param([string]$Title)

    Write-Host ""
    Write-Host "== $Title ==" -ForegroundColor Cyan
}

function Get-Prop {
    param([object]$Value, [string]$Name)

    if ($null -eq $Value) {
        return $null
    }
    $property = $Value.PSObject.Properties[$Name]
    if ($property) {
        return $property.Value
    }
    return $null
}

function ConvertTo-Array {
    param([object]$Value)

    if ($null -eq $Value) {
        return @()
    }
    return @($Value)
}

function Get-Preview {
    param([object]$Text, [int]$MaxChars = 700)

    if ($null -eq $Text) {
        return ""
    }
    $clean = ([string]$Text) -replace "\r?\n", " "
    if ($clean.Length -le $MaxChars) {
        return $clean
    }
    return "$($clean.Substring(0, $MaxChars))..."
}

function Write-JsonOrSummary {
    param([object]$Value, [scriptblock]$Summary)

    if ($FullJson) {
        $Value | ConvertTo-Json -Depth 30
        return
    }
    & $Summary
}

function Get-ToolOutputSummary {
    param([string]$ToolName, [object]$Output)

    $summary = Get-Prop $Output "summary"
    if ($summary) {
        return [string]$summary
    }

    switch ($ToolName) {
        "query_project_manifest" {
            $matchedServices = @(ConvertTo-Array (Get-Prop $Output "matched_services"))
            $dependencies = @(ConvertTo-Array (Get-Prop $Output "dependencies"))
            $runbooks = @(ConvertTo-Array (Get-Prop $Output "runbooks"))
            return "confidence=$(Get-Prop $Output "confidence") matched_services=$($matchedServices.Count) dependencies=$($dependencies.Count) runbooks=$($runbooks.Count)"
        }
        "query_service_status" {
            $alerts = @(ConvertTo-Array (Get-Prop $Output "active_alerts"))
            $metrics = Get-Prop $Output "metrics"
            return "service=$(Get-Prop $Output "service_name") status=$(Get-Prop $Output "status") alerts=$($alerts.Count) cpu=$(Get-Prop $metrics "cpu_percent") memory=$(Get-Prop $metrics "memory_percent")"
        }
        "query_mock_logs" {
            return "matched_count=$(Get-Prop $Output "matched_count") service=$(Get-Prop $Output "service_name")"
        }
        default {
            $status = Get-Prop $Output "status"
            if ($status) {
                return [string]$status
            }
            return ""
        }
    }
}

function Write-ChatSummary {
    param([object]$Chat)

    Write-Host ("query_id: {0}" -f (Get-Prop $Chat "query_id"))
    Write-Host ("run_id: {0}" -f (Get-Prop $Chat "run_id"))
    Write-Host ("route: {0} confidence={1}" -f (Get-Prop $Chat "route"), (Get-Prop $Chat "route_confidence"))
    Write-Host ("refused: {0} latency_ms={1}" -f (Get-Prop $Chat "refused"), (Get-Prop $Chat "latency_ms"))

    $answer = Get-Prop $Chat "answer"
    if ($answer) {
        Write-Host "answer_preview:"
        Write-Output (Get-Preview $answer $AnswerPreviewChars)
    }

    $citations = @(ConvertTo-Array (Get-Prop $Chat "citations"))
    Write-Host ("citations: {0}" -f $citations.Count)
    $citationOrdinal = 0
    foreach ($citation in ($citations | Select-Object -First 3)) {
        $citationOrdinal += 1
        $citationIndex = Get-Prop $citation "index"
        if ($null -eq $citationIndex) {
            $citationIndex = Get-Prop $citation "citation_index"
        }
        if ($null -eq $citationIndex) {
            $citationIndex = $citationOrdinal
        }
        Write-Host ("  [{0}] {1} score={2}" -f $citationIndex, (Get-Prop $citation "section_path"), (Get-Prop $citation "score"))
    }

    $toolCalls = @(ConvertTo-Array (Get-Prop $Chat "tool_calls"))
    Write-Host ("tool_calls: {0}" -f $toolCalls.Count)
    foreach ($call in $toolCalls) {
        $toolName = [string](Get-Prop $call "tool_name")
        $output = Get-Prop $call "output_json"
        $summary = Get-ToolOutputSummary $toolName $output
        Write-Host (
            "  #{0} {1}: {2} latency_ms={3} {4}" -f
            (Get-Prop $call "call_index"),
            $toolName,
            (Get-Prop $call "status"),
            (Get-Prop $call "latency_ms"),
            (Get-Preview $summary 160)
        )
    }
}

function Invoke-DocWiseSse {
    $streamBody = @{
        query = $StreamQuery
        workspace_slug = $StreamWorkspace
    } | ConvertTo-Json -Compress -Depth 20
    $tempBody = New-TemporaryFile
    $tempOutput = New-TemporaryFile
    try {
        [System.IO.File]::WriteAllText($tempBody.FullName, $streamBody, $script:Utf8NoBom)
        $curlArgs = @(
            "-N",
            "-sS",
            "-X", "POST",
            "$ApiBaseUrl/chat/stream",
            "-H", "Content-Type: application/json; charset=utf-8"
        )
        if ($script:Headers.ContainsKey("Authorization")) {
            $curlArgs += @("-H", "Authorization: $($script:Headers["Authorization"])")
        }
        $curlArgs += @("--data-binary", "@$($tempBody.FullName)")

        if ($RawSse) {
            & curl.exe @curlArgs
            if ($LASTEXITCODE -ne 0) {
                throw "curl.exe failed with exit code $LASTEXITCODE"
            }
            return [pscustomobject]@{ Events = @(); Done = $null; Raw = $true }
        }

        $curlArgs += @("--output", $tempOutput.FullName)
        & curl.exe @curlArgs
        if ($LASTEXITCODE -ne 0) {
            throw "curl.exe failed with exit code $LASTEXITCODE"
        }
        $streamText = [System.IO.File]::ReadAllText($tempOutput.FullName, $script:Utf8NoBom)
        return Write-SseSummary $streamText
    }
    finally {
        Remove-Item -LiteralPath $tempBody.FullName -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $tempOutput.FullName -Force -ErrorAction SilentlyContinue
    }
}

function Write-SseSummary {
    param([string]$StreamText)

    $events = New-Object System.Collections.Generic.List[string]
    $currentEvent = ""
    $donePayload = ""
    $done = $null
    foreach ($line in ($StreamText -split "\r?\n")) {
        if ($line -match "^event:\s*(.+)$") {
            $currentEvent = $Matches[1].Trim()
            $events.Add($currentEvent)
            continue
        }
        if ($currentEvent -eq "done" -and $line -match "^data:\s*(.+)$") {
            $donePayload = $Matches[1]
        }
    }

    Write-Host ("events: {0}" -f ($events -join " -> "))
    if ($donePayload) {
        try {
            $done = $donePayload | ConvertFrom-Json
            Write-Host (
                "done: query_id={0} run_id={1} refused={2} latency_ms={3}" -f
                (Get-Prop $done "query_id"),
                (Get-Prop $done "run_id"),
                (Get-Prop $done "refused"),
                (Get-Prop $done "latency_ms")
            )
        }
        catch {
            Write-Host "done: received but could not parse summary"
        }
    }
    return [pscustomobject]@{ Events = @($events); Done = $done; Raw = $false }
}

function Write-EvalRunSummary {
    param([object]$EvalRun)

    Write-Host ("eval_run_id: {0}" -f (Get-Prop $EvalRun "eval_run_id"))
    Write-Host ("job_id: {0}" -f (Get-Prop $EvalRun "job_id"))
    Write-Host ("status: {0}" -f (Get-Prop $EvalRun "status"))
}

function Write-AdminStatsSummary {
    param([object]$Stats)

    Write-Host (
        "documents={0} chunks={1} queries={2} agent_runs={3} eval_runs={4}" -f
        (Get-Prop $Stats "total_documents"),
        (Get-Prop $Stats "total_chunks"),
        (Get-Prop $Stats "total_queries"),
        (Get-Prop $Stats "total_agent_runs"),
        (Get-Prop $Stats "total_eval_runs")
    )
    foreach ($workspace in @(ConvertTo-Array (Get-Prop $Stats "workspaces"))) {
        Write-Host (
            "  {0}: documents={1} chunks={2}" -f
            (Get-Prop $workspace "slug"),
            (Get-Prop $workspace "document_count"),
            (Get-Prop $workspace "chunk_count")
        )
    }
}

function Write-IndexStatusSummary {
    param([object]$IndexStatus)

    Write-Host (
        "chunks total={0} active={1} inactive={2} model={3} dim={4}" -f
        (Get-Prop $IndexStatus "total_chunks"),
        (Get-Prop $IndexStatus "active_chunks"),
        (Get-Prop $IndexStatus "inactive_chunks"),
        (Get-Prop $IndexStatus "embedding_model"),
        (Get-Prop $IndexStatus "embedding_dim")
    )
    foreach ($workspace in @(ConvertTo-Array (Get-Prop $IndexStatus "workspaces"))) {
        Write-Host (
            "  {0}: chunks={1} latest_indexed_at={2}" -f
            (Get-Prop $workspace "slug"),
            (Get-Prop $workspace "chunk_count"),
            (Get-Prop $workspace "latest_indexed_at")
        )
    }
}

function Write-BadCasesSummary {
    param([object]$BadCases)

    $items = @(ConvertTo-Array (Get-Prop $BadCases "items"))
    Write-Host ("total_bad_cases={0} showing={1}" -f (Get-Prop $BadCases "total"), $items.Count)
    foreach ($item in $items) {
        $types = @(ConvertTo-Array (Get-Prop $item "bad_case_types"))
        Write-Host (
            "  {0} route={1} types={2}" -f
            (Get-Prop $item "case_id"),
            (Get-Prop $item "route"),
            ($types -join ",")
        )
        Write-Host ("    query: {0}" -f (Get-Preview (Get-Prop $item "query") 100))
    }
}

function Write-SmokeVerdict {
    param(
        [object]$Chat,
        [object]$SseSummary,
        [object]$EvalCount,
        [object]$EvalRun,
        [object]$IndexStatus
    )

    $citations = @(ConvertTo-Array (Get-Prop $Chat "citations"))
    $toolCalls = @(ConvertTo-Array (Get-Prop $Chat "tool_calls"))
    $activeChunks = Get-Prop $IndexStatus "active_chunks"
    $totalCases = Get-Prop $EvalCount "total_cases"
    $sseDone = $false
    if ($SseSummary -and -not (Get-Prop $SseSummary "Raw")) {
        $sseDone = $null -ne (Get-Prop $SseSummary "Done")
    }

    $checks = @(
        [pscustomobject]@{ Name = "chat_json_answer"; Ok = (($null -ne (Get-Prop $Chat "answer")) -and ((Get-Prop $Chat "refused") -eq $false)) },
        [pscustomobject]@{ Name = "chat_json_citations"; Ok = ($citations.Count -gt 0) },
        [pscustomobject]@{ Name = "chat_json_tool_calls"; Ok = ($toolCalls.Count -gt 0) },
        [pscustomobject]@{ Name = "chat_sse_done"; Ok = ($RawSse -or $sseDone) },
        [pscustomobject]@{ Name = "eval_cases_loaded"; Ok = ([int]$totalCases -gt 0) },
        [pscustomobject]@{ Name = "index_has_active_chunks"; Ok = ([int]$activeChunks -gt 0) },
        [pscustomobject]@{ Name = "eval_run"; Ok = ((-not $RunEval) -or ((Get-Prop $EvalRun "status") -eq "queued")) }
    )

    $failed = @($checks | Where-Object { -not $_.Ok })
    foreach ($check in $checks) {
        $mark = if ($check.Ok) { "ok" } else { "warn" }
        Write-Host ("{0}: {1}" -f $mark, $check.Name)
    }
    if ($failed.Count -eq 0) {
        Write-Host "SMOKE PASS: local end-to-end flow is reachable." -ForegroundColor Green
    }
    else {
        Write-Host "SMOKE WARN: one or more checks need attention." -ForegroundColor Yellow
    }
}

if (-not $AdminToken) {
    $AdminToken = Get-DotEnvValue "ADMIN_API_TOKEN"
}
if (-not $env:DOCWISE_API_BASE_URL -and $ApiBaseUrl -eq "http://127.0.0.1:8000/api/v1") {
    $dotEnvApiBaseUrl = Get-DotEnvValue "DOCWISE_API_BASE_URL"
    if ($dotEnvApiBaseUrl) {
        $ApiBaseUrl = $dotEnvApiBaseUrl
    }
}

$script:Headers = @{}
if ($AdminToken) {
    $script:Headers["Authorization"] = "Bearer $AdminToken"
}

Write-Section "Chat JSON"
$chat = Invoke-DocWiseJson -Method POST -Path "/chat" -Body @{
    query = $ChatQuery
    workspace_slug = $ChatWorkspace
}
Write-JsonOrSummary $chat { Write-ChatSummary $chat }

Write-Section "Chat SSE"
$sseSummary = Invoke-DocWiseSse
if (-not $RawSse) {
    Write-Host "Pass -RawSse to print the full live SSE stream."
}

Write-Section "Eval count"
$evalCount = Invoke-DocWiseJson -Method GET -Path "/eval/count"
Write-JsonOrSummary $evalCount { Write-Host ("total_cases: {0}" -f (Get-Prop $evalCount "total_cases")) }

$evalRun = $null
if ($RunEval) {
    Write-Section "Eval run"
    $evalRun = Invoke-DocWiseJson -Method POST -Path "/eval/run" -Body @{
        retry_failed = $false
    }
    Write-JsonOrSummary $evalRun { Write-EvalRunSummary $evalRun }
    Write-Host ("Track job: {0}/documents/jobs/{1}" -f $ApiBaseUrl, (Get-Prop $evalRun "job_id"))
}
else {
    Write-Host "Eval run skipped. Pass -RunEval to enqueue a full eval job." -ForegroundColor Yellow
}

Write-Section "Admin stats"
$adminStats = Invoke-DocWiseJson -Method GET -Path "/admin/stats"
Write-JsonOrSummary $adminStats { Write-AdminStatsSummary $adminStats }

Write-Section "Admin index status"
$indexStatus = Invoke-DocWiseJson -Method GET -Path "/admin/index-status"
Write-JsonOrSummary $indexStatus { Write-IndexStatusSummary $indexStatus }

Write-Section "Admin bad cases"
$badCases = Invoke-DocWiseJson -Method GET -Path "/admin/bad-cases?limit=$BadCaseLimit"
Write-JsonOrSummary $badCases { Write-BadCasesSummary $badCases }

Write-Section "Smoke verdict"
Write-SmokeVerdict $chat $sseSummary $evalCount $evalRun $indexStatus
