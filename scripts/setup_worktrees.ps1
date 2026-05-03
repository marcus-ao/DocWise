# DocWise Multi-Agent Worktree Setup (PowerShell)
# 为每个 Agent 创建独立的 git worktree，实现并行开发
#
# 使用方法:
#   .\scripts\setup_worktrees.ps1
#
# 前提条件:
#   - 已完成 Phase 1 并合并到 main
#   - 当前在项目根目录

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$WorktreeDir = Join-Path $ProjectRoot ".worktrees"

Write-Host "=== DocWise Multi-Agent Worktree Setup ===" -ForegroundColor Cyan
Write-Host "Project root: $ProjectRoot"
Write-Host "Worktree dir: $WorktreeDir"
Write-Host ""

# 确保在 main 分支
Set-Location $ProjectRoot
$CurrentBranch = git branch --show-current
if ($CurrentBranch -ne "main") {
    Write-Host "WARNING: 当前不在 main 分支 (当前: $CurrentBranch)" -ForegroundColor Yellow
    $reply = Read-Host "继续? (y/N)"
    if ($reply -ne "y" -and $reply -ne "Y") {
        exit 1
    }
}

# 创建 worktree 目录
if (-not (Test-Path $WorktreeDir)) {
    New-Item -ItemType Directory -Path $WorktreeDir | Out-Null
}

# Agent 分支定义
$Agents = @{
    "agent-b" = "feat/document-pipeline"
    "agent-c" = "feat/retrieval-agent"
    "agent-d" = "feat/api-frontend"
    "agent-e" = "feat/quality-eval"
}

# 为每个 Agent 创建 worktree
foreach ($agent in $Agents.Keys | Sort-Object) {
    $branch = $Agents[$agent]
    $worktreePath = Join-Path $WorktreeDir $agent

    if (Test-Path $worktreePath) {
        Write-Host "  [SKIP] $agent - worktree already exists at $worktreePath" -ForegroundColor DarkGray
        continue
    }

    Write-Host "  [CREATE] $agent -> branch: $branch" -ForegroundColor Green

    # 创建分支（如果不存在）
    $branchExists = git show-ref --verify --quiet "refs/heads/$branch" 2>$null
    if ($LASTEXITCODE -ne 0) {
        git branch $branch main
    }

    # 创建 worktree
    git worktree add $worktreePath $branch
}

Write-Host ""
Write-Host "=== Setup Complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Worktree 路径:" -ForegroundColor White
foreach ($agent in $Agents.Keys | Sort-Object) {
    $worktreePath = Join-Path $WorktreeDir $agent
    Write-Host "  ${agent}: $worktreePath"
}

Write-Host ""
Write-Host "使用方法:" -ForegroundColor White
Write-Host "  cd $WorktreeDir\agent-b   # Agent B 的工作目录"
Write-Host "  cd $WorktreeDir\agent-c   # Agent C 的工作目录"
Write-Host "  cd $WorktreeDir\agent-d   # Agent D 的工作目录"
Write-Host "  cd $WorktreeDir\agent-e   # Agent E 的工作目录"

Write-Host ""
Write-Host "合并顺序 (Phase 3):" -ForegroundColor White
Write-Host "  1. git merge feat/quality-eval       # Agent E (tracer + mock)"
Write-Host "  2. git merge feat/document-pipeline  # Agent B (LLM + embedder + ingestion)"
Write-Host "  3. git merge feat/retrieval-agent    # Agent C (retrieval + agent)"
Write-Host "  4. git merge feat/api-frontend       # Agent D (API + frontend)"

Write-Host ""
Write-Host "清理 worktrees:" -ForegroundColor White
Write-Host "  git worktree remove $WorktreeDir\agent-b"
Write-Host "  git worktree remove $WorktreeDir\agent-c"
Write-Host "  git worktree remove $WorktreeDir\agent-d"
Write-Host "  git worktree remove $WorktreeDir\agent-e"
