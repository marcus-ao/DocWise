# DocWise GUIDE

本文是 DocWise 当前唯一权威的本地运行、调试、验收与日常操作指南。它已经合并原 `docs/GUIDE.md` 的项目操控说明与 `docs/WINDOWS_LOCAL_DEV_GUIDE.md` 的 Windows 全功能调试流程，并以当前 `src/`、脚本、Docker Compose、API 路由和恢复状态为准。

旧的多 Agent 并行开发说明保留在本文末尾的历史附录中，仅用于追溯，不作为当前运行步骤。

## 0. 当前运行边界

DocWise 是一个企业级开发者知识工作流 Agent 系统，当前恢复后的本地推荐运行方式是：

| 层级 | 当前实现 |
| --- | --- |
| Python | 3.11，使用仓库内 `.venv` |
| API | FastAPI，入口 `src.api.app:app` |
| Worker | `arq + Redis`，入口 `src.tasks.worker.WorkerSettings` |
| Frontend | Next.js，入口 `web/` |
| 数据库 | PostgreSQL + pgvector + tsvector |
| 队列/缓存 | Redis |
| 对象存储 | MinIO，bucket 默认为 `docwise-documents` |
| 生成模型 | DeepSeek-compatible chat |
| Embedding/Rerank | DashScope/Qwen，embedding 维度为 2048 |
| Trace/Eval | 本地数据库 trace/eval 为主，Langfuse 可选 |

本地开发推荐只用 Docker 跑 `postgres`、`redis`、`minio`，API、worker 由 Windows `.venv` 启动，前端使用 `web/` 下的 Next.js。完整 Docker app 服务仍保留在 Compose 中，但日常调试以本指南命令为准。

## 1. 准备 PowerShell 与虚拟环境

进入项目根目录：

```powershell
cd D:\VSCodeWorkspace\DocWise
```

建议启用 UTF-8：

```powershell
chcp 65001
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
```

确认 Python：

```powershell
.\.venv\Scripts\python.exe --version
```

如果 `.venv` 缺失或不是 Python 3.11：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## 2. 准备 `.env`

本地 `.venv` + Docker 基础设施使用 `.env.local.example`：

```powershell
Copy-Item .env.local.example .env
```

本地运行必须使用宿主机地址，不要把 API/worker 的 `.env` 写成 Docker 服务名：

```dotenv
DATABASE_URL=postgresql+asyncpg://docwise:docwise@localhost:15432/docwise
POSTGRES_HOST=localhost
POSTGRES_PORT=15432
POSTGRES_USER=docwise
POSTGRES_PASSWORD=docwise
REDIS_URL=redis://localhost:6379/0
MINIO_ENDPOINT=localhost:9000
MINIO_BUCKET=docwise-documents
DOCWISE_API_BASE_URL=http://127.0.0.1:8000/api/v1
```

真实入库、检索、Chat、Eval 需要：

```dotenv
DEEPSEEK_API_KEY=你的 DeepSeek key
DASHSCOPE_API_KEY=你的 DashScope/Qwen key
```

不要打印真实 key。只检查是否存在：

```powershell
@'
from pathlib import Path
for key in ("DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY"):
    value = ""
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(key + "="):
            value = line.split("=", 1)[1].strip()
            break
    print(f"{key}: {'set' if value else 'missing'}")
'@ | .\.venv\Scripts\python.exe -
```

## 3. 启动基础设施

```powershell
docker compose up -d postgres redis minio
docker compose ps
```

预期三项均 healthy：

```powershell
Test-NetConnection 127.0.0.1 -Port 15432
Test-NetConnection 127.0.0.1 -Port 6379
Test-NetConnection 127.0.0.1 -Port 9000
```

如果 Alembic 报 `InvalidPasswordError`，说明当前 Postgres volume 中的密码和 `.env` 不一致。开发环境可重置：

```powershell
docker compose down
docker volume ls | findstr docwise
docker volume rm docwise_postgres_data
docker compose up -d postgres redis minio
```

这个操作会删除本地开发数据库数据，只在确认可重建时执行。

## 4. 数据库迁移与种子数据

```powershell
.\.venv\Scripts\python.exe -m alembic -c alembic\alembic.ini upgrade head
.\.venv\Scripts\python.exe -m alembic -c alembic\alembic.ini current
```

当前恢复基线的 head 为：

```text
004 (head)
```

初始化 demo：

