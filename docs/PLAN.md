# DocWise PLAN

本文是 DocWise 当前权威的架构计划、恢复状态和后续任务路线图。它已经把旧 `docs/PLAN.md` 的系统蓝图与 `docs/TASK.md` 的多 Agent 工作包拆解合并为一个面向当前仓库实际状态的计划。旧的 15 天实施计划和多 Agent 任务拆解保留在本文末尾历史部分，仅用于追溯，不再作为当前事实来源。

## 1. 项目目标

DocWise 的目标是一个企业级开发者知识工作流 Agent：

- 面向开发者、SRE、运维工程师，解决技术文档、项目资料、SOP、日志和服务状态分散导致的排障低效问题。
- 以 RAG 为基础，结合路由、workspace 隔离、工具调用、trace 和 eval，提供可验证、可追溯的技术问答和故障排查。
- 保留真实企业 MVP 边界：PostgreSQL/pgvector、Redis、MinIO、独立 worker、结构化 trace、评估体系和可恢复本地部署。

## 2. 当前权威运行架构

| 模块 | 当前实现 |
| --- | --- |
| API | FastAPI，`src/api/app.py` 注册 chat、agent、documents、eval、admin 路由 |
| Worker | arq worker，`src/tasks/worker.py` 暴露 ingest、reindex、eval job |
| DB | PostgreSQL + pgvector + tsvector，SQLAlchemy async，Alembic 当前 head 为 `004` |
| Cache/Queue | Redis，用于 arq、embedding cache 和入库锁 |
| Object Storage | MinIO，默认 bucket `docwise-documents`，seed 和 ingestion 会确保 bucket 存在 |
| LLM | DeepSeek-compatible chat wrapper，区分 fast/pro 模型 |
| Embedding/Rerank | DashScope/Qwen `text-embedding-v4`，维度 2048；`qwen3-rerank`，失败可降级 |
| Agent | LangGraph StateGraph，节点在 `src/agent/nodes/`，工具在 `src/agent/tools/` |
| Retrieval | pgvector vector search + tsvector keyword search + RRF + rerank |
| Observability | 本地 DB trace first，Langfuse optional |
| Frontend | Streamlit，多页 app 位于 `src/frontend/` |

## 3. 当前目录与职责

| 路径 | 作用 |
| --- | --- |
| `src/config/` | settings、secret redaction |
| `src/common/` | 跨模块异常和 MinIO helper |
| `src/db/` | async SQLAlchemy session 与 Redis client |
| `src/models/` | ORM 模型和枚举 |
| `src/schemas/` | API Pydantic schema |
| `src/document/` | parser、chunker、embedding、ingestion orchestration |
| `src/llm/` | provider routing、chat wrapper |
| `src/retrieval/` | vector、keyword、hybrid、rerank、retriever |
| `src/agent/` | LangGraph state、nodes、tools、prompts |
| `src/tasks/` | arq job entrypoints 和 job status helper |
| `src/observability/` | trace writer、eval runner、metrics、bad case |
| `src/api/` | FastAPI app、dependencies、routers |
| `src/frontend/` | Streamlit app、pages、components、API client |
| `scripts/` | seed、ingest、download、validation、smoke、dev start/stop |
| `data/mock/` | 工具 mock fixture，必须保留 |
| `data/eval/` | eval fixture，必须保留 |
| `data/raw/` | 可复现 demo 输入，由脚本生成 |
| `docs/contracts/` | 接口契约和历史冻结点 |

## 4. 核心架构决策

| 决策 | 当前选择 | 原因 |
| --- | --- | --- |
| Python | 3.11 | 与当前依赖和本地 `.venv` 对齐 |
| API | FastAPI | async 支持成熟，测试方便 |
| DB | PostgreSQL + pgvector | 让业务数据、chunk、trace、eval 与向量检索保持同库事务边界 |
| 向量库扩展 | 保留 `VectorStore` 抽象 | 当前不引入 Milvus，后续可迁移 |
| 队列 | arq + Redis | async-native，轻量，适合当前 Python async 栈 |
| 对象存储 | MinIO | 保留 S3-compatible 企业部署边界 |
| LLM | DeepSeek-compatible chat | 成本和部署摩擦适合 P1 |
| Embedding/Rerank | Qwen API | 当前验证维度为 2048，质量和接入成本平衡 |
| Trace | local DB first + Langfuse optional | 本地可跑通，可选外部观测 |
| 前端 | Streamlit | 快速管理台和演示，后续可替换 |

## 5. 数据与运行契约

- `.env.local.example` 用于 Windows `.venv` 跑 API/worker/frontend，基础设施地址使用 `localhost`。
- `.env.docker.example` 用于 Docker app services，服务地址使用 Compose service name。
- `.env` 可包含真实 key，必须保持 ignored，严禁打印密钥。
- API、SSE、JSONB、schema 字段统一 `snake_case`。
- `DocumentChunk` 是 citation、trace 和 eval 的最小证据单元。
- embedding 维度固定为 2048；更换 provider 或维度需要 DB migration 和 reindex。
- `data/mock/` 与 `data/eval/` 是核心 fixture，不应删除。
- `logs/`、`.run/`、cache、bytecode 都是本地运行产物，不入 Git。

## 6. Agent 工作流

当前 LangGraph 工作流保留以下主线：

```text
START
  -> input_normalizer
  -> query_router
  -> scope_selector
  -> query_rewriter
  -> hybrid_retriever
  -> reranker
  -> evidence_validator
      -> answer_generator
      -> 或 tool_planner -> tool_executor -> evidence_validator
  -> citation_verifier
  -> refusal_checker
  -> END
```

支持的 route：

| Route | 语义 |
| --- | --- |
| `tech_general` | 通用技术文档问答 |
| `project_specific` | 项目/工作区限定问答 |
| `troubleshooting` | 故障排查，允许工具补证据 |
| `runbook_generation` | 生成 runbook 草稿 |
| `out_of_scope` | 超出范围，倾向拒答 |

工具边界：

