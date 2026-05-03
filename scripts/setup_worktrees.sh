#!/usr/bin/env bash
# DocWise Multi-Agent Worktree Setup
# 为每个 Agent 创建独立的 git worktree，实现并行开发
#
# 使用方法:
#   chmod +x scripts/setup_worktrees.sh
#   ./scripts/setup_worktrees.sh
#
# 前提条件:
#   - 已完成 Phase 1 并合并到 main
#   - 当前在项目根目录

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKTREE_DIR="$PROJECT_ROOT/.worktrees"

echo "=== DocWise Multi-Agent Worktree Setup ==="
echo "Project root: $PROJECT_ROOT"
echo "Worktree dir: $WORKTREE_DIR"
echo ""

# 确保在 main 分支且是最新
cd "$PROJECT_ROOT"
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "main" ]; then
    echo "WARNING: 当前不在 main 分支 (当前: $CURRENT_BRANCH)"
    echo "建议先切换到 main 并确保最新"
    read -p "继续? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# 创建 worktree 目录
mkdir -p "$WORKTREE_DIR"

# Agent 分支定义
declare -A AGENTS=(
    ["agent-b"]="feat/document-pipeline"
    ["agent-c"]="feat/retrieval-agent"
    ["agent-d"]="feat/api-frontend"
    ["agent-e"]="feat/quality-eval"
)

# 为每个 Agent 创建 worktree
for agent in "${!AGENTS[@]}"; do
    branch="${AGENTS[$agent]}"
    worktree_path="$WORKTREE_DIR/$agent"

    if [ -d "$worktree_path" ]; then
        echo "  [SKIP] $agent — worktree already exists at $worktree_path"
        continue
    fi

    echo "  [CREATE] $agent → branch: $branch"

    # 创建分支（如果不存在）
    if ! git show-ref --verify --quiet "refs/heads/$branch"; then
        git branch "$branch" main
    fi

    # 创建 worktree
    git worktree add "$worktree_path" "$branch"
done

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Worktree 路径:"
for agent in "${!AGENTS[@]}"; do
    echo "  $agent: $WORKTREE_DIR/$agent"
done
echo ""
echo "使用方法:"
echo "  cd $WORKTREE_DIR/agent-b   # Agent B 的工作目录"
echo "  cd $WORKTREE_DIR/agent-c   # Agent C 的工作目录"
echo "  cd $WORKTREE_DIR/agent-d   # Agent D 的工作目录"
echo "  cd $WORKTREE_DIR/agent-e   # Agent E 的工作目录"
echo ""
echo "合并顺序 (Phase 3):"
echo "  1. git merge feat/quality-eval       # Agent E (tracer + mock)"
echo "  2. git merge feat/document-pipeline  # Agent B (LLM + embedder + ingestion)"
echo "  3. git merge feat/retrieval-agent    # Agent C (retrieval + agent)"
echo "  4. git merge feat/api-frontend       # Agent D (API + frontend)"
echo ""
echo "清理 worktrees:"
echo "  git worktree remove $WORKTREE_DIR/agent-b"
echo "  git worktree remove $WORKTREE_DIR/agent-c"
echo "  git worktree remove $WORKTREE_DIR/agent-d"
echo "  git worktree remove $WORKTREE_DIR/agent-e"