```powershell
.\.venv\Scripts\python.exe -m scripts.seed_demo
```

该命令会创建或更新：

- MinIO bucket：`docwise-documents`
- 默认 workspace
- `data/raw/` demo 文档
- `data/mock/` mock fixture
- `data/eval/` eval fixture 和数据库 eval cases

如果只需要部分初始化：

```powershell
.\.venv\Scripts\python.exe -m scripts.seed_workspaces
.\.venv\Scripts\python.exe -m scripts.seed_eval_cases
```

## 5. 质量门

Windows 临时目录偶尔会导致 pytest 权限问题，推荐使用仓库内临时目录：

```powershell
New-Item -ItemType Directory -Force .\.tmp\pytest | Out-Null
$env:TMP=(Resolve-Path .\.tmp\pytest)
$env:TEMP=$env:TMP
```

运行质量门：

```powershell
.\.venv\Scripts\python.exe -m scripts.validate_mock_data
.\.venv\Scripts\python.exe -m scripts.validate_eval_cases
.\.venv\Scripts\python.exe -m ruff check src tests scripts alembic
.\.venv\Scripts\python.exe -m pytest -q
```

当前恢复基线：

```text
validate_mock_data: ALL CHECKS PASSED
validate_eval_cases: ALL CHECKS PASSED (20 retrieval + 30 qa)
ruff: All checks passed!
pytest: 121 passed
```

如果 pytest 只出现 `AsyncMock ... was never awaited` warning，但结果为 passed，目前不影响功能验收。

## 6. 真实模型直连 Smoke

这一节用于确认 key、网络和 provider 配置。它不依赖业务数据库。

```powershell
@'
import asyncio
from src.document.embedder import embed_query, get_embedding_dim
from src.retrieval.reranker import rerank
from src.llm.client import chat_completion

async def main():
    vector = await embed_query("DocWise model smoke test")
    print("embedding_dim", len(vector), "expected", get_embedding_dim())
    chunks = [
        {"content": "DocWise uses FastAPI, arq, PostgreSQL, Redis, and MinIO.", "rrf_score": 1.0},
        {"content": "Unrelated text.", "rrf_score": 0.1},
    ]
    ranked, fallback = await rerank("DocWise runtime stack", chunks, top_k=1)
    print("rerank_count", len(ranked), "fallback", fallback)
    resp = await chat_completion(
        [{"role": "user", "content": "Reply with exactly: docwise-smoke-ok"}],
        model="fast",
        temperature=0,
        timeout=30.0,
    )
    print("chat_content", resp["content"][:80])

asyncio.run(main())
'@ | .\.venv\Scripts\python.exe -
```

预期：

```text
embedding_dim 2048 expected 2048
rerank_count 1 fallback False
chat_content docwise-smoke-ok
```

## 7. 启动 API、Worker、Frontend

推荐使用脚本：

```powershell
.\scripts\dev_start.ps1
```

如果 PowerShell 执行策略阻止：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev_start.ps1
```

脚本会启动：

| 进程 | 地址或入口 | 日志 |
| --- | --- | --- |
| FastAPI | http://127.0.0.1:8000 | `logs/api/` |
| arq worker | `src.tasks.worker.WorkerSettings` | `logs/worker/` |
| Next.js Web | http://127.0.0.1:3000 | `logs/web/` |

PID 文件写入 `.run/`。停止：

```powershell
.\scripts\dev_stop.ps1
```

## 8. 健康检查

```powershell
curl.exe http://127.0.0.1:8000/healthz
curl.exe http://127.0.0.1:8000/readyz
curl.exe http://127.0.0.1:3000
```

`/readyz` 预期类似：

```json
{"db":"ok","redis":"ok","minio":"ok","status":"ready"}
```

如果 `db` 或 `minio` degraded，优先检查 `.env` 地址、Docker 服务状态、Alembic 迁移和 MinIO bucket。

## 9. 文档入库验证

文档入库会调用 Qwen embedding，建议先通过第 6 节。

同步入库最适合定位问题：

```powershell
.\.venv\Scripts\python.exe -m scripts.ingest_docs --workspace public_tech --dir data\raw\airflow
```

当前恢复验证中，两份 Airflow demo 文档可处理到 `ready`。

异步入队需要 worker 正在运行：

```powershell
.\.venv\Scripts\python.exe -m scripts.ingest_docs --workspace public_tech --dir data\raw\airflow --enqueue
```

查询 job：

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/documents/jobs/<job_id>"
```