- `search_docs`
- `query_project_manifest`
- `query_mock_logs`
- `query_service_status`
- `generate_runbook_draft`

工具输出、retrieval results、final citations 和 trace 都是产品表面，不能当作内部临时字段随意改名。

## 7. API Surface

| 分组 | 端点 |
| --- | --- |
| Health | `GET /healthz`, `GET /readyz` |
| Documents | `POST /api/v1/documents/upload`, `GET /api/v1/documents`, `GET /api/v1/documents/{document_id}`, `GET /api/v1/documents/jobs/{job_id}`, `POST /api/v1/documents/{document_id}/retry`, `DELETE /record`, `DELETE /purge` |
| Chat | `POST /api/v1/chat`, `POST /api/v1/chat/stream`, `GET /api/v1/chat/history`, `GET /api/v1/chat/{query_id}`, `POST /api/v1/chat/{query_id}/feedback` |
| Agent | `POST /api/v1/agent/run`, `GET /api/v1/agent/runs/{run_id}/status`, `GET /api/v1/agent/runs/{run_id}/trace` |
| Eval | `GET /api/v1/eval/count`, `POST /api/v1/eval/run`, `GET /api/v1/eval/results` |
| Admin | `GET /api/v1/admin/stats`, `GET /api/v1/admin/index-status`, `GET /api/v1/admin/bad-cases` |

## 8. 当前恢复状态

已恢复或校准：

- `src.document.chunker`
- chunk、parser、ingestion、embedder、retrieval、agent、trace、eval、API、frontend 的当前可运行路径
- `scripts/dev_start.ps1` / `scripts/dev_stop.ps1`
- `.env.local.example` / `.env.docker.example`
- MinIO bucket 初始化：`scripts.seed_demo` 和 ingestion 上传前都会确保 `docwise-documents`
- Windows 本地运行指南已并入 `docs/GUIDE.md`

当前验证基线：

```powershell
.\.venv\Scripts\python.exe -m scripts.validate_mock_data
.\.venv\Scripts\python.exe -m scripts.validate_eval_cases
.\.venv\Scripts\python.exe -m ruff check src tests scripts alembic
.\.venv\Scripts\python.exe -m pytest -q
```

观察结果：

```text
validate_mock_data: ALL CHECKS PASSED
validate_eval_cases: ALL CHECKS PASSED (20 retrieval + 30 qa)
ruff: All checks passed!
pytest: 121 passed
```

真实 smoke 已验证过的链路：

- Docker `postgres`、`redis`、`minio` healthy
- Alembic 到 `004 (head)`
- `scripts.seed_demo` 完成
- `scripts.ingest_docs --workspace public_tech --dir data\raw\airflow` 两份 demo 文档到 `ready`
- `--enqueue` 对已有文档返回 succeeded job
- Qwen embedding 返回 2048 维
- Qwen rerank 非 fallback
- DeepSeek-compatible chat 返回预期 smoke 文本

## 9. 当前任务路线图

### P0 保持可运行

- 任意改动后至少运行相关单元/集成测试。
- 涉及 fixture、schema、routes、eval 时运行完整质量门。
- 涉及 ingestion、retrieval、chat、eval 时优先补真实 smoke，而不是只看类型或单测。
- 保持 `.env`、日志、上传文档、模型响应中的敏感信息脱敏。

### P1 硬化

- 将目前的 smoke 步骤沉淀成更稳定的自动化脚本和可读报告。
- 扩展 eval case 覆盖项目问答、故障排查、拒答、runbook generation。
- 强化 Streamlit 页面错误展示和 job polling。
- 补充 API 认证开启后的端到端验证。
- 梳理 `docs/contracts/` 与当前实现的差异，保留仍需要冻结的接口。

### P2 扩展

- 根据吞吐需求评估独立向量库，例如 Milvus，但保留 Postgres 作为系统事实源。
- 引入更完整的权限模型或组织/workspace RBAC。
- 将 Langfuse 或 OpenTelemetry 从 optional 提升为可部署观测方案。
- 将 Streamlit 管理台替换或补充为更完整的前端。

## 10. 风险与降级

| 风险 | 当前策略 |
| --- | --- |
| Qwen embedding/rerank API 不可用 | embedding 入库失败需重试；rerank 可 fallback 到 RRF |
| DeepSeek chat API 不可用 | chat/agent smoke 会失败，应记录脱敏错误类型 |
| MinIO fresh volume 缺 bucket | seed 和 ingestion 自动确保 bucket |
| Postgres volume 密码漂移 | 开发环境重置 volume 或对齐 `.env` |
| worker 未启动 | 同步 ingest 可先跑通，异步 job 需要 arq worker |
| `data/raw/` 被清理 | `scripts.seed_demo` / `scripts.download_docs` 可复现生成 |

## 11. 文档权威关系

| 需求 | 当前权威文件 |
| --- | --- |
| 运行、调试、全功能验证 | `docs/GUIDE.md` |
| 架构、任务、路线图 | `docs/PLAN.md` |
| 编码规范、文件边界、Agent 协作规则 | `docs/AGENT.md` |
| 接口契约 | `docs/contracts/` |
| 恢复记录 | `docs/RECOVERY_STATUS.md` |
| PowerShell API smoke 细节 | `docs/POWERSHELL_SMOKE_TEST.md` |

## 12. 实施工作包与当前状态

这一节吸收旧 `docs/TASK.md` 的工作包拆解，但按当前仓库状态重新归并。后续继续开发时，以这里的责任域和验证门为准，而不是旧的 Agent prompt 原文。

