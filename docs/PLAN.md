# DocWise PLAN

## 1. 项目目标

DocWise 的目标是一个企业级开发者知识工作流 Agent：

- 面向开发者、SRE、运维工程师，解决技术文档、项目资料、SOP、日志和服务状态分散导致的排障低效问题。
- 以 RAG 为基础，结合路由、workspace 隔离、工具调用、trace 和 eval，提供可验证、可追溯的技术问答和故障排查。
- 保留真实企业 MVP 边界：PostgreSQL/pgvector、Redis、MinIO、独立 worker、结构化 trace、评估体系和可恢复本地部署。

## 2. 当前权威运行架构

| 模块 | 当前实现 |
| --- | --- |
| API | FastAPI，`src/api/app.py` 注册 chat、agent、documents、eval、traces、lab、workspaces、admin 路由 |
| Worker | arq worker，`src/tasks/worker.py` 暴露 ingest、reindex、eval job |
| DB | PostgreSQL + pgvector + tsvector，SQLAlchemy async，Alembic 当前 head 为 `006` |
| Cache/Queue | Redis，用于 arq、embedding cache 和入库锁 |
| Object Storage | MinIO，默认 bucket `docwise-documents`，seed 和 ingestion 会确保 bucket 存在 |
| LLM | DeepSeek-compatible chat wrapper，区分 fast/pro 模型 |
| Embedding/Rerank | DashScope/Qwen `text-embedding-v4`，维度 2048；`qwen3-rerank`，失败可降级 |
| Agent | LangGraph StateGraph，节点在 `src/agent/nodes/`，工具在 `src/agent/tools/` |
| Retrieval | pgvector vector search + tsvector keyword search + RRF + rerank |
| Observability | 本地 DB trace first，Langfuse optional |
| Frontend | Next.js，前端工程位于 `web/` |

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
| `web/` | Next.js app、组件、页面与前端 API 调用 |
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
| 前端 | Next.js | 当前唯一前端实现，面向正式展示与交互 |

## 5. 数据与运行契约