上传 API：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/documents/upload" `
  -F "workspace_slug=public_tech" `
  -F "file=@data/raw/airflow/airflow-runbook.md;type=text/markdown"
```

MinIO bucket 缺失的典型错误是：

```text
S3 operation failed; code: NoSuchBucket; bucket_name: docwise-documents
```

当前 `scripts.seed_demo` 和 ingestion 上传路径都会确保 bucket 存在；遇到该错误时先重跑 `scripts.seed_demo`，再确认 `MINIO_ENDPOINT=localhost:9000`。

## 10. 文档管理 API

列出文档：

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/documents?workspace_slug=public_tech"
```

详情：

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/documents/<document_id>"
```

重试 pending/error 文档：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/documents/<document_id>/retry"
```

删除记录与 chunk：

```powershell
curl.exe -X DELETE "http://127.0.0.1:8000/api/v1/documents/<document_id>/record"
```

删除记录、chunk 与对象存储：

```powershell
curl.exe -X DELETE "http://127.0.0.1:8000/api/v1/documents/<document_id>/purge"
```

## 11. Chat、Agent、Trace 与 Feedback

JSON Chat：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/chat" `
  -H "Content-Type: application/json" `
  -d "{\"query\":\"Airflow task 失败时应该先检查什么？\",\"workspace_slug\":\"public_tech\"}"
```

SSE Chat：

```powershell
curl.exe -N -X POST "http://127.0.0.1:8000/api/v1/chat/stream" `
  -H "Content-Type: application/json" `
  -d "{\"query\":\"帮我排查 Airflow scheduler 异常\",\"workspace_slug\":\"public_tech\"}"
```

历史与反馈：

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/chat/history"
curl.exe "http://127.0.0.1:8000/api/v1/chat/<query_id>"
curl.exe -X POST "http://127.0.0.1:8000/api/v1/chat/<query_id>/feedback" `
  -H "Content-Type: application/json" `
  -d "{\"rating\":5,\"thumbs\":\"up\",\"comment\":\"useful\"}"
```

Agent run：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/agent/run" `
  -H "Content-Type: application/json" `
  -d "{\"query\":\"生成 Airflow task failure runbook\",\"workspace_slug\":\"public_tech\"}"
curl.exe "http://127.0.0.1:8000/api/v1/agent/runs/<run_id>/status"
curl.exe "http://127.0.0.1:8000/api/v1/agent/runs/<run_id>/trace"
```

## 12. Eval 与 Admin

Eval：

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/eval/count"
curl.exe -X POST "http://127.0.0.1:8000/api/v1/eval/run" `
  -H "Content-Type: application/json" `
  -d "{\"case_filter\":{},\"limit\":5}"
curl.exe "http://127.0.0.1:8000/api/v1/eval/results"
```

Admin：

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/admin/stats"
curl.exe "http://127.0.0.1:8000/api/v1/admin/index-status"
curl.exe "http://127.0.0.1:8000/api/v1/admin/bad-cases"
```

如果启用 `AUTH_ENABLED=true`，admin 端点需要：

```powershell
curl.exe -H "Authorization: Bearer <ADMIN_API_TOKEN>" "http://127.0.0.1:8000/api/v1/admin/stats"
```

## 13. 一键 API Smoke 与前端验收

脚本 smoke：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_api.ps1
```

Next.js 前端：

```powershell
Start-Process http://127.0.0.1:3000
```

前端验收重点：

- Chat 页面可以发起 JSON/SSE 问答，并展示 citation、工具结果和 trace 摘要。
- Documents 页面可以上传、查看状态、重试、删除或 purge。
- Traces 页面可以查看 query/run 的检索、rerank、工具调用和回答链路。
- Eval 页面可以查看 eval count、运行评估和结果列表。

## 14. 常见排障

### PowerShell 禁止运行脚本

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

或：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev_start.ps1
```

### 端口被占用

```powershell
netstat -ano | findstr ":8000"
netstat -ano | findstr ":3000"
netstat -ano | findstr ":15432"
```

换端口启动 app：

```powershell
.\scripts\dev_start.ps1 -ApiPort 8010
$env:DOCWISE_API_BASE_URL="http://127.0.0.1:8010/api/v1"
$env:DOCWISE_API_PROXY_TARGET="http://127.0.0.1:8010"
$env:NEXT_PUBLIC_DOCWISE_API_BASE_URL="/api/v1"
```