| 工作包 | 当前主要路径 | 当前状态 | 下一步关注 |
| --- | --- | --- | --- |
| WP-01 Infra/Foundation | `pyproject.toml`, Dockerfile, Compose, Alembic, `src/config/`, `src/db/`, `src/models/`, `src/schemas/` | 已恢复到可运行，本地 infra health、Alembic head、seed 基线可用 | 保持 env 模板、migration、healthcheck 和 docs 同步 |
| WP-02 LLM/Document/Tasks | `src/llm/`, `src/document/`, `src/tasks/`, `scripts/ingest_docs.py`, `data/raw/` | chunker、ingestion、MinIO bucket、embedding、worker 路径已恢复；Airflow demo 入库 ready | 强化失败重试、job reporting、更多真实文档入库 smoke |
| WP-03 Retrieval/Agent | `src/retrieval/`, `src/agent/` | hybrid retrieval、rerank fallback、LangGraph route/tool/citation/refusal 主链路存在 | 扩充端到端 agent 场景和 route/tool contract tests |
| WP-04 API/Frontend | `src/api/`, `src/frontend/`, `scripts/smoke_api.ps1` | FastAPI 路由和 Streamlit 管理台存在，dev_start/dev_stop 管理本地进程 | 强化 Streamlit job polling、错误展示、auth-enabled smoke |
| WP-05 Observability/Eval/Data | `src/observability/`, `data/mock/`, `data/eval/`, validation scripts | mock/eval fixture gate 通过，eval cases 为 20 retrieval + 30 qa | 扩展 eval 覆盖故障排查、runbook、拒答和 bad-case 分析 |
| Docs/Contracts | `docs/`, `docs/contracts/` | GUIDE/PLAN/AGENT 已完成当前化合并 | 后续改动必须同步权威文档，旧文档只作历史 |

### 合并与验证顺序

当前项目已经从早期并行开发阶段进入恢复后的单仓收敛阶段。后续变更建议按风险顺序合并：

1. Infra/schema/env 变更先合并，并立即运行 Alembic、seed、fixture validation。
2. Document/LLM/task 变更合并后，运行 chunk/parser/ingestion 测试和至少一条真实入库 smoke。
3. Retrieval/Agent 变更合并后，运行 route/retrieval/agent 相关测试，并用已入库 demo 文档做 chat smoke。
4. API/Frontend 变更合并后，运行 API integration tests、`smoke_api.ps1` 和前端手动检查。
5. Eval/observability 变更合并后，运行 fixture validators、eval tests 和小批量 eval job。

### 当前验收清单

- [x] Docker `postgres` / `redis` / `minio` healthy。
- [x] Alembic 当前版本为 `004 (head)`。
- [x] `scripts.seed_demo` 成功并创建/确认 MinIO bucket。
- [x] `data/mock/` 与 `data/eval/` validation 通过。
- [x] `ruff check src tests scripts alembic` 通过。
- [x] `pytest -q` 当前为 `121 passed`。
- [x] `scripts.ingest_docs --workspace public_tech --dir data\raw\airflow` 同步入库到 ready。
- [x] `scripts.ingest_docs --workspace public_tech --dir data\raw\airflow --enqueue` 返回已有 succeeded job。
- [ ] API/worker/frontend 长时间运行稳定性仍需更长 session smoke。
- [ ] Auth-enabled admin smoke 仍需专门覆盖。
- [ ] 大文档、多格式、多 workspace 批量 reindex 仍需扩展验证。

---

## 历史附录：原细粒度实施规划

以下内容来自旧版 `docs/PLAN.md`，用于追溯早期设计过程。当前架构与路线图以上文为准。

# DocWise — Developer Knowledge Workflow Agent 细粒度实施规划

---

## 1. 项目目录结构

```
DocWise/
├── README.md
├── .gitignore
├── .env.example
├── pyproject.toml
├── Makefile
├── docker-compose.yml
├── docker-compose.override.yml
├── Dockerfile
├── Dockerfile.streamlit
│
├── alembic/
│   ├── alembic.ini
│   ├── env.py
│   └── versions/
│       └── 001_initial_schema.py
│
├── scripts/
│   ├── seed_workspaces.py
│   ├── ingest_docs.py
│   ├── download_docs.py
│   └── generate_mock_data.py
│
├── data/
│   ├── raw/
│   │   ├── backstage/
│   │   ├── airflow/
│   │   ├── fastapi-docs/
│   │   └── enterprise-sops/
│   ├── processed/
│   ├── mock/                        # mock logs, service status JSON fixtures
│   └── eval/
│       ├── qa_pairs.jsonl
│       └── retrieval_golden.jsonl
│
├── src/
│   ├── __init__.py
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py              # Pydantic Settings, 所有环境变量
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py                  # DeclarativeBase, 公共 mixin
│   │   ├── workspace.py
│   │   ├── document.py              # Document + DocumentChunk
│   │   ├── query.py                 # Query + RetrievalResult
│   │   ├── agent.py                 # AgentRun + ToolCall
│   │   ├── feedback.py
│   │   └── eval.py                  # EvalCase + EvalResult
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── document.py
│   │   ├── chat.py
│   │   ├── agent.py
│   │   ├── eval.py
│   │   ├── feedback.py
│   │   └── admin.py
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── session.py               # async engine + sessionmaker + get_db
│   │   └── redis.py                 # Redis 连接池 + get_redis
│   │
│   ├── document/
│   │   ├── __init__.py
│   │   ├── parser.py                # 统一解析接口 + 工厂
│   │   ├── pdf_parser.py            # PyMuPDF
│   │   ├── docx_parser.py           # python-docx
│   │   ├── markdown_parser.py       # mistune
│   │   ├── chunker.py               # RecursiveCharacterTextSplitter
│   │   ├── embedder.py              # OpenAI-compatible embedding
│   │   └── ingestion.py             # 编排: parse → chunk → embed → store
│   │
│   ├── retrieval/
│   │   ├── __init__.py
│   │   ├── vector_search.py         # pgvector cosine search
│   │   ├── keyword_search.py        # PostgreSQL tsvector/tsquery
│   │   ├── hybrid.py                # RRF 融合
│   │   ├── reranker.py              # bge-reranker / Jina / Cohere
│   │   ├── metadata_filter.py       # workspace + doc_type 过滤
│   │   └── retriever.py             # UnifiedRetriever 统一接口
│   │
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── state.py                 # AgentState TypedDict
│   │   ├── graph.py                 # LangGraph 主图构建
│   │   ├── nodes/
│   │   │   ├── __init__.py
│   │   │   ├── input_normalizer.py
│   │   │   ├── query_router.py
│   │   │   ├── scope_selector.py
│   │   │   ├── query_rewriter.py
│   │   │   ├── hybrid_retriever.py
│   │   │   ├── reranker.py
│   │   │   ├── evidence_validator.py
│   │   │   ├── tool_planner.py
│   │   │   ├── tool_executor.py
│   │   │   ├── answer_generator.py
│   │   │   ├── citation_verifier.py
│   │   │   └── refusal_checker.py
│   │   ├── tools/
│   │   │   ├── __init__.py
│   │   │   ├── search_docs.py
│   │   │   ├── query_project_manifest.py
│   │   │   ├── query_mock_logs.py
│   │   │   ├── query_service_status.py
│   │   │   └── generate_runbook_draft.py
│   │   └── prompts/
│   │       ├── __init__.py
│   │       ├── router.py
│   │       ├── rewriter.py
│   │       ├── generator.py
│   │       ├── refusal.py
│   │       └── tool_planner.py
│   │
│   ├── observability/
│   │   ├── __init__.py
│   │   ├── tracer.py                # Langfuse 集成
│   │   ├── evaluator.py             # 批量评估 runner
│   │   ├── metrics.py               # hit_rate, MRR, NDCG, faithfulness, citation_accuracy
│   │   └── bad_case.py              # bad case 检测与存储
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── app.py                   # FastAPI app factory + lifespan + middleware
│   │   ├── deps.py                  # 共享依赖
│   │   └── routers/
│   │       ├── __init__.py
│   │       ├── documents.py
│   │       ├── chat.py
│   │       ├── agent.py
│   │       ├── eval.py
│   │       └── admin.py
│   │
│   └── frontend/
│       ├── app.py                   # Streamlit 多页入口
│       ├── pages/
│       │   ├── 1_chat.py
│       │   ├── 2_documents.py
│       │   ├── 3_traces.py
│       │   └── 4_eval.py
│       ├── components/
│       │   ├── chat_message.py
│       │   ├── document_uploader.py
│       │   ├── trace_viewer.py
│       │   └── eval_chart.py
│       └── api_client.py            # 后端 API HTTP 客户端
│
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── unit/
    │   ├── test_parsers.py
    │   ├── test_chunker.py
    │   ├── test_hybrid_retrieval.py
    │   └── test_query_router.py
    ├── integration/
    │   ├── test_ingestion_pipeline.py
    │   ├── test_retrieval_pipeline.py
    │   └── test_api_endpoints.py
    └── eval/
        └── test_eval_runner.py
```