- `.env.local.example` 用于 Windows `.venv` 跑 API/worker，本地前端使用 `web/` 下的 Next.js，基础设施地址使用 `localhost`。
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
| Documents | `POST /api/v1/documents/upload`, `GET /api/v1/documents`, `GET /api/v1/documents/{document_id}`, `GET /api/v1/documents/{document_id}/chunks`, `GET /api/v1/documents/jobs/{job_id}`, `POST /api/v1/documents/{document_id}/retry`, `DELETE /record`, `DELETE /purge` |
| Chat | `POST /api/v1/chat`, `POST /api/v1/chat/stream`, `POST /api/v1/chat/runs/{run_id}/cancel`, `GET /api/v1/chat/history`, `GET /api/v1/chat/conversations`, `GET /api/v1/chat/conversations/{conversation_id}`, `PATCH /api/v1/chat/conversations/{conversation_id}/rename`, `PATCH /api/v1/chat/conversations/{conversation_id}/archive`, `DELETE /api/v1/chat/conversations/{conversation_id}`, `GET /api/v1/chat/{query_id}`, `POST /api/v1/chat/{query_id}/feedback` |
| Agent | `POST /api/v1/agent/run`, `GET /api/v1/agent/runs/{run_id}/status`, `GET /api/v1/agent/runs/{run_id}/trace` |
| Traces | `GET /api/v1/traces`, `GET /api/v1/traces/{run_id}/timeline` |
| Eval | `GET /api/v1/eval/count`, `POST /api/v1/eval/run`, `GET /api/v1/eval/results`, `GET /api/v1/eval/trends`, `GET /api/v1/eval/bad-cases` |
| Lab | `POST /api/v1/lab/compare` |
| Workspaces | `GET /api/v1/workspaces` |
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
pytest: 174 passed
```

真实 smoke 已验证过的链路：

- Docker `postgres`、`redis`、`minio` healthy
- Alembic 到 `006 (head)`（Phase A M2 多轮字段已落地：`agent_runs.turn_index/parent_run_id` + `queries.context_summary`）
- `scripts.seed_demo` 完成
- `scripts.ingest_docs --workspace public_tech --dir data\raw\airflow` 两份 demo 文档到 `ready`
- `--enqueue` 对已有文档返回 succeeded job
- Qwen embedding 返回 2048 维
- Qwen rerank 非 fallback
- DeepSeek-compatible chat 返回预期 smoke 文本

## 9. V1 定位与实施策略

### 9.1 V1 形态与边界

V1 形态收敛为「公开技术文档知识库驱动的内部 RAG + 运维辅助 Agent」，不扩展为通用 agent 平台。以下边界写死到本阶段：

- 不新建独立 `conversations` 表；继续以 `queries` 作会话根、`agent_runs` 作 turn 记录。
- 不引入 OpenClaw control plane、多通道接入、MCP 编排层；这些留给 V2+。
- Live tools（真实服务状态查询、真实日志、外部 ticket 系统）延后；V1 只做 runtime policy 框架 + mock/live adapter 分离，为 V2+ 接入做好骨架。
- 不做 session branching / 多分支重跑；前端保持单会话单线索体验。

### 9.2 优先级链

按「**上下文运行时与多轮体验 → 真实知识库 → Agent 能力（grounding/工具/runbook） → 协议与 eval 回流**」执行。多轮对话和 scope 运行时策略的体验价值最高，置于最前；真实知识库先于 Agent 能力强化（避免在 demo 数据上做复杂 grounding 逻辑）；协议统一和 eval 框架收尾。

### 9.3 Phase 编排（4 Phase，13 模块）

| Phase | 模块 | 主题 | 核心产出 |
| --- | --- | --- | --- |
| **A** | M0 → M1 → M2 → M3 → M4 | 上下文运行时 + 多轮 + scope + rewrite | 体验主线稳定：多轮不丢主题、scope 可解释、rewrite 可追溯 |
| **B** | M8 | 真实知识库采集与文档处理工程 | 200+ 真实文档入库，Agent 能力强化有真实数据支撑 |
| **C** | M5 → M6 → M7 → M9 | Grounding 闭环 + Tool Orchestration + Runbook 专线 + Retrieval 深化 | 证据闭环、typed artifact 工具链、runbook 亮点链路、检索实验策略 |
| **D** | M10 → M11 → M12 | 契约统一 + Eval 回流 + 安全边界 | SSE 单一协议、bad case 六层归因、tool policy 就位 |

### 9.4 统一验收标准

- 多轮连续 5 轮不丢主题、不丢前提、不丢引用来源。
- `project_specific` 与 `troubleshooting` 在 Auto scope 下不再误打到 `public_tech`。
- Rewrite、scope、tool chain、grounding 都能在 trace 中解释「为何如此」。
- 真实知识库可复现采集、可批量入库、可导出 chunk index。
- SSE 契约与前端消费一致，取消、恢复、reasoning 展示一致。
- Eval 能覆盖单轮、多轮、工具、拒答、runbook，并能给出可回流的坏例归因。

详细规划见 §13–§17。

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

## 12. 实施工作包与当前状态

这一节吸收旧 `docs/TASK.md` 的工作包拆解，但按当前仓库状态重新归并。后续继续开发时，以这里的责任域和验证门为准。

| 工作包 | 当前主要路径 | 当前状态 | 下一步关注 |
| --- | --- | --- | --- |
| WP-01 Infra/Foundation | `pyproject.toml`, Dockerfile, Compose, Alembic, `src/config/`, `src/db/`, `src/models/`, `src/schemas/` | 已恢复到可运行，本地 infra health、Alembic head=006、seed 基线可用；Phase A M2 多轮字段已落地（`agent_runs.turn_index/parent_run_id` + `queries.context_summary`） | Migration 007（Phase B M8：`documents.provenance` + `parent_document_id` + `is_container` + `DocumentStatus.container`）、Migration 008（Phase C M5：`agent_runs.grounding_report_json`）、前端 Docker 集成、CI workflow |
| WP-02 LLM/Document/Tasks | `src/llm/`, `src/document/`, `src/tasks/`, `scripts/ingest_docs.py`, `data/raw/` | chunker、ingestion、MinIO bucket、embedding、worker 路径已恢复 | RST parser、真实文档批量入库、大文件处理 |
| WP-03 Retrieval/Agent | `src/retrieval/`, `src/agent/` | hybrid retrieval、rerank fallback、LangGraph 12 节点主链路完整；`POST /lab/compare` 已支持 4 种策略（`vector_only / keyword_only / hybrid / hybrid_rerank`）+ `rrf_k / rerank_top_k` 参数；SSE reasoning 事件已接入 | `context_loader` 节点、多轮对话摘要注入 `query_rewriter`、HyDE / Query Decomposition 实验 |
| WP-04 API/Frontend | `src/api/`, `web/` | FastAPI 路由完整（chat/agent/documents/eval/traces/lab/workspaces/admin）；Next.js 5 核心页 + History/Archive/Home 全部上线；Lab 页支持策略多选 + 参数滑块 + 重叠度热力图 + 耗时对比 | 多轮对话前端、反馈持久化、文件附件 |
| WP-05 Observability/Eval/Data | `src/observability/`, `data/mock/`, `data/eval/` | mock/eval fixture gate 通过，eval cases 为 20 retrieval + 30 qa | 真实文档 eval case 对齐、扩展到 80-100 条、趋势追踪 |
| Docs/Contracts | `docs/`, `docs/contracts/` | GUIDE/PLAN/AGENT 已完成当前化合并 | 后续改动必须同步权威文档 |

### 合并与验证顺序

1. 真实知识库（Phase 1）先行：下载脚本 → RST parser → 批量入库 → eval 对齐。
2. RAG 深化（Phase 2）：conversations 表 → context_loader → reasoning 事件 → 检索实验室后端。
3. 前端重构（Phase 3）：Next.js 初始化 → Chat → Docs → Traces → Eval → Lab。
4. 每个 Phase 完成后运行完整质量门（pytest + ruff + fixture validation + smoke）。

### 当前验收清单

- [x] Docker `postgres` / `redis` / `minio` healthy。
- [x] Alembic 当前版本为 `006 (head)`（Phase A M2 已落地）。
- [x] `scripts.seed_demo` 成功并创建/确认 MinIO bucket。
- [x] `data/mock/` 与 `data/eval/` validation 通过。
- [x] `ruff check src tests scripts alembic` 通过。
- [x] `pytest -q` 当前为 `174 passed`。
- [x] `scripts.ingest_docs --workspace public_tech --dir data\raw\airflow` 同步入库到 ready。
- [x] `scripts.ingest_docs --workspace public_tech --dir data\raw\airflow --enqueue` 返回已有 succeeded job。
- [ ] 真实文档 200+ 入库，hit_rate@5 > 75%。
- [ ] 多轮对话 + reasoning 事件可消费。
- [ ] Next.js 前端 5 页可用。
- [ ] Eval 仪表盘有真实数据趋势。

---

## Part II：V1 详细开发规划

---

## 13. 13 模块总览与依赖

### 13.1 模块列表

| # | 模块 | 核心产出 | 主要落点 |
|---|---|---|---|
| **M0** | 权威规划与契约基线 | PLAN.md 重写、api_contract/sse_events/db_schema/tool_schemas 对齐代码事实 | `docs/PLAN.md`, `docs/contracts/*` |
| **M1** | Context Runtime 与上下文装配层 | durable history vs model-visible context 分离、token budget、rolling summary / compaction、context diagnostics | `src/agent/graph.py`, 新 `src/agent/context/` |
| **M2** | 多轮记忆与 context_loader | 图内新增节点、recent_turns + context_summary 双层注入、`agent_runs.turn_index/parent_run_id`、`queries.context_summary` | 新 `src/agent/nodes/context_loader.py`, `src/models/agent.py`, `src/models/query.py` |
| **M3** | Route / Scope / Workspace 运行时策略 | 拆分「显式 workspace」与「系统 scope policy」；Auto scope 默认；`troubleshooting=project+public+mock_ops`；前端 workspace 行为修正；scope 命中理由写入 reasoning | `src/agent/nodes/scope_selector.py`, `web/src/components/chat/chat-console.tsx` |
| **M4** | Query Rewriter 修复与检索输入规范化 | 先修 route 参数 fallback；区分 original / rewritten / effective_query；接收 context_summary；保留硬实体 | `src/agent/nodes/query_rewriter.py`, `src/agent/prompts/rewriter.py` |
| **M5** | Evidence / Citation / Refusal Grounding 闭环 | 关键结论严引用、叙述性宽松；critical-claim grounding；citation 升级为 claim 对齐；evidence route-specific 阈值；refusal 三态；`grounding_report_json` 持久化 | `src/agent/nodes/{evidence_validator,citation_verifier,refusal_checker}.py`, `src/models/agent.py` |
| **M6** | Tool Orchestration Runtime | tool_planner 升级为 artifact-driven plan；typed artifacts；参数补全、依赖串接、超时分类、取消、重试、结构化失败 | `src/agent/nodes/{tool_planner,tool_executor}.py`, 新 `src/agent/artifacts.py` |
| **M7** | runbook_generation 垂直链路 | 独立子图：search_docs → manifest → status/logs → 结构化 section 生成 + 引用 + 执行前提 + 失败降级 | `src/agent/tools/generate_runbook_draft.py`, runbook subgraph |
| **M8** | 真实知识库采集与文档处理工程 | source lock + manifest + provenance + sparse-checkout；RST parser；大文件预切分；section_path 推断；跨 workspace 去重 | 新 `scripts/download_real_docs.py`, `src/document/parser.py`, `src/document/ingestion.py` |
| **M9** | Retrieval 深化与实验策略 | Query Decomposition / HyDE / neighbor expansion / parent document retrieval / metadata-aware rerank；route-specific 默认策略；`/lab/compare` 扩展 | 新 `src/retrieval/{hyde,decompose,neighbors}.py`, `src/api/routers/lab.py` |
| **M10** | Trace / SSE / 前端消费契约统一 | 统一事件协议（run/reasoning/route/retrieval/rerank/tool_call/tool_result/token/citation/done/error/cancelled）；移除临时 answer 事件；前端状态机重写 | `docs/contracts/sse_events.pyi`, `src/api/routers/chat.py`, `web/src/lib/api.ts` |
| **M11** | Eval 体系与 bad case 回流闭环 | chunk remap；multi-turn / tool-use / runbook / refusal eval cases；新指标（critical_claim_grounding / context_retention / follow_up_resolution）；bad case 六层归因 | `src/observability/evaluator.py`, `data/eval/*.jsonl` |
| **M12** | 安全边界、Tool Policy 与未来外联准备 | Runtime tool policy（资源范围 / 输出长度 / 超时 / 频率 / 熔断）；mock adapter 与 live adapter 分离；审计；降级 | 新 `src/agent/tool_policy.py`, 各工具基类 |

### 13.2 依赖关系

```text
M0 (契约基线) ──┐
                ├─► M1 (runtime 骨架) ──► M2 (多轮) ──► M3 (scope) ──► M4 (rewriter)
                └─► M8 (真实知识库) ────────┐                              │
                                           │                              ▼
                                           └──► M9 (检索深化)     M5 (grounding)
                                                   │                      │
                                                   └──► M6 (工具编排) ◄───┤
                                                          │               │
                                                          └─► M7 (runbook subgraph)
                                                                          │
                                          M10 (SSE契约) ◄─────────────────┤
                                          M11 (eval回流) ◄────────────────┤
                                          M12 (tool policy) ◄─────────────┘
```

### 13.3 Phase 编排

| Phase | 模块 | 主题 |
| --- | --- | --- |
| **A** | M0 → M1 → M2 → M3 → M4 | 上下文运行时 + 多轮 + scope + rewrite（体验主线） |
| **B** | M8 | 真实知识库（在 Agent 能力强化前先建数据底座） |
| **C** | M5 → M6 → M7 → M9 | Grounding 闭环 + Tool Orchestration + Runbook 专线 + Retrieval 深化 |
| **D** | M10 → M11 → M12 | 契约统一 + Eval 回流 + 安全边界 |

每个 Phase 结束执行跨阶段质量门（见 §16.5）。

---

## 14. Phase A：上下文运行时与多轮体验主线

### 14.1 M0 — 权威规划与契约基线

**目标**：让 `docs/PLAN.md`、`docs/contracts/*` 与代码事实一致，后续实现不再靠重新解释边界。

**子任务**：

- 重写 PLAN.md Part II（本次改动）。
- `docs/contracts/api_contract.md` 对齐 chat conversations、traces、lab、workspaces 实际端点（已完成）。
- `docs/contracts/sse_events.pyi` 升级为 §14.10 (M10) 的统一事件协议（M10 收尾）。
- `docs/contracts/db_schema.md` 增补 queries 会话字段（`conversation_title`, `is_archived`, `context_summary`）、`agent_runs.turn_index/parent_run_id/grounding_report_json` 字段。
- `docs/contracts/tool_schemas.pyi` 添加 typed artifacts 基类（为 M6 做准备）。

**交付物**：一套与代码事实一致的权威文档。

**验收**：任意新成员读完 PLAN.md + contracts 能理解 V1 边界、当前进度和下一步任务，无需问人。

### 14.2 M1 — Context Runtime 与上下文装配层

**目标**：把 LangGraph 从「节点图」升级为「上下文运行时」，durable history 与 model-visible context 分离。

**当前实现注记**：M1 已按 **per-call budget** 落地，当前通过 `answer_context_budget` 与 `tool_planner_context_budget` 分别控制上下文预算，而不是严格按示意图里的全局 `32K` 桶式切分实现。

**子任务**：

- 新建 `src/agent/context/` 模块：
  - `builder.py`：`ContextBuilder.build(state, token_budget) -> ModelContext`，在每次模型调用前由上游节点显式调用。
  - `projection.py`：三分层投影 —— `durable`（进 trace_events）/ `working`（进模型）/ `ui`（进 SSE）。
  - `compaction.py`：rolling summary，当 working context 超阈值（默认 `MODEL_CONTEXT_MAX_TOKENS * 0.7`）时，将更早的 retrieval / tool results 替换为摘要。
  - `diagnostics.py`：记录每轮上下文构成（system + recent turns + summary + retrieval + tool results 各自 token 占用）。
- `AgentState` 增加 `working_context_snapshot` 字段（本轮模型实际看到的 projection），写入 `trace_events.metadata` 便于事后回放。
- 在 `answer_generator` / `tool_planner` 节点前接入 builder，不再直接读 raw state。
- 大输出截断规则：retrieval 每条 chunk 默认不超过 1000 字符，tool result 默认不超过 2000 字符（可配），截断时保留"可续读 offset"。

**交付物**：独立 context runtime 层 + 可追踪的 context diagnostics。

**验收**：

- 给定一个混合召回 10 chunks + 3 轮历史的 state，builder 能产生稳定的 ModelContext 对象。
- Trace 里能看到「本轮塞给模型了什么、token 分布、是否触发 compaction」。
- 单元测试覆盖：budget 裁剪、summary 触发、截断续读。

### 14.3 M2 — 多轮记忆与 context_loader

**目标**：让 conversation 不再只是 UI 壳，真正进入 graph，实现 follow-up 记忆链。

**子任务**：

- **Alembic 006**（数据模型微调，不新建 conversations 表）：
  - `agent_runs` 加 `turn_index INT NOT NULL DEFAULT 0`、`parent_run_id UUID NULL REFERENCES agent_runs(id) ON DELETE SET NULL`。
  - `queries` 加 `context_summary TEXT NULL`。
  - 为 `(query_id, turn_index)` 建索引，加速历史加载。
- 新节点 `src/agent/nodes/context_loader.py`，位置在 `input_normalizer → context_loader → query_router`：
  1. 从 DB 按 `queries.id` 根 + 同 `conversation_title/parent_query_id` 的关联，加载最近 N=5 轮 `(user_query, answer, final_citations, key_tool_results)`。
  2. 填 `state.recent_turns`（原文，≤ 最近 3 轮）和 `state.context_summary`（更早轮用 LLM 生成 ≤ 200 字摘要，持久化到 `queries.context_summary` 避免重算）。
  3. 把结构化摘要写进 `trace_events` 便于前端 reasoning 面板展示"读到了哪些历史"。
- `agent_runs.parent_run_id` 在每次 chat 调用时由 chat router 显式设置（当同一 query 再次跑时形成取消/重试链）。
- Chat 流 SSE 新增 `event: conversation data: {"conversation_id": ..., "turn_index": ...}`（事件协议由 M10 统一规范）。

**交付物**：真正可用的 follow-up 记忆链。

**验收**：

- 连续 5 轮问答能保持主题、前提和已有排障结论（例如第 1 轮问"Airflow scheduler 卡住"，第 3 轮问"那 task 超时呢？"时能正确关联上文）。
- Trace 里可看到 context_loader 加载了哪些历史轮、摘要内容、是否命中缓存。
- 新增 eval 子集 `multi_turn_followup.jsonl`（M11 补 10 条）。

### 14.4 M3 — Route / Scope / Workspace 运行时策略

**目标**：拆分「显式 workspace 选择」与「系统 scope policy」，让 Auto 模式成为默认，同时允许用户显式覆盖。

**子任务**：

- 后端：
  - `scope_selector` 重构：输入 `(route, explicit_workspace_slugs, query, alias_hits)`，输出 `effective_workspaces`。
  - 固定各 route 的默认 scope：
    - `tech_general` → `[public_tech]`
    - `project_specific` → `[project_alias_hit or project_pack_default, public_tech]`
    - `troubleshooting` → `[project_alias_hit or project_pack_default, public_tech, mock_ops]`
    - `runbook_generation` → `[project_alias_hit or project_pack_default, public_tech]`
    - `out_of_scope` → `[]`（直接进入 refusal_checker）
  - 当用户显式传 `workspace_slug` 时，scope_selector 把它加入 effective_workspaces 并合并 route 默认（不再完全覆盖）。
  - 把命中理由写入 `trace_events`：`{node: "scope_selector", effective: [...], reason: "troubleshooting default + alias hit 'airflow'"}`。
- 前端：
  - `chat-console.tsx` 的请求体默认不传 `workspace_slug`（Auto mode）。
  - Chat 页 workspace 选择器新增「Auto」选项（默认选中）+ 列出 `GET /workspaces` 的具体选项；选 Auto 时不传字段。
  - Reasoning 面板显示 effective workspaces 和命中理由。

**交付物**：稳定可解释的 scope 运行时。

**验收**：

- 同一问题「Airflow task 超时怎么排查」在三种入口下行为一致：
  - Auto 模式：effective = `[project_airflow, public_tech, mock_ops]`
  - 显式 `workspace=project_airflow`：effective = `[project_airflow, public_tech, mock_ops]`（合并非覆盖）
  - 显式 `workspace=public_tech`：effective = `[public_tech, mock_ops]`（用户意图优先但保留 troubleshooting 的 mock_ops）
- 前端请求体不再写死 `public_tech`。
- Trace 里能看到 scope 决策理由。

### 14.5 M4 — Query Rewriter 修复与检索输入规范化

**目标**：当前基础 bug 已修，M4 重点转为把 rewriter 收敛为 route-aware、context-aware 的检索输入规范化层，并让 `effective_query` 真正进入检索链路与 Lab 对比工具。

**子任务**：

- **字段所有权收敛**：`query_rewriter` 成为 `effective_query` 的唯一写入者；`tool_planner` / `answer_generator` 不再覆盖它。
- **Route-aware + history-aware rewrite**：rewriter 继续消费 M2 的 `recent_turns/context_summary`，把 follow-up 如「那 task 超时呢？」改写为独立查询。
- **硬实体守卫**：对白名单实体（错误码、HTTP 状态码、版本、路径、配置文件名、`key_entities`）做保守检查；缺少任一 critical entity 时，`effective_query` 回退到 `original_query`。
- **检索链路接线**：`hybrid_retriever` 与 `reranker` 统一改读 `effective_query`。
- **Trace 与 Lab 同步写入**：rewrite 前后的 query 与 fallback 诊断写入 `trace_events`，`/lab/compare` 增加 `use_rewriter`、`route_override` 和 history 模拟输入。

**交付物**：稳定的 route-aware + context-aware rewrite 机制。

**验收**：

- Rewriter 对 project_specific / troubleshooting / runbook_generation 三种 route 产出的改写结果有明显风格差异（可通过 eval case 验证）。
- Trace 里能看到 original / rewritten / effective 三个 query。
- 硬实体保留回归测试覆盖至少 5 个典型 case（错误码、服务名、版本、路径、组件）。
- 真实 eval（M11）的 `hit_rate@5` 与 rewriter 禁用基线比较，至少不劣化，troubleshooting 类应有提升。

---

## 15. Phase B：真实知识库工程

### 15.1 M8 — 真实知识库采集与文档处理工程

**目标**：用真实的公开技术文档替换当前 demo stub，建立可复现、可审计的 200+ 文档、~1500 chunks 知识库底座，为 Phase C 的 Agent 能力强化提供真实数据。

**文档来源与许可**：

| 来源 | Workspace | 预计文档 | 格式 | 许可 |
|---|---|---|---|---|
| Apache Airflow docs | `project_airflow` | ~80 | RST / MD | Apache-2.0 |
| Backstage docs + ADRs | `project_backstage` | ~60 | MD | Apache-2.0 |
| FastAPI docs (en) | `project_fastapi` | ~50 | MD | MIT |
| Kubernetes troubleshooting | `public_tech` | ~30 | MD | CC-BY-4.0 |
| PagerDuty Incident Response | `public_tech` | ~20 | MD | Apache-2.0 |
| Redis docs (精选) | `public_tech` | ~15 | MD | BSD-3 |
| Prometheus docs (精选) | `public_tech` | ~10 | MD | Apache-2.0 |

总计：~265 文档，预计 ~2000 chunks，embedding 成本约 ¥5–10。

**子任务**：

- **M8.1 采集脚本** `scripts/download_real_docs.py`：
  - 基于 `git sparse-checkout` 避免 clone 整仓。
  - `SOURCES` 列表（仓库 URL、branch、sparse_paths、file_filter、exclude_patterns、max_files、workspace）。
  - 按 max_files 截断时优先保留中等大小（3–30 KB）文件。
  - 输出到 `data/raw/<source_name>/`，保留相对路径结构。
- **M8.2 Source lock + manifest**：
  - 生成 `data/raw/manifest.json`：记录每个 source 的 `commit_sha`、`retrieved_at`、`file_count`、`total_bytes`、`license`，实现复现性。
  - 每份文档入库时在 `documents.metadata` 记录 `provenance = {source, commit_sha, original_path, license}`。
- **M8.3 RST parser** `src/document/parsers/rst.py`：
  - 使用 `docutils` 转换为 Markdown 中间态，复用现有 chunker。
  - 保留标题层级、代码块、表格。
  - 单元测试覆盖 Airflow docs 典型文件（configuration/logging/troubleshooting）。
- **M8.4 大文件预分割**：
  - 超过 30 KB 的文件按 H1/H2 标题预分割为子文档。
  - 子文档在 `documents` 表保留 `parent_document_id` 关联。
- **M8.5 元数据提取增强**：
  - `section_path` 从文件路径推断：`airflow/configuration/logging.rst` → `configuration > logging`。
  - 从 frontmatter / RST field list 提取 `title`、`tags`、`version`。
  - 自动标注 `doc_type`（tutorial / reference / troubleshooting / adr / runbook）。
- **M8.6 跨 workspace 去重**：
  - 入库前计算 `content_hash = sha256(normalized_text)`。
  - 同 workspace 内 hash 重复则跳过。
  - 跨 workspace 允许重复（同一文档可能属于多个知识域）。
- **M8.7 Chunk index 导出**：
  - `scripts/export_chunk_index.py --output data/eval/chunk_index.json`，供 M11 eval chunk remap 使用。

**交付物**：

- 可复现的采集链路（`scripts/download_real_docs.py` + `manifest.json`）。
- 200+ 文档在 DB，1500+ active chunks。
- RST parser 单元测试通过。
- `chunk_index.json` 可供后续 eval 脚本消费。

**验收**：

- 从空仓库开始，`python -m scripts.download_real_docs` 能稳定产出全部 source。
- 批量入库脚本能完成全部 workspace 的 ingestion，无 OOM 或超时。
- Chunk 抽检 20 条，分割质量合格（标题完整、代码块不截断）。
- 当前 demo eval cases（50 条）经过 chunk remap 后仍可运行（允许 hit_rate 暂时劣化，M11 会补新 cases）。

**风险与降级**：

- RST 解析复杂时可先跳过 Airflow（~80 条）只入 MD 源，规模降到 ~180 文档。
- Embedding 成本超预期时减少 max_files，优先保留 troubleshooting / runbook 类。

---

## 16. Phase C：Agent 能力强化（基于真实知识库）

### 16.1 M5 — Evidence / Citation / Refusal Grounding 闭环

**目标**：把"关键结论严格引用、叙述性内容宽松组织"的分层证据策略做成产品能力，而不是散落在节点里的正则补丁。

**子任务**：

- **M5.1 Critical claim 分类器**（轻量 LLM 调用或规则）：
  - 在 `answer_generator` 后增加节点 `claim_extractor`。
  - 对答案按句子切分，标注每句是否为 critical claim：含数值、错误码、明确配置项名、命令、推荐动作、"必须/应当/禁止"等强断言时为 critical；叙述性连接、背景说明、一般性总结为 narrative。
- **M5.2 Citation alignment**（升级 `citation_verifier`）：
  - 当前 verifier 只做编号→chunk id 过滤，升级为 critical claim → evidence span 对齐：
    - Critical claim 必须映射到至少一个 chunk 的具体文本 span（不要求完全复现，但需语义覆盖）。
    - 映射失败的 critical claim → 标记 `unsupported_critical_claim`，触发二次生成（重新 prompt 要求补引用）或降级为提示用户。
  - Narrative sentence 允许无强映射，不产生 unsupported 警告。
- **M5.3 Route-specific 证据阈值**（升级 `evidence_validator`）：
  - `tech_general`：rerank top1 ≥ 0.25
  - `project_specific`：rerank top1 ≥ 0.28
  - `troubleshooting`：rerank top1 ≥ 0.30，且至少一条来自 project workspace 或 mock_ops
  - `runbook_generation`：rerank top1 ≥ 0.32，且至少两条来自 reference / runbook 类 doc_type
  - 不足时 → evidence_validator 触发 tool_planner（而不是直接 refuse）。
- **M5.4 Refusal 三态**（重构 `refusal_checker`）：
  - `continue`：证据充分，走完整生成。
  - `clarify`：证据模糊或 query 有歧义，生成澄清问题（如"你指的是 Airflow 2.x 还是 1.x？"）。
  - `refuse`：明确 out_of_scope 或 critical claim 无法 ground，拒答并说明原因。
- **M5.5 Grounding report 持久化**：
  - Migration 008：`agent_runs.grounding_report_json` JSONB 字段（注：原 §12 路线图把此 migration 标为 `007`，但 Phase B M8 已先行占用 `007` 用于 `documents.provenance`/`parent_document_id`/`is_container`。M5 的 grounding migration 顺延为 `008`，`down_revision = "007"`。）
  - 记录：`{critical_claims: [...], aligned: [...], unsupported: [...], narrative_count: N, threshold_met: bool, refusal_state: "continue"|"clarify"|"refuse"}`。
  - 前端 chat 页面/ trace 页面可展示 grounding 细节。

**交付物**：

- `claim_extractor` / 升级后的 `citation_verifier` / `evidence_validator` / `refusal_checker` 四节点。
- `grounding_report_json` schema 与前端展示。

**验收**：

- 关键数字、错误码、明确结论、推荐动作 100% 可回溯到 chunk 或工具事实。
- Narrative 段落不产生 unsupported 警告，保留模型组织空间。
- Eval 新增 `critical_claim_grounding_rate` 指标（M11），在真实 corpus 上 ≥ 85%。
- Refusal accuracy（正确拒答 out_of_scope 问题）≥ 90%。

### 16.2 M6 — Tool Orchestration Runtime

**目标**：把 tool_planner 从固定工具链升级为 artifact-driven 执行计划，让工具间真正形成「输入-输出-依赖」链。

**子任务**：

- **M6.1 Typed artifacts** `src/agent/artifacts.py`：
  - 定义基类 `Artifact` 和典型子类：
    - `DocHits`: `{chunks: list[ChunkRef], retrieval_strategy: str, score_stats: {...}}`
    - `ManifestFacts`: `{project: str, services: list[...], owners: list[...], environments: list[...]}`
    - `ServiceStatusFacts`: `{service: str, health: str, incidents: [...], last_deploy: ...}`
    - `LogFindings`: `{service: str, window: str, error_patterns: [...], counts: {...}}`
    - `RunbookSections`: `{title, sections: [{heading, steps: [...], prerequisites, citations}]}`
  - Artifact 可序列化到 `trace_events` 便于回放。
- **M6.2 tool_planner 改造**：
  - 输入：`(route, query, evidence_state, existing_artifacts)`；输出：`ToolPlan = [ToolStep(tool, required_artifacts, produces_artifact_type)]`。
  - 按 route 定义典型 plan：
    - `troubleshooting`: `[query_project_manifest → query_service_status → query_mock_logs]`（后一工具依赖前一工具的 service 名）。
    - `runbook_generation`: 见 M7。
    - `project_specific`: 仅在 evidence 不足时触发 `query_project_manifest`。
  - Plan 允许条件分支（"若 service_status 显示 healthy 则跳过 log 查询"）。
- **M6.3 tool_executor 改造**：
  - 参数补全：前一个工具 artifact 里的字段自动注入下一个工具的参数（如 `query_service_status` 输出的 `service` 自动填给 `query_mock_logs`）。
  - 失败分类：区分 `transient`（可重试，最多 2 次）/ `invalid_input`（参数问题，不重试）/ `permission_denied`（M12 tool policy 拦截）/ `timeout`（可重试 1 次）/ `unavailable`（降级到下一个替代工具）。
  - 结构化失败反馈：工具失败后在 state 写入 `tool_failures = [{tool, reason, artifact_if_partial}]`，让 answer_generator 能解释"我试过但没拿到"。
  - 取消传播：chat cancel 事件到达时，中断正在执行的工具（通过 `asyncio.CancelledError`）。
  - 轮次上限：单次 chat 最多 `MAX_TOOL_ROUNDS = 3`，超过后强制进 answer_generator。
- **M6.4 before/after tool hooks**：
  - `before_tool_call(state, tool, args) -> Decision(allow|deny|modify)`：为 M12 tool policy 预留。
  - `after_tool_call(state, tool, result, duration_ms)`：写 trace、截断大输出、记录到 artifacts。

**交付物**：

- `src/agent/artifacts.py` + 升级后的 `tool_planner.py` / `tool_executor.py`。
- 5 种 typed artifact 的结构化 schema。
- 3 种 route 的典型 tool plan 模板。

**验收**：

- `troubleshooting` 链路可自动把 `query_project_manifest` 返回的 service 名串到 `query_service_status` 和 `query_mock_logs`，无需 LLM 二次解析。
- 工具失败时有结构化分类，不会把原始 stack trace 透给模型。
- Trace 里能看到完整 tool plan、依赖边、失败节点和降级路径。
- 单元测试：模拟 transient 失败→重试成功、permission_denied→不重试、超轮次→强制收敛。

### 16.3 M7 — runbook_generation 垂直链路

**目标**：让 `runbook_generation` 成为 DocWise 的企业亮点链路，不复用通用问答，而是独立子图。

**子任务**：

- **M7.1 独立子图**：
  - 从 `query_router` 识别为 `runbook_generation` 后，走专门的 subgraph：
    ```
    runbook_search (search_docs with doc_type filter)
      → manifest_fetch (query_project_manifest)
      → facts_fetch (query_service_status + query_mock_logs)
      → runbook_synthesizer (generate_runbook_draft, artifact-driven)
      → runbook_validator (check sections, citations, prerequisites)
    ```
- **M7.2 `generate_runbook_draft` 重写**：
  - 输入：`DocHits + ManifestFacts + ServiceStatusFacts + LogFindings`。
  - 输出：`RunbookSections` artifact，严格结构：
    ```json
    {
      "title": "...",
      "sections": [
        {
          "heading": "前提检查",
          "prerequisites": ["...", "..."],
          "steps": [
            {"action": "...", "command": "...", "expected": "...", "citations": ["chunk_uid_1"]}
          ]
        }
      ]
    }
    ```
- **M7.3 失败降级**：
  - Facts 不足时（服务状态未命中、manifest 缺失），降级为 `runbook_draft` 而非答非所问。
  - Draft 明确标注「基于通用文档生成，未结合项目实际状态」。
- **M7.4 前端渲染**：
  - Chat 页面对 RunbookSections artifact 做专门渲染（折叠 section、citation 悬浮卡、复制命令按钮）。

**交付物**：

- Runbook subgraph + `generate_runbook_draft` artifact 化版本。
- 前端 runbook 专用渲染组件。

**验收**：

- 至少一条端到端 runbook 流程稳定跑通（`project_airflow` + `mock_ops`）。
- 生成的 runbook 每个 step 都有 citations 或标注「来自 mock_ops service status」。
- Eval 新增 `runbook_completeness_score`（M11）：检查 title / prerequisites / steps / citations 是否齐全。

### 16.4 M9 — Retrieval 深化与实验策略

**目标**：在 hybrid baseline 基础上引入更强的检索增强，先在 `/lab/compare` 验证、再择优晋升到主链路。

**子任务**：

- **M9.1 Query Decomposition** `src/retrieval/decompose.py`：
  - LLM 把复杂 query 拆为 2–3 个子问题（如「Airflow 在 K8s 上部署时 task 失败如何排查」→「Airflow K8sExecutor 配置」+「Airflow task 失败常见原因」+「K8s pod 失败调试」）。
  - 各子问题独立走 hybrid，合并去重后统一 rerank。
- **M9.2 HyDE** `src/retrieval/hyde.py`：
  - LLM 生成一段假设答案（不要求准确），用其 embedding 做向量检索。
  - 仅对抽象问题（`tech_general` 中 query 长度短、无硬实体）启用。
- **M9.3 Neighbor expansion**：
  - 检索到的每条 chunk 自动附带前 1 + 后 1 邻居（可配）。
  - 去重后一起进 rerank 的上下文展示。
- **M9.4 Parent document retrieval**：
  - Chunk 检索命中后，回溯到父 section（同 H2 下的全部 chunks）作为可选展示。
  - 适用场景：runbook / SOP 需要完整步骤。
- **M9.5 Metadata-aware rerank**：
  - Rerank 阶段把 `doc_type`（runbook/troubleshooting 加权）、`section_path`、`workspace_id` 纳入排序特征。
  - 对 `troubleshooting` route，`doc_type=troubleshooting` 的 chunk 得分乘 1.15；对 `runbook_generation` route，`doc_type=runbook` 乘 1.20。
- **M9.6 Route-specific 默认策略**：
  - `tech_general`：hybrid + rerank（默认）
  - `project_specific`：hybrid + neighbor expansion + rerank
  - `troubleshooting`：query_decomposition + hybrid + metadata-rerank
  - `runbook_generation`：hybrid + parent_document + metadata-rerank
- **M9.7 `/lab/compare` 扩展**：
  - 增加策略：`vector_only` / `keyword_only` / `hybrid` / `hybrid_rerank` / `hybrid_hyde` / `hybrid_decomposed` / `hybrid_neighbors` / `hybrid_metadata_rerank`。
  - 请求体加 `use_rewriter: bool`、`enable_neighbors: bool`、`enable_parent_doc: bool`。

**交付物**：

- 四个新检索模块 (`hyde.py` / `decompose.py` / `neighbors.py` / metadata rerank)。
- Lab 页可对比 8 种策略。
- Route-specific 默认策略写入 retriever 路由表。

**验收**：

- 在真实 corpus（M8 完成后）上，至少 1–2 个新策略的 `hit_rate@5` 或 `ndcg@5` 优于 baseline `hybrid_rerank`。
- Query Decomposition 对多条件问题的召回率提升 ≥ 10%。
- Lab 页可视化能明显看出策略间重叠度差异。

---

## 17. Phase D：契约统一、Eval 回流与安全边界

### 17.1 M10 — Trace / SSE / 前端消费契约统一

**目标**：消除当前 `sse_events.pyi`、`chat.py` 流式实现、前端消费三者间的 drift，建立单一事件协议。

**子任务**：

- **M10.1 统一事件枚举**（写入 `docs/contracts/sse_events.pyi`）：
  - `run`：`{run_id, query_id, conversation_id, turn_index}`（原 `conversation` + `run_id` 合并）
  - `reasoning`：`{node, decision, confidence?, reason, metadata?}`
  - `route`：`{route, confidence}`
  - `retrieval`：`{strategy, chunk_count, top_score}`
  - `rerank`：`{input_count, output_count, fallback: bool}`
  - `tool_call`：`{tool, args_preview, call_id}`
  - `tool_result`：`{call_id, status, artifact_preview, duration_ms}`
  - `token`：`{delta: str}`（答案流 token）
  - `citation`：`{index, chunk_uid, document_title, score, quote}`
  - `grounding`：`{critical_claims, aligned, unsupported, refusal_state}`（M5 产出）
  - `done`：`{run_id, final_answer, citations, grounding_report, duration_ms}`
  - `error`：`{type, message_redacted}`
  - `cancelled`：`{run_id, reason}`
- **M10.2 移除临时事件**：
  - 当前 `answer` 事件在 chain_end 一次性发出完整答案——与 `token` 流式 delta 重复，删除。最终答案在 `done` 事件里给出。
  - 心跳事件保留但不进契约枚举。
- **M10.3 后端收敛**：
  - `src/api/routers/chat.py` 的 SSE 映射器重构为「事件类型 → payload schema」查表，不再散在分支里。
  - 单元测试：模拟 LangGraph event stream，断言 SSE 输出事件序列与契约一致。
- **M10.4 前端状态机重写**：
  - `web/src/lib/api.ts` 的 `streamChat` 改为「事件 → 状态机 action」统一分发。
  - Chat 页的 reasoning 面板、citation 卡片、tool call 折叠面板、grounding badge 各自订阅对应事件，不再从 message body 里解析。
  - Cancel / resume 行为统一走 `run` + `cancelled` 事件。

**交付物**：

- 单一事件协议文件 `sse_events.pyi`。
- 后端 SSE 映射器 + 前端状态机。

**验收**：

- SSE 流、cancel 恢复、reasoning 面板、trace 回放共用同一套事件解析。
- 契约测试：每个事件类型至少有一条集成测试覆盖。
- 前端状态机从事件流完整重建 message + citations + reasoning + grounding，无需 fallback 到 REST 拉取。

### 17.2 M11 — Eval 体系与 bad case 回流闭环

**目标**：让 eval 成为开发主驱动，每次调优都能通过 eval 定位提升点和退化点。

**子任务**：

- **M11.1 Chunk remap**：
  - 基于 M8 导出的 `chunk_index.json`，把现有 50 条 eval case 的 `expected_chunk_uids` 重映射到真实 chunk。
  - 无法映射的 case（stub 文档已删除）手动补新 golden chunk。
- **M11.2 Eval case 扩展**（目标 100+ 条）：

  | 类别 | 当前 | 目标 | 新增来源 |
  | --- | --- | --- | --- |
  | tech_general | 10 qa + 8 retrieval | 25 qa + 15 retrieval | K8s / Redis / Prometheus |
  | project_specific | 10 qa + 6 retrieval | 25 qa + 15 retrieval | Airflow / Backstage / FastAPI |
  | troubleshooting | 5 qa + 4 retrieval | 15 qa + 10 retrieval | PagerDuty IR + Airflow troubleshooting |
  | runbook_generation | 3 qa + 2 retrieval | 8 qa + 5 retrieval | PagerDuty SOP |
  | out_of_scope | 2 qa | 7 qa | 明确越界问题 |
  | multi_turn_followup（新） | 0 | 10 qa | M2 多轮场景 |
  | tool_use（新） | 0 | 8 qa | M6 工具链场景 |
  | refusal_clarify（新） | 0 | 5 qa | M5 三态 |

- **M11.3 新指标**：
  - `critical_claim_grounding_rate`：critical claims 被成功对齐到 chunk 的比例。
  - `context_retention_score`：多轮场景下第 N 轮答案是否保留第 1 轮的关键前提（LLM judge）。
  - `follow_up_resolution_score`：follow-up query 是否被 rewriter 正确改写为独立查询（人工标注 + LLM judge）。
  - `tool_chain_completeness`：工具链是否按 plan 完成、artifacts 是否齐全。
  - `runbook_completeness_score`：runbook sections / prerequisites / citations 完整度。
  - 保留现有 `hit_rate@k` / `mrr` / `citation_accuracy` / `refusal_accuracy`。
- **M11.4 Bad case 六层归因**：
  - 当 eval case 失败时，归因到以下六层之一（可多选）：
    - `rewrite`：rewriter 产出 query 导致召回失败。
    - `retrieval`：检索策略或参数问题。
    - `scope`：workspace / scope 选择错误。
    - `grounding`：critical claim 对齐失败。
    - `tool`：工具链失败或 artifact 不足。
    - `refusal`：refusal 决策错误（该答未答 / 不该答却答）。
  - 归因由 evaluator 输出结构化字段，前端 bad case 页面按归因分组展示。
- **M11.5 回流工作流**：
  - 每次调优后运行 eval，新增 `reports/<date>_<phase>.json`。
  - Bad case 页面对每个 case 提供「跳转 trace」+「导出为测试 fixture」按钮。

**交付物**：

- Chunk 重映射后的 eval fixture + 扩展到 100+ 条。
- 扩展后的 evaluator 和新指标。
- 前端 bad case 六层归因视图。

**验收**：

- `python -m scripts.run_eval` 在真实 corpus 上稳定产出全部新指标。
- 至少 1 次 bad case → 调优 → eval 改善的完整闭环演示。
- 文档化「如何加一条 eval case」流程。

### 17.3 M12 — 安全边界、Tool Policy 与未来外联准备

**目标**：在接入真实外部工具前，先把 runtime tool policy、mock/live adapter 分离、审计、降级机制做出来，为 V2+ 外部工具接入留好骨架。

**子任务**：

- **M12.1 Tool policy 框架** `src/agent/tool_policy.py`：
  - `ToolPolicy`：按 `(workspace, tool_name)` 或 `(route, tool_name)` 决定 allow / deny / modify。
  - 支持字段：`max_output_bytes`、`timeout_seconds`、`rate_limit_per_minute`、`circuit_breaker_threshold`、`requires_confirmation`。
  - 接入 M6 的 `before_tool_call` hook：policy 拒绝时返回结构化 `permission_denied` 失败。
- **M12.2 Mock / Live adapter 分离**：
  - 每个工具在 `src/agent/tools/<tool>/` 下提供 `mock.py` + `live.py` + `factory.py`。
  - V1 默认加载 mock 实现，`settings.TOOL_MODE = "mock"`（当前行为）。
  - `live.py` 只定义接口和 stub，V2+ 再填充真实实现。
- **M12.3 审计日志**：
  - 所有工具调用（尤其 live 模式）写入独立 `tool_audit_log` 表（或复用 `trace_events` 加 `audit: true` 标记）。
  - 记录：tool、args（脱敏）、result（脱敏摘要）、policy decision、duration、caller conversation。
- **M12.4 熔断与降级**：
  - 单工具连续失败 ≥ 阈值时，该 session 内熔断，降级到替代工具或直接走 refusal_checker。
  - 熔断状态在 trace 中明确标注。

**交付物**：

- `src/agent/tool_policy.py` + 每个工具的 mock/live 分离目录结构。
- 审计日志机制。

**验收**：

- Mock 模式下所有现有测试通过。
- Live 模式下至少一个工具有 stub 骨架 + policy 拒绝路径测试。
- 熔断机制在单元测试中可触发并降级。

**V1 边界**：本模块只做框架和 mock 路径，不接任何真实外部服务。真实 live 工具留给 V2+。

---

## 18. 里程碑、质量门与验收

### 18.1 里程碑总览

| 里程碑 | Phase | 完成标志 | 依赖 |
| --- | --- | --- | --- |
| **MA** | Phase A 结束 | 多轮连续 5 轮不丢主题；scope 运行时策略可解释；rewrite 前后可追溯；migration 006 上线 | — |
| **MB** | Phase B 结束 | 200+ 真实文档入库；`chunk_index.json` 导出；现有 eval 经 chunk remap 可运行；migration 007 上线（`documents.provenance` + `parent_document_id` + `is_container` + `DocumentStatus.container`） | MA |
| **MC** | Phase C 结束 | Grounding 闭环 + Tool artifact 链 + Runbook 端到端 + 至少 1 个新检索策略优于 baseline；migration 008 上线 | MB |
| **MD** | Phase D 结束 | SSE 单一协议前后端一致；eval 100+ cases + 六层归因；tool policy 框架就位 | MC |

### 18.2 跨 Phase 质量门

每个 Phase 结束执行：

```bash
# 基础质量门
./.venv/Scripts/python.exe -m ruff check src tests scripts alembic
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m scripts.validate_mock_data
./.venv/Scripts/python.exe -m scripts.validate_eval_cases
./.venv/Scripts/python.exe -m scripts.smoke_multi_turn --base-url http://127.0.0.1:8000

# Phase B 额外
./.venv/Scripts/python.exe -m scripts.download_real_docs --source all
./.venv/Scripts/python.exe -m scripts.ingest_docs --workspace project_airflow --dir data/raw/airflow
./.venv/Scripts/python.exe -m scripts.export_chunk_index --output data/eval/chunk_index.json

# Phase C 额外
./.venv/Scripts/python.exe -m scripts.run_eval --output reports/phase-c-baseline.json
pytest tests/integration/test_graph_pipeline.py -k "grounding or tool_chain or runbook"

# Phase D 额外
pytest tests/integration/test_sse_contract.py     # 新增契约测试
./.venv/Scripts/python.exe -m scripts.run_eval --full --output reports/phase-d-final.json
cd web && npm run lint && npm run build
```

### 18.3 统一验收标准（V1 完成时）

- [ ] 多轮连续 5 轮不丢主题、不丢前提、不丢引用来源。
- [ ] `project_specific` / `troubleshooting` 在 Auto scope 下不再误打 `public_tech`。
- [ ] Rewrite / scope / tool chain / grounding 在 trace 中可解释「为何如此」。
- [ ] 真实知识库 200+ 文档、1500+ chunks 可复现入库。
- [ ] SSE 契约统一，前端状态机消费单一事件流。
- [ ] Eval 覆盖单轮、多轮、工具、拒答、runbook，bad case 可六层归因。
- [ ] Tool policy 框架就位，mock/live adapter 分离。

### 18.4 风险与降级

| 风险 | 影响 | 降级方案 |
| --- | --- | --- |
| M1 context runtime 重构破坏现有节点 | Phase A 延期 | 先以 shim 方式接入，旧节点保留，逐步切换 |
| M2 多轮摘要质量不稳定 | follow-up 改写失败 | 降级为「只拼最近 1 轮 query+answer」，不做 LLM 摘要 |
| M8 RST 解析复杂 | Airflow 文档入不了 | 跳过 RST，只用 MD 源（Backstage/FastAPI/K8s/PagerDuty），规模降到 ~180 文档 |
| M8 embedding 成本超预期 | 入库成本上升 | max_files 减半，优先保留 troubleshooting / runbook 类 |
| M5 critical claim 分类误判高 | grounding 报告噪音 | 先用规则（数字/错误码/命令/推荐词）做 v1，LLM judge 留给 M11 完善 |
| M6 tool artifact 串联失败 | 工具链不稳定 | 降级为固定 plan（当前行为），只对 troubleshooting 启用 artifact-driven |
| M9 新检索策略无收益 | Lab 变展示工具 | 保留在 lab 可选，不晋升到主链路，主链路仍用 hybrid_rerank |
| M10 前端状态机重写量大 | Phase D 延期 | 分事件类型增量迁移，旧 REST fallback 保留 1 个版本 |

---

## 19. V2+ 未来演进（不在 V1 范围）

| 方向 | V1 状态 | V2+ 规划 |
| --- | --- | --- |
| Session branching（分支重跑） | 不做 | `parent_query_id` + regenerate 走分支，前端 tree 视图 |
| OpenClaw 风格 control plane | 不做 | 多通道接入（IM / webhook / cron）、session routing、effective tool policy per-channel |
| Live tools | 只做 mock/live 骨架 | 接入真实 service status、log 查询、ticket 系统、MCP server |
| Memory 长期化 | 只做 per-conversation summary | 用户/项目级长期 memory、embedding-based retrieval of past conversations |
| Multi-agent 协作 | 不做 | 专家子 agent（retrieval agent / runbook agent / root-cause agent）+ orchestrator |
| 前端多标签 / 多分支 UI | 不做 | Chat 页支持多 tab、分支对比、diff 视图 |
| 企业身份与权限 | 简单 bearer | OIDC / RBAC、workspace 级 ACL、审计导出 |
| 成本与性能可观测 | 基础 token 计数 | 完整 cost dashboard、per-node latency SLO、慢查询告警 |

