### Worker 不处理任务

```powershell
Test-NetConnection 127.0.0.1 -Port 6379
Get-Content logs\worker\docwise-worker.out.log -Tail 80
Get-Content logs\worker\docwise-worker.err.log -Tail 80
.\.venv\Scripts\python.exe -m arq src.tasks.worker.WorkerSettings
```

### Chat 没有 citations

先确认有 active chunks：

```powershell
curl.exe "http://127.0.0.1:8000/api/v1/admin/index-status"
```

如果 `active_chunks=0`，先完成文档入库。

### 彻底重置本地环境

仅开发环境执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev_stop.ps1
docker compose down
docker volume rm docwise_postgres_data
docker volume rm docwise_redis_data
docker volume rm docwise_minio_data
docker compose up -d postgres redis minio
.\.venv\Scripts\python.exe -m alembic -c alembic\alembic.ini upgrade head
.\.venv\Scripts\python.exe -m scripts.seed_demo
powershell -ExecutionPolicy Bypass -File .\scripts\dev_start.ps1
```

如果 volume 名称不同：

```powershell
docker volume ls | findstr docwise
```

## 15. 当前 Demo 场景

1. 文档入库：导入 `data/raw/airflow`，确认 document/job/chunk ready。
2. 通用技术问答：围绕 Airflow、FastAPI、Backstage demo 文档提问，确认 citation。
3. 项目/工作区问答：通过 workspace 参数限制检索范围。
4. 故障排查 Agent：触发 mock logs、service status、manifest 等工具，确认 trace 和 tool_calls。
5. Eval：运行小批量 eval，查看 metrics、bad case 和历史结果。

---

## 历史附录：原多 Agent 操控指南

以下内容来自旧版 `docs/GUIDE.md`，用于追溯早期多 Agent 并行开发流程。当前运行、调试和验收请以上文为准。

# DocWise 项目操控指南

DocWise 是一个多 Agent 并行开发的 Developer Knowledge Workflow 系统。本指南帮助你从零开始配置环境、启动各 Agent、协调合并，直到系统完整运行。

---

## 1. 前置准备

### 环境要求

| 工具 | 版本 | 用途 |
|------|------|------|
| Python | 3.12 | 后端运行时 |
| Docker + Docker Compose | 24.0+ / 2.20+ | 容器化服务 |
| Git | 2.40+ | 版本控制 + worktree |
| Node.js | 不需要 | — |

### API Key 准备

| 服务 | 环境变量 | 用途 |
|------|---------|------|
| DeepSeek API | `DEEPSEEK_API_KEY` | LLM 生成（路由、改写、回答） |
| Qwen/DashScope API | `QWEN_API_KEY` | Embedding + Rerank |
| Langfuse (可选) | `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` | 可观测性 |

---

## 2. 项目初始化

### 2.1 克隆并进入项目

```bash
cd d:/VSCodeWorkspace/DocWise
```

### 2.2 创建环境变量文件

Phase 1 完成后，Agent A 会生成 `.env.example`。复制并填入你的 API Key：

```bash
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY, QWEN_API_KEY 等
```

### 2.3 启动 Docker 服务

Phase 1 完成后：

```bash
make up          # 启动所有 8 个服务 (PostgreSQL, Redis, MinIO, 后端, Worker, Next.js 前端等)
make migrate     # 执行数据库迁移（创建 12 张表 + pgvector + zhparser）
make seed        # 初始化 5 个默认 workspace + MinIO bucket
```

验证：
```bash
curl http://localhost:8000/healthz    # 应返回 200
curl http://localhost:8000/readyz     # 应返回 200 (DB/Redis/MinIO 连通)
```

---

## 3. Phase 执行流程

### Phase 0: 契约确认（你现在在这里）

所有契约文件已生成并细化。在启动 Agent 之前：

1. 阅读 `docs/contracts/` 下的 9 个契约文件，确认无误
2. 阅读 `docs/CODING_STANDARDS.md`，了解编码规范
3. 阅读 `docs/FILE_OWNERSHIP.md`，了解文件所有权

### Phase 1: 基础架构（Agent A，串行）

**目标**: 从零搭建项目骨架，所有其他 Agent 依赖此产出。

**启动方式**: 将 `docs/agent-prompts/agent-a-foundation.md` 的完整内容作为 prompt 发送给一个 Claude Code 实例。

**预计耗时**: 8-10 小时

**完成标志**:
- `docker-compose up -d` 所有服务启动
- `make migrate` 12 张表创建成功
- `make seed` 5 个 workspace 创建成功
- `curl http://localhost:8000/healthz` 返回 200
- `python -c "from src.models import *; from src.schemas import *; print('OK')"` 通过