---

## 2. 技术栈与依赖

```toml
# pyproject.toml 核心依赖
[project]
name = "docwise"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    # Web 框架
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "python-multipart>=0.0.9",

    # 数据库
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "pgvector>=0.3",

    # Redis
    "redis>=5.0",

    # 对象存储
    "minio>=7.2",

    # LLM & Agent
    "langchain>=0.3",
    "langchain-openai>=0.2",
    "langgraph>=0.2",
    "langfuse>=2.0",

    # 文档解析
    "pymupdf>=1.24",
    "python-docx>=1.1",
    "mistune>=3.0",

    # Embedding & Rerank
    "tiktoken>=0.7",
    "httpx>=0.27",

    # 工具
    "pydantic>=2.0",
    "pydantic-settings>=2.0",

    # 前端
    "streamlit>=1.38",
    "plotly>=5.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "ruff>=0.5"]
```

---

## 3. Docker Compose 服务架构

| 服务 | 镜像 | 端口 | 用途 |
|------|------|------|------|
| postgres | pgvector/pgvector:pg16 | 5432 | 业务数据 + 向量索引 |
| redis | redis:7-alpine | 6379 | 缓存 + 任务状态 |
| minio | minio/minio:latest | 9000/9001 | 文档对象存储 |
| langfuse | langfuse/langfuse:2 | 3000 | 可观测平台 |
| langfuse-db | postgres:16-alpine | 5433 | Langfuse 专用数据库 |
| backend | 自建 Dockerfile | 8000 | FastAPI 后端 |
| frontend | 自建 Dockerfile.streamlit | 8501 | Streamlit 前端 |

---

## 4. 数据库核心表设计

共 10 张表，分为 4 组：

**知识库组**
- `workspaces` — 知识空间 (public_tech / project_pack)
- `documents` — 文档元数据 (状态: pending → processing → ready → error)
- `document_chunks` — 文档切片 + embedding 向量 + tsvector 全文索引

**问答组**
- `queries` — 用户查询 + 路由结果 + 回答 + 置信度
- `retrieval_results` — 每次查询的召回结果 + 各阶段分数

**Agent 组**
- `agent_runs` — Agent 运行记录 + 状态 + Langfuse trace_id
- `tool_calls` — 工具调用记录 (输入/输出/耗时/状态)

**评估组**
- `feedback` — 用户反馈 (thumbs/rating/correction)
- `eval_cases` — 评估用例 (问题 + 期望答案 + 期望 chunk)
- `eval_results` — 评估结果 (各项指标分数)

关键索引：
- `document_chunks.embedding` — IVFFlat 向量索引 (cosine)
- `document_chunks.content_tsv` — GIN 全文索引
- `document_chunks.workspace_id` — B-tree 索引用于 workspace 过滤

---

## 5. Agent 工作流设计 (LangGraph)

### 5.1 AgentState 定义

```python
class AgentState(TypedDict):
    original_query: str
    rewritten_query: str
    route: str                    # tech_general | project_specific | troubleshooting
    workspace_ids: list[str]
    retrieved_chunks: list[dict]
    reranked_chunks: list[dict]
    evidence_sufficient: bool
    tools_to_call: list[str]
    tool_results: list[dict]
    answer: str
    citations: list[dict]
    confidence_score: float
    refused: bool
    trace_id: str
    error: str | None
```

### 5.2 图结构与条件分支