**完成后操作**:
```bash
# 确认所有文件已提交到 main
git status
git log --oneline -10
```

### Phase 2: 并行开发（Agent B/C/D/E，并行）

**目标**: 4 个 Agent 在独立分支上并行开发各自模块。

**启动方式**:

方式一：使用 Git Worktree（推荐）
```bash
# Linux/Mac
chmod +x scripts/setup_worktrees.sh
./scripts/setup_worktrees.sh

# Windows (PowerShell)
.\scripts\setup_worktrees.ps1
```

方式二：使用独立分支
```bash
git checkout -b feat/document-pipeline main    # Agent B
git checkout -b feat/retrieval-agent main      # Agent C
git checkout -b feat/api-frontend main         # Agent D
git checkout -b feat/quality-eval main         # Agent E
```

**启动各 Agent**:

为每个 Agent 打开一个独立的 Claude Code 实例，发送对应的 prompt 文件内容：

| Agent | Prompt 文件 | 分支 | 优先交付 |
|-------|------------|------|---------|
| Agent E | `docs/agent-prompts/agent-e-quality-eval.md` | feat/quality-eval | tracer 接口 (2h) + mock 数据 (4h) |
| Agent B | `docs/agent-prompts/agent-b-document-pipeline.md` | feat/document-pipeline | LLM client + embedder (2-4h) |
| Agent C | `docs/agent-prompts/agent-c-retrieval-agent.md` | feat/retrieval-agent | 等待 Agent B + E 优先交付 |
| Agent D | `docs/agent-prompts/agent-d-api-frontend.md` | feat/api-frontend | 等待 Agent C 完成 graph.py |

**关键依赖时序**:
```
Agent E (tracer) ──────┐
                       ├──→ Agent C (retrieval + agent) ──→ Agent D (API + frontend)
Agent B (LLM + embed) ─┘
```

**预计耗时**: 12-16 小时（并行）

### Phase 3: 集成合并（Agent A 协调）

**合并顺序**（严格按依赖关系）:

```bash
git checkout main

# 1. 合并 Agent E (tracer + mock + eval)
git merge feat/quality-eval --no-ff
# 解决冲突（如有），运行测试
python -c "from src.observability.tracer import write_trace_event; print('OK')"

# 2. 合并 Agent B (LLM + document + tasks)
git merge feat/document-pipeline --no-ff
pytest tests/unit/test_parsers.py tests/unit/test_chunker.py -v

# 3. 合并 Agent C (retrieval + agent)
git merge feat/retrieval-agent --no-ff
python -c "from src.agent.graph import build_agent_graph; print('OK')"
pytest tests/unit/test_hybrid_retrieval.py tests/unit/test_query_router.py -v

# 4. 合并 Agent D (API + frontend)
git merge feat/api-frontend --no-ff
pytest tests/integration/test_api_endpoints.py -v
```

### Phase 4: 端到端验证

```bash
# 完整测试
make test

# 入库文档
python scripts/ingest_docs.py --workspace public_tech --dir data/raw/airflow/

# 运行评估
make eval

# 启动前端
# 访问 http://localhost:3000
```

---

## 4. Agent 操控详细说明

### 4.1 发送 Prompt 给 Agent

每个 Agent 的 prompt 文件是自包含的完整指令。发送时：

1. 打开一个新的 Claude Code 会话
2. 确保工作目录在对应的 worktree 或分支
3. 将 prompt 文件的**完整内容**粘贴发送
4. Agent 会自动开始执行任务

### 4.2 Agent 执行过程中的干预

如果 Agent 遇到 Stop Condition：
- Agent 会停止并报告问题
- 你需要协调对应的 Owner Agent 解决问题
- 解决后告诉 Agent "问题已解决，请继续"

如果 Agent 偏离契约：
- 检查 `docs/contracts/` 中的对应文件
- 指出具体偏离点，要求 Agent 修正

### 4.3 验证 Agent 产出

每个 Agent prompt 底部都有 "Test Requirements" 部分。Agent 完成后：

1. 运行对应的测试命令
2. 检查 "Final Output Format" 中列出的交付物
3. 确认与契约文件的一致性