```
START
  → input_normalizer
  → query_router
  → scope_selector
  → query_rewriter
  → hybrid_retriever
  → reranker
  → evidence_validator
      ├─ evidence_sufficient=True ──→ answer_generator
      └─ evidence_sufficient=False AND route=troubleshooting ──→ tool_planner
          → tool_executor
              ├─ 需要更多证据 ──→ evidence_validator (循环，最多 2 次)
              └─ 证据充分 ──→ answer_generator
  → answer_generator
  → citation_verifier
  → refusal_checker
  → END
```

### 5.3 各节点职责

| 节点 | 输入 | 输出 | 实现方式 |
|------|------|------|----------|
| input_normalizer | 原始 query | 清洗后 query | 规则 (strip, 编码归一化) |
| query_router | query | route 分类 | LLM few-shot 分类 |
| scope_selector | route | workspace_ids | 规则映射 |
| query_rewriter | query + route | rewritten_query | LLM 改写 |
| hybrid_retriever | rewritten_query + workspace_ids | retrieved_chunks | 调用 UnifiedRetriever |
| reranker | query + chunks | reranked_chunks | Reranker API |
| evidence_validator | reranked_chunks | evidence_sufficient | 分数阈值判断 |
| tool_planner | query + evidence + route | tools_to_call | LLM 决策 |
| tool_executor | tools_to_call | tool_results | 执行工具函数 |
| answer_generator | query + chunks + tool_results | answer + citations | LLM 生成 |
| citation_verifier | answer + citations + chunks | 验证后 citations | 规则校验 |
| refusal_checker | confidence_score | refused flag | 阈值判断 |

### 5.4 工具定义

| 工具 | 参数 | 返回 | 数据来源 |
|------|------|------|----------|
| search_docs | query, workspace | 相关文档片段 | 知识库检索 |
| query_project_manifest | project_name | 服务列表、依赖、SLA | JSON fixture |
| query_mock_logs | service_name, time_range, level | 模拟日志条目 | JSON fixture |
| query_service_status | service_name | 健康状态、CPU/内存/错误率 | JSON fixture |
| generate_runbook_draft | incident_type, service_name | Runbook 草稿 | LLM 生成 |

---

## 6. 检索策略设计

```
用户 query
  → 提取关键词 / 错误码 / 项目名
  → 向量召回 top_k=20 (pgvector cosine)
  → 关键词召回 top_k=20 (tsvector ts_rank)
  → workspace_id + doc_type metadata 过滤
  → RRF 融合去重 (k=60)
  → Rerank top_k=5
  → 送入 answer_generator
```

RRF 公式: `score(d) = Σ 1/(k + rank_i(d))`，k=60 是经验值，平衡向量和关键词两路结果。

---

## 7. API 端点设计

### 文档管理
| 方法 | 路径 | 功能 |
|------|------|------|
| POST | /api/v1/documents/upload | 上传文档 (multipart) |
| GET | /api/v1/documents | 文档列表 (分页 + workspace 过滤) |
| GET | /api/v1/documents/{id} | 文档详情 + chunk 统计 |
| POST | /api/v1/documents/{id}/reindex | 重新索引 |
| DELETE | /api/v1/documents/{id} | 删除文档及其 chunks |

### 问答
| 方法 | 路径 | 功能 |
|------|------|------|
| POST | /api/v1/chat | 提交问题，返回带引用回答 |
| GET | /api/v1/chat/{query_id} | 查询历史记录 |
| POST | /api/v1/chat/{query_id}/feedback | 提交反馈 |

### Agent
| 方法 | 路径 | 功能 |
|------|------|------|
| POST | /api/v1/agent/run | 触发 Agent 工作流 |
| GET | /api/v1/agent/runs/{run_id} | 查询运行状态 |
| GET | /api/v1/agent/runs/{run_id}/trace | 查询完整 trace |

### 评估
| 方法 | 路径 | 功能 |
|------|------|------|
| POST | /api/v1/eval/run | 运行评估集 |
| GET | /api/v1/eval/results | 评估结果列表 |
| GET | /api/v1/eval/results/{run_id} | 单次评估详情 |

### 管理
| 方法 | 路径 | 功能 |
|------|------|------|
| GET | /api/v1/admin/stats | 系统统计 (文档数/chunk数/查询数) |
| GET | /api/v1/admin/bad-cases | Bad case 列表 |
| GET | /api/v1/admin/index-status | 索引状态 |

---

## 8. 前端页面设计 (Streamlit)

**页面 1: Chat 对话页**
- 左侧: workspace 选择器 (下拉)
- 中间: 对话流 (用户消息 + Agent 回答 + 引用卡片 + 工具调用展示)
- 右侧: trace 摘要 (路由结果、召回数、耗时)
- 底部: 反馈按钮

**页面 2: 文档管理页**
- 文件上传区 (支持多文件)
- 文档列表表格 (workspace / 类型 / 状态 / chunk数 / 操作)
- 状态筛选 + workspace 筛选

**页面 3: Trace 观测页**
- 查询历史列表
- 单条 trace 详情: router → retrieval → rerank → tool_calls → generation
- 各阶段耗时瀑布图
- 召回 chunk 详情 + 分数

**页面 4: Eval 评估页**
- 运行评估按钮
- 指标仪表盘: hit_rate, MRR, citation_accuracy, answer_correctness, refusal_accuracy
- Bad case 表格 (问题 / 期望 / 实际 / 差异原因)

---

## 9. 每日实施计划 (15 天)

---

### Day 1: 项目初始化 + 基础设施搭建

**目标**: 项目骨架就绪，所有基础服务可启动

| 任务 | 预计耗时 | 产出文件 |
|------|----------|----------|
| 初始化 git 仓库 + .gitignore | 15min | .gitignore |
| 创建 pyproject.toml + 安装依赖 | 30min | pyproject.toml |
| 编写 docker-compose.yml (7 个服务) | 1.5h | docker-compose.yml, docker-compose.override.yml |
| 编写 Dockerfile + Dockerfile.streamlit | 45min | Dockerfile, Dockerfile.streamlit |
| 编写 .env.example | 15min | .env.example |
| 编写 Makefile (up/down/migrate/seed/test) | 30min | Makefile |
| 创建 src/ 目录结构 + 所有 __init__.py | 30min | src/**/__init__.py |
| 实现 src/config/settings.py (Pydantic Settings) | 45min | src/config/settings.py |
| 实现 src/db/session.py (async engine + get_db) | 45min | src/db/session.py |
| 实现 src/db/redis.py (连接池 + get_redis) | 30min | src/db/redis.py |
| docker-compose up 验证所有服务启动 | 30min | — |