---

## 5. 契约文件使用说明

### 5.1 契约文件列表

| 文件 | 定义者 | 消费者 | 核心内容 |
|------|--------|--------|---------|
| `orm_models.pyi` | Agent A | 所有 | 12 张表字段定义 |
| `schemas.pyi` | Agent A | Agent D | API 请求/响应模型 |
| `agent_state.pyi` | Agent C | Agent C/D/E | AgentState + 阈值 + 异常 |
| `tracer_interface.pyi` | Agent E | Agent C | Trace 写入接口 |
| `llm_client_interface.pyi` | Agent B | Agent C | LLM 调用接口 |
| `embedder_interface.pyi` | Agent B | Agent C | 向量化接口 |
| `tool_schemas.pyi` | Agent C | Agent E | 工具 I/O + mock 格式 |
| `sse_events.pyi` | Agent C+D | Agent D | SSE 事件类型 + 映射 |
| `eval_case_format.md` | Agent E | Agent E | Eval Case JSONL 格式 |

### 5.2 契约修改规则

- **Phase 0 冻结后，契约文件不得随意修改**
- 如果必须修改，需要：
  1. 定义者 Agent 提出修改
  2. 所有消费者 Agent 确认兼容
  3. 更新契约文件
  4. 通知所有受影响的 Agent

---

## 6. 常见问题排查

### Docker 服务启动失败

```bash
docker-compose logs postgres    # 检查 PostgreSQL 日志
docker-compose logs redis       # 检查 Redis 日志
docker-compose logs minio       # 检查 MinIO 日志
```

### Migration 失败

```bash
# 检查 PostgreSQL 是否支持 pgvector
docker-compose exec postgres psql -U docwise -c "SELECT * FROM pg_extension WHERE extname='vector';"

# 重置数据库（开发环境）
make down
docker volume rm docwise_postgres_data
make up && make migrate && make seed
```

### Agent 报告契约不一致

1. 确认 Agent 读取的是最新的契约文件
2. 检查 `docs/contracts/` 中对应文件的版本
3. 如果确实不一致，按 5.2 节流程修改

### 合并冲突

最常见的冲突位置：
- `src/__init__.py` — 各 Agent 添加不同的导出
- `src/api/app.py` — Agent A 和 Agent D 都可能修改

解决方式：
- `__init__.py` 冲突：合并所有导出
- `app.py` 冲突：以 Agent A 的 Phase 2 版本为基准，添加 Agent D 的路由

### Eval 指标不达标

```bash
# 查看 bad cases
make eval-report

# 常见原因:
# 1. retrieval_miss → 检查 chunk 是否正确入库，embedding 维度是否匹配
# 2. wrong_workspace → 检查 query_router 的路由规则
# 3. bad_citation → 检查 citation_verifier 的正则匹配
# 4. latency_high → 检查 API 超时设置，考虑增加 reranker 降级
```

---

## 7. 快速参考

### Makefile 常用命令

```bash
make up              # 启动所有 Docker 服务
make down            # 停止所有服务
make migrate         # 执行数据库迁移
make seed            # 初始化种子数据
make test            # 运行全部测试
make eval            # 运行评估
make lint            # 代码检查 (ruff)
make format          # 代码格式化 (ruff format)
```

### 项目 URL

| 服务 | URL | 说明 |
|------|-----|------|
| FastAPI 后端 | http://localhost:8000 | API 服务 |
| API 文档 | http://localhost:8000/docs | Swagger UI |
| Next.js 前端 | http://localhost:3000 | 用户界面 |
| MinIO Console | http://localhost:9001 | 对象存储管理 |
| Langfuse (可选) | http://localhost:3000 | 可观测性面板 |

### 5 个 Demo 场景

完成所有 Phase 后，验证以下场景：

1. **文档上传**: Documents 页面上传 PDF → 查看 job 进度 → status=ready
2. **通用技术问答**: Chat 页面选择 public_tech → 提问 "什么是 Kubernetes Pod?" → 流式回答 + 引用
3. **项目问答**: Chat 页面选择 project_airflow → 提问 "Airflow DAG 怎么配置?" → 项目文档引用
4. **故障排查**: Chat 页面提问 "Airflow scheduler 挂了怎么办?" → 工具调用 + 日志分析 + Runbook
5. **评估面板**: Eval 页面运行评估 → 查看 7 个指标 → 查看 bad cases → 跳转 trace