**验证**: `docker-compose up -d` 后 postgres/redis/minio/langfuse 全部 healthy

---

### Day 2: 数据库模型 + 迁移 + 数据准备

**目标**: 数据库 schema 就绪，知识源文档下载完成

| 任务 | 预计耗时 | 产出文件 |
|------|----------|----------|
| 实现 src/models/base.py (Base + TimestampMixin) | 30min | src/models/base.py |
| 实现所有 ORM 模型 (workspace/document/chunk/query/agent/feedback/eval) | 2h | src/models/*.py |
| 配置 Alembic + 编写初始迁移 | 1h | alembic/, alembic/versions/001_initial_schema.py |
| 运行迁移，验证表结构 + pgvector 扩展 + 索引 | 30min | — |
| 编写 scripts/seed_workspaces.py (创建默认 workspace) | 30min | scripts/seed_workspaces.py |
| 编写 scripts/download_docs.py (从 GitHub 下载 Backstage/Airflow/FastAPI docs) | 1h | scripts/download_docs.py |
| 下载公开技术文档 PDF (PostgreSQL 手册等) | 30min | data/raw/ |
| 编写 5-10 份模拟企业 SOP/Runbook DOCX | 1.5h | data/raw/enterprise-sops/*.docx |
| 实现 src/schemas/ 基础 Pydantic 模型 | 1h | src/schemas/*.py |

**验证**: `alembic upgrade head` 成功，`psql` 可查看所有表，data/raw/ 下有文档文件

---

### Day 3: 文档解析模块

**目标**: PDF/DOCX/Markdown 三种格式解析完成

| 任务 | 预计耗时 | 产出文件 |
|------|----------|----------|
| 实现 parser.py (ParsedDocument 模型 + 工厂函数) | 30min | src/document/parser.py |
| 实现 pdf_parser.py (PyMuPDF: 逐页提取 + 标题检测 + 表格) | 1.5h | src/document/pdf_parser.py |
| 实现 docx_parser.py (python-docx: 段落 + 标题 + 表格) | 1h | src/document/docx_parser.py |
| 实现 markdown_parser.py (mistune: 标题层级 + 代码块 + 列表) | 1h | src/document/markdown_parser.py |
| 实现 chunker.py (RecursiveCharacterTextSplitter + metadata 保留) | 1.5h | src/document/chunker.py |
| 编写 tests/unit/test_parsers.py | 1h | tests/unit/test_parsers.py |
| 编写 tests/unit/test_chunker.py | 45min | tests/unit/test_chunker.py |
| 用实际文档测试解析效果，调整参数 | 1h | — |

**验证**: 对 data/raw/ 中的 PDF/DOCX/MD 文件运行解析，输出结构化 chunk，单元测试通过

---

### Day 4: Embedding + 文档入库流水线

**目标**: 文档从上传到入库的完整流水线跑通

| 任务 | 预计耗时 | 产出文件 |
|------|----------|----------|
| 实现 embedder.py (OpenAI-compatible, 批量处理, 重试) | 1h | src/document/embedder.py |
| 实现 ingestion.py (编排: MinIO上传 → 解析 → 切分 → embedding → 写库) | 2h | src/document/ingestion.py |
| 实现 documents router (upload/list/detail/delete) | 1.5h | src/api/routers/documents.py |
| 实现 FastAPI app.py (app factory + lifespan + CORS) | 45min | src/api/app.py |
| 实现 api/deps.py (共享依赖) | 30min | src/api/deps.py |
| 编写 scripts/ingest_docs.py (批量导入 CLI) | 45min | scripts/ingest_docs.py |
| 运行批量导入，将 data/raw/ 全部入库 | 1h | — |
| 验证: 查询 documents 表和 document_chunks 表 | 30min | — |

**验证**: 通过 API 上传文档 → 数据库中可查到 document + chunks + embedding 向量

---

### Day 5: 检索系统 — 向量检索 + 关键词检索

**目标**: 双路检索可用

| 任务 | 预计耗时 | 产出文件 |
|------|----------|----------|
| 实现 vector_search.py (pgvector cosine, workspace 过滤) | 1.5h | src/retrieval/vector_search.py |
| 实现 keyword_search.py (tsvector + ts_rank) | 1.5h | src/retrieval/keyword_search.py |
| 实现 metadata_filter.py (workspace/doc_type 过滤构建) | 45min | src/retrieval/metadata_filter.py |
| 实现 hybrid.py (RRF 融合 + 去重) | 1h | src/retrieval/hybrid.py |
| 编写 tests/unit/test_hybrid_retrieval.py | 1h | tests/unit/test_hybrid_retrieval.py |
| 用实际问题测试检索效果，调整 top_k 和 RRF k 值 | 1.5h | — |

**验证**: 输入技术问题，向量和关键词两路都能返回相关 chunk，RRF 融合结果合理

---

### Day 6: Reranker + 统一检索接口

**目标**: 完整检索链路 (embed → 双路召回 → RRF → rerank) 跑通

| 任务 | 预计耗时 | 产出文件 |
|------|----------|----------|
| 实现 reranker.py (API-based reranker, 支持降级跳过) | 1.5h | src/retrieval/reranker.py |
| 实现 retriever.py (UnifiedRetriever: embed → 双路 → RRF → rerank) | 1.5h | src/retrieval/retriever.py |
| 集成测试: 端到端检索流水线 | 1h | tests/integration/test_retrieval_pipeline.py |
| 准备 20 条测试问题，人工标注期望 chunk，评估 hit_rate | 2h | data/eval/ 初始数据 |
| 根据测试结果调优参数 (chunk_size, top_k, rerank_top_k) | 1.5h | — |

**验证**: UnifiedRetriever.retrieve() 对 20 条测试问题的 hit_rate > 70%

---

### Day 7: Agent 核心 — 路由 + 改写 + 基础问答

**目标**: 基础 RAG 问答链路跑通 (无工具调用)

| 任务 | 预计耗时 | 产出文件 |
|------|----------|----------|
| 实现 state.py (AgentState TypedDict) | 30min | src/agent/state.py |
| 实现 prompts/ 下所有 prompt 模板 | 1.5h | src/agent/prompts/*.py |
| 实现 input_normalizer 节点 | 30min | src/agent/nodes/input_normalizer.py |
| 实现 query_router 节点 (LLM few-shot 分类) | 1h | src/agent/nodes/query_router.py |
| 实现 scope_selector 节点 (route → workspace_ids 映射) | 30min | src/agent/nodes/scope_selector.py |
| 实现 query_rewriter 节点 (LLM 改写) | 45min | src/agent/nodes/query_rewriter.py |
| 实现 hybrid_retriever 节点 (调用 UnifiedRetriever) | 30min | src/agent/nodes/hybrid_retriever.py |
| 实现 reranker 节点 | 30min | src/agent/nodes/reranker.py |
| 实现 answer_generator 节点 (带引用生成) | 1h | src/agent/nodes/answer_generator.py |
| 实现 citation_verifier + refusal_checker 节点 | 1h | src/agent/nodes/citation_verifier.py, refusal_checker.py |
| 实现 graph.py (组装基础图，暂无工具分支) | 1h | src/agent/graph.py |

**验证**: 输入技术问题 → 正确路由 → 检索 → 生成带引用回答；输入无关问题 → 拒答

---

### Day 8: Agent 进阶 — 工具调用 + 故障排查工作流

**目标**: 完整 Agent 工作流，包含工具调用和条件分支

| 任务 | 预计耗时 | 产出文件 |
|------|----------|----------|
| 实现 evidence_validator 节点 | 45min | src/agent/nodes/evidence_validator.py |
| 实现 tool_planner 节点 (LLM 决策调用哪些工具) | 1h | src/agent/nodes/tool_planner.py |
| 实现 tool_executor 节点 | 1h | src/agent/nodes/tool_executor.py |
| 实现 5 个工具函数 | 2h | src/agent/tools/*.py |
| 编写 mock 数据 (日志、服务状态、项目 manifest) | 1h | data/mock/*.json, scripts/generate_mock_data.py |
| 更新 graph.py 添加条件分支 (evidence → tool → loop) | 1h | src/agent/graph.py |
| 端到端测试故障排查场景 | 1.5h | — |

**验证**: 输入 "Airflow task 一直失败" → 路由到 troubleshooting → 检索 + 调用 mock_logs + service_status → 生成排查步骤

---

### Day 9: Chat API + Agent API + 基础前端

**目标**: 通过 API 和前端可以完成问答

| 任务 | 预计耗时 | 产出文件 |
|------|----------|----------|
| 实现 chat router (POST /chat, GET /chat/{id}, POST feedback) | 1.5h | src/api/routers/chat.py |
| 实现 agent router (POST /agent/run, GET runs/{id}, GET trace) | 1.5h | src/api/routers/agent.py |
| 实现 frontend/api_client.py (HTTP 客户端封装) | 45min | src/frontend/api_client.py |
| 实现 Chat 对话页 (输入 + workspace 选择 + 回答 + 引用 + 反馈) | 2h | src/frontend/pages/1_chat.py, components/chat_message.py |
| 实现文档管理页 (上传 + 列表 + 状态) | 1.5h | src/frontend/pages/2_documents.py, components/document_uploader.py |
| 实现 Streamlit 主入口 app.py | 30min | src/frontend/app.py |

**验证**: 浏览器打开 Streamlit → 上传文档 → 提问 → 看到带引用回答 + 工具调用展示

---

### Day 10: 可观测 — Langfuse 集成 + Trace 页面

**目标**: 全链路 trace 可查看

| 任务 | 预计耗时 | 产出文件 |
|------|----------|----------|
| 实现 tracer.py (Langfuse callback handler 封装) | 1h | src/observability/tracer.py |
| 在 Agent 各节点中埋入 trace span | 1.5h | 更新 src/agent/nodes/*.py |
| 记录: 路由结果、检索 query、召回 chunk、rerank 分数、工具调用、生成结果、耗时、token | 1h | — |
| 实现 admin router (stats/bad-cases/index-status) | 1h | src/api/routers/admin.py |
| 实现 Trace 观测页 (查询历史 + 单条 trace 详情 + 耗时瀑布) | 2h | src/frontend/pages/3_traces.py, components/trace_viewer.py |
| 验证 Langfuse 控制台可看到完整 trace | 1h | — |

**验证**: 提一个问题 → Langfuse 控制台显示完整 trace → Streamlit trace 页面展示各阶段详情

---

### Day 11: 评估系统

**目标**: 离线评估可运行，指标可展示

| 任务 | 预计耗时 | 产出文件 |
|------|----------|----------|
| 编写 120-150 条 eval cases (JSONL 格式) | 3h | data/eval/qa_pairs.jsonl |
| 实现 metrics.py (hit_rate, MRR, NDCG, faithfulness, citation_accuracy, refusal_accuracy) | 1.5h | src/observability/metrics.py |
| 实现 evaluator.py (批量运行 eval cases, 收集指标) | 1.5h | src/observability/evaluator.py |
| 实现 bad_case.py (自动检测 bad case: 未命中/错误引用/误拒答) | 1h | src/observability/bad_case.py |
| 实现 eval router (POST /eval/run, GET results) | 1h | src/api/routers/eval.py |

**eval cases 分布**:
- 通用技术问答: 40 条
- 项目细节问答: 40 条
- 部署/配置指导: 15 条
- 故障排查任务: 25 条
- 无答案拒答: 15 条
- 引用准确性: 15 条

**验证**: 运行 eval → 输出各项指标 → bad case 列表可查看

---

### Day 12: Eval 仪表盘 + 调优

**目标**: 评估结果可视化，系统调优到可展示水平

| 任务 | 预计耗时 | 产出文件 |
|------|----------|----------|
| 实现 Eval 评估页 (指标仪表盘 + bad case 表格) | 2h | src/frontend/pages/4_eval.py, components/eval_chart.py |
| 运行完整评估，分析 bad case | 1.5h | — |
| 调优 prompt (router/rewriter/generator/refusal) | 2h | 更新 src/agent/prompts/*.py |
| 调优检索参数 (chunk_size/overlap/top_k/rerank_top_k/threshold) | 1.5h | — |
| 重新运行评估，对比调优前后指标 | 1h | — |

**目标指标** (第一版合理范围):
- Retrieval Hit Rate: > 75%
- Citation Accuracy: > 70%
- Answer Correctness: > 65%
- Refusal Accuracy: > 80%

---

### Day 13: 工程化部署 + 集成测试

**目标**: Docker Compose 一键启动，集成测试通过

| 任务 | 预计耗时 | 产出文件 |
|------|----------|----------|
| 完善 Dockerfile (多阶段构建, 生产优化) | 1h | Dockerfile |
| 完善 docker-compose.yml (healthcheck, depends_on, restart) | 1h | docker-compose.yml |
| 编写集成测试 (API 端点 + 入库流水线 + Agent 图) | 2h | tests/integration/*.py |
| 从零 docker-compose up 测试完整流程 | 1.5h | — |
| 修复发现的问题 | 2h | — |

**验证**: 全新环境 `docker-compose up` → `make migrate` → `make seed` → 上传文档 → 问答 → 查看 trace → 运行 eval

---

### Day 14: README + 架构图 + Demo 数据

**目标**: 项目文档完整，demo 路径流畅

| 任务 | 预计耗时 | 产出文件 |
|------|----------|----------|
| 编写 README.md (完整结构，含架构图) | 2.5h | README.md |
| 绘制系统架构图 (Mermaid 或 draw.io) | 1h | 嵌入 README |
| 绘制 Agent 工作流图 | 45min | 嵌入 README |
| 准备 demo 数据 (预置文档 + 预置问题) | 1h | scripts/seed_demo.py |
| 走通 5 个 demo 场景，确保每个都流畅 | 2h | — |
| 修复 demo 中发现的问题 | 1h | — |

**5 个 Demo 场景**:
1. 上传文档 → 查看解析状态
2. 通用技术问答 (K8s CrashLoopBackOff) → 带引用回答
3. 项目细节问答 (Backstage TechDocs) → 限定 workspace 回答
4. 故障排查 Agent (Airflow task 失败) → 工具调用 + 排查步骤
5. 评估仪表盘 → 指标 + bad case

---

### Day 15: 简历 + 面试准备

**目标**: 简历描述完成，面试讲解稿就绪

| 任务 | 预计耗时 | 产出文件 |
|------|----------|----------|
| 录制 demo 视频 (5 个场景) | 2h | — |
| 编写简历项目描述 (中英文) | 1h | — |
| 编写面试讲解稿 (按问题驱动线索) | 2h | — |
| 整理项目亮点清单 (面试时可展开的技术点) | 1h | — |
| 最终代码审查 + 清理 | 1.5h | — |

---

## 10. 关键依赖与风险

### 10.1 关键路径

```
Day 1 基础设施 → Day 2 数据库模型 → Day 3-4 文档解析入库 → Day 5-6 检索系统
  → Day 7-8 Agent 工作流 → Day 9 API+前端 → Day 10-12 可观测+评估 → Day 13-14 部署+文档
```

Day 1-8 是关键路径，任何延迟都会影响后续。Day 9-14 有一定弹性。

### 10.2 风险与降级策略

| 风险 | 影响 | 降级方案 |
|------|------|----------|
| Reranker API 不可用或太慢 | 检索质量下降 | 跳过 rerank，直接用 RRF 分数排序 |
| Embedding API 配额不足 | 无法入库 | 减少文档量，优先入库核心文档 |
| LangGraph 学习曲线陡峭 | Day 7-8 延迟 | 简化图结构，先做线性流程，后加条件分支 |
| Langfuse 自托管部署问题 | 可观测缺失 | 先用本地日志 + JSON 文件记录 trace，后补 Langfuse |
| 文档解析质量差 (PDF 表格/复杂排版) | 检索效果差 | 跳过复杂 PDF，优先用 Markdown 文档 |
| 15 天时间不够 | 功能不完整 | 砍 P1 功能，确保 P0 闭环完整 |

### 10.3 绝不能砍的核心

即使时间紧张，以下必须保留，否则项目失去差异化价值：

1. **双层知识库 + Query Router** — 这是核心差异点
2. **混合检索 + Rerank** — 区别于纯向量检索 demo
3. **至少 1 个完整 Agent 工作流** (故障排查) — 证明不是单轮 RAG
4. **带引用回答 + 拒答** — 证明工程化意识
5. **Eval 指标** — 证明可量化评估
6. **Docker Compose 部署** — 证明工程化交付

---

## 11. 验证方案

### 11.1 开发阶段验证

每个阶段完成后运行：
- 单元测试: `pytest tests/unit/`
- 集成测试: `pytest tests/integration/`
- 手动测试: 通过 Streamlit 前端走通核心流程

### 11.2 最终验证清单

- [ ] `docker-compose up` 一键启动所有服务
- [ ] 上传 PDF/DOCX/MD 文档，状态变为 ready
- [ ] 通用技术问答返回带引用回答
- [ ] 项目问答只检索对应 workspace
- [ ] 无关问题触发拒答
- [ ] 故障排查触发工具调用 + 生成排查步骤
- [ ] Langfuse 可查看完整 trace
- [ ] Eval 运行输出各项指标
- [ ] Bad case 页面可查看
- [ ] 5 个 demo 场景全部流畅通过
