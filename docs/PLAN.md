# DocWise PLAN

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

## 9. 下一阶段开发方向

当前项目已完成核心 RAG + Agent 闭环（121 tests passing），进入功能深化和展示质量提升阶段。下一阶段聚焦三大方向：

### 方向一：前端重构 — Next.js + shadcn/ui 专业级 UI

将 Streamlit 管理台替换为独立 Next.js 前端，达到业内主流 AI 产品的展示水准。参考 Perplexity（引用展示）、Langfuse（trace 可视化）、Promptfoo（eval 仪表盘）的 UI 模式。

### 方向二：RAG 深化 — 检索可视化 + 多轮对话 + Agent 决策透明化

- 检索策略 A/B 对比实验室
- 多轮对话上下文记忆
- Agent 每步决策理由实时展示
- 高级检索增强（HyDE、Query Decomposition、Chunk 关联）

### 方向三：真实知识库 — 公开技术文档获取与入库

用真实的 Apache Airflow / Backstage / FastAPI / K8s / PagerDuty 文档替换当前 stub 文件，建立 200-300 文档、~2000 chunks 的中等规模知识库，使 eval 指标基于真实数据。

详细规划见 Section 13-16。

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

这一节吸收旧 `docs/TASK.md` 的工作包拆解，但按当前仓库状态重新归并。后续继续开发时，以这里的责任域和验证门为准。

| 工作包 | 当前主要路径 | 当前状态 | 下一步关注 |
| --- | --- | --- | --- |
| WP-01 Infra/Foundation | `pyproject.toml`, Dockerfile, Compose, Alembic, `src/config/`, `src/db/`, `src/models/`, `src/schemas/` | 已恢复到可运行，本地 infra health、Alembic head、seed 基线可用 | 新增 conversations 表迁移、前端 Docker 集成 |
| WP-02 LLM/Document/Tasks | `src/llm/`, `src/document/`, `src/tasks/`, `scripts/ingest_docs.py`, `data/raw/` | chunker、ingestion、MinIO bucket、embedding、worker 路径已恢复 | RST parser、真实文档批量入库、大文件处理 |
| WP-03 Retrieval/Agent | `src/retrieval/`, `src/agent/` | hybrid retrieval、rerank fallback、LangGraph 12 节点主链路完整 | 多轮对话 context_loader、reasoning 事件、检索实验室后端、HyDE |
| WP-04 API/Frontend | `src/api/`, `src/frontend/`, `web/` (新增) | FastAPI 路由完整，Streamlit 管理台存在 | Next.js 前端 5 页重构、新增 API 端点（conversations/timeline/trends/compare/chunks） |
| WP-05 Observability/Eval/Data | `src/observability/`, `data/mock/`, `data/eval/` | mock/eval fixture gate 通过，eval cases 为 20 retrieval + 30 qa | 真实文档 eval case 对齐、扩展到 80-100 条、趋势追踪 |
| Docs/Contracts | `docs/`, `docs/contracts/` | GUIDE/PLAN/AGENT 已完成当前化合并 | 后续改动必须同步权威文档 |

### 合并与验证顺序

1. 真实知识库（Phase 1）先行：下载脚本 → RST parser → 批量入库 → eval 对齐。
2. RAG 深化（Phase 2）：conversations 表 → context_loader → reasoning 事件 → 检索实验室后端。
3. 前端重构（Phase 3）：Next.js 初始化 → Chat → Docs → Traces → Eval → Lab。
4. 每个 Phase 完成后运行完整质量门（pytest + ruff + fixture validation + smoke）。

### 当前验收清单

- [x] Docker `postgres` / `redis` / `minio` healthy。
- [x] Alembic 当前版本为 `004 (head)`。
- [x] `scripts.seed_demo` 成功并创建/确认 MinIO bucket。
- [x] `data/mock/` 与 `data/eval/` validation 通过。
- [x] `ruff check src tests scripts alembic` 通过。
- [x] `pytest -q` 当前为 `121 passed`。
- [x] `scripts.ingest_docs --workspace public_tech --dir data\raw\airflow` 同步入库到 ready。
- [x] `scripts.ingest_docs --workspace public_tech --dir data\raw\airflow --enqueue` 返回已有 succeeded job。
- [ ] 真实文档 200+ 入库，hit_rate@5 > 75%。
- [ ] 多轮对话 + reasoning 事件可消费。
- [ ] Next.js 前端 5 页可用。
- [ ] Eval 仪表盘有真实数据趋势。

---

## Part II: 下一阶段开发规划

---

## 13. 前端重构：Next.js + shadcn/ui 专业级 UI

### 13.1 技术选型与架构

| 层 | 选择 | 理由 |
|---|---|---|
| 框架 | Next.js 14 (App Router) + TypeScript | SSR/SSG 灵活、生态成熟、体现全栈能力 |
| UI 库 | shadcn/ui + Tailwind CSS + Radix UI | 可定制、无运行时开销、设计系统一致性 |
| 流式 | Vercel AI SDK `useChat` hook | 原生 SSE 消费、token 级流式渲染 |
| 图表 | Recharts (eval) + 自定义 SVG (trace waterfall) | 轻量、React 原生 |
| 状态 | Zustand + TanStack Query (React Query) | 轻量客户端状态 + 服务端缓存 |
| 部署 | Docker 容器化，集成现有 compose | 一键启动全栈 |

### 13.2 页面设计（5 个核心页面）

**Page 1: Chat 对话页（Perplexity 风格）**

- 左侧边栏：workspace 选择器 + 对话历史列表 + 新建对话
- 中间主区域：
  - 流式回答渲染 + 内联编号引用 `[1][2][3]`
  - 引用卡片区（答案下方）：文档名、chunk 位置、相关性分数、点击展开原文
  - 工具调用折叠面板：实时展示 tool_planner → tool_executor 过程
  - Follow-up 建议按钮（基于当前回答生成 2-3 个追问）
- 右侧面板（可折叠）：
  - Agent 决策透明化：路由理由、检索策略、证据评估
  - 实时 trace 摘要：各阶段耗时、token 消耗
- 底部：反馈按钮（thumbs up/down + 文字修正）

**Page 2: 文档管理页**

- 拖拽上传区 + 批量上传（支持 PDF/DOCX/MD/RST）
- 文档列表表格：workspace / 类型 / 状态 / chunk 数 / 进度条
- 实时 job 状态更新（轮询 + 乐观更新）
- 文档预览：点击查看原文 + chunk 边界高亮
- 操作：重新索引、删除、移动 workspace

**Page 3: Trace 观测页（Langfuse 风格）**

- 查询历史列表（可搜索、按 route/workspace/时间筛选）
- 单条 trace 详情：
  - Waterfall/Gantt 时间线：每个 Agent 节点的执行时长横条
  - 节点详情面板：点击节点查看输入/输出/token/cost
  - 树形结构展示父子嵌套关系
  - 颜色编码：路由(蓝)、检索(绿)、工具(橙)、生成(紫)、验证(灰)
- 统计摘要：平均延迟、token 分布、路由分布饼图

**Page 4: Eval 评估页（Promptfoo 风格）**

- 顶部指标卡：Hit Rate、MRR、Citation Accuracy、Faithfulness、Refusal Accuracy
- 趋势图：指标随 eval run 的变化折线图（run-over-run 对比）
- 分组视图：按 route / workspace / bad_case_type 分组柱状图
- Bad case 表格：问题 / 期望 / 实际 / 差异原因 / 跳转 trace
- 检索策略 A/B 对比：纯向量 vs 混合 vs +rerank 的效果对比热力图

**Page 5: 检索实验室（Retrieval Lab）**

- 输入查询 + workspace 选择 + 策略多选
- 实时展示多种检索策略的结果并排对比
- Chunk 级别相关性分数热力图
- 策略间重叠度 Venn 图
- 参数调节面板：top_k、rerank_top_k、RRF k 值（实时刷新结果）

### 13.3 前端目录结构

```
web/
├── package.json
├── next.config.ts
├── tailwind.config.ts
├── tsconfig.json
├── Dockerfile
├── src/
│   ├── app/
│   │   ├── layout.tsx              # 全局布局（侧边栏 + 主区域）
│   │   ├── page.tsx                # 首页/仪表盘概览
│   │   ├── chat/
│   │   │   └── page.tsx
│   │   ├── documents/
│   │   │   └── page.tsx
│   │   ├── traces/
│   │   │   ├── page.tsx            # trace 列表
│   │   │   └── [runId]/page.tsx    # 单条 trace 详情
│   │   ├── eval/
│   │   │   └── page.tsx
│   │   └── lab/
│   │       └── page.tsx            # 检索实验室
│   ├── components/
│   │   ├── ui/                     # shadcn/ui 基础组件
│   │   ├── layout/
│   │   │   ├── sidebar.tsx
│   │   │   ├── header.tsx
│   │   │   └── theme-toggle.tsx
│   │   ├── chat/
│   │   │   ├── message-list.tsx
│   │   │   ├── message-bubble.tsx
│   │   │   ├── citation-card.tsx
│   │   │   ├── tool-call-panel.tsx
│   │   │   └── agent-reasoning.tsx
│   │   ├── documents/
│   │   │   ├── upload-zone.tsx
│   │   │   ├── document-table.tsx
│   │   │   └── chunk-viewer.tsx
│   │   ├── traces/
│   │   │   ├── trace-timeline.tsx
│   │   │   ├── node-detail.tsx
│   │   │   └── waterfall-chart.tsx
│   │   ├── eval/
│   │   │   ├── metric-cards.tsx
│   │   │   ├── trend-chart.tsx
│   │   │   ├── bad-case-table.tsx
│   │   │   └── comparison-heatmap.tsx
│   │   └── lab/
│   │       ├── retrieval-compare.tsx
│   │       └── vector-viz.tsx
│   ├── lib/
│   │   ├── api-client.ts           # 后端 API 封装（fetch + error handling）
│   │   ├── sse-client.ts           # SSE 流式消费封装
│   │   ├── utils.ts                # 通用工具函数
│   │   └── constants.ts            # API URL、颜色映射等
│   ├── hooks/
│   │   ├── use-chat-stream.ts      # 流式聊天 hook
│   │   ├── use-trace.ts            # trace 数据 hook
│   │   └── use-eval.ts             # eval 数据 hook
│   ├── stores/
│   │   ├── chat-store.ts           # 对话状态（Zustand）
│   │   └── workspace-store.ts      # workspace 选择状态
│   └── types/
│       ├── api.ts                   # API 响应类型
│       ├── chat.ts                  # 聊天相关类型
│       └── trace.ts                 # trace 相关类型
└── public/
    └── favicon.ico
```

### 13.4 后端 API 适配

现有 FastAPI 后端 API 基本满足前端需求，需要补充以下端点：

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/v1/chat/conversations` | GET | 对话列表（支持分页） |
| `/api/v1/chat/conversations/{id}` | GET | 单个对话的完整消息历史 |
| `/api/v1/traces/{run_id}/timeline` | GET | 时间线格式的 trace 数据（waterfall 渲染用） |
| `/api/v1/eval/trends` | GET | 指标趋势数据（按 run 聚合） |
| `/api/v1/lab/compare` | POST | 检索策略对比（多策略并行执行） |
| `/api/v1/documents/{id}/chunks` | GET | 文档 chunk 列表（含位置和分数） |
| `/api/v1/workspaces` | GET | workspace 列表（前端选择器用） |

### 13.5 Docker 集成

```yaml
# docker-compose.yml 新增 service
web:
  build:
    context: ./web
    dockerfile: Dockerfile
  ports:
    - "3000:3000"
  environment:
    - NEXT_PUBLIC_API_URL=http://backend:8000
  depends_on:
    backend:
      condition: service_healthy
```

Streamlit 前端保留为 admin/debug 工具，不再作为主要用户界面。

---

## 14. RAG 深化：检索可视化 + 多轮对话 + Agent 决策透明化

### 14.1 检索质量可视化 + A/B 对比

**目标**: 让用户和开发者直观看到不同检索策略的效果差异，支持参数调优决策。

**后端实现**:

```python
# src/api/routers/lab.py
class CompareRequest(BaseModel):
    query: str
    workspace_ids: list[str]
    strategies: list[Literal["vector_only", "keyword_only", "hybrid_rrf", "hybrid_rerank"]]
    top_k: int = 10

class CompareResponse(BaseModel):
    results: dict[str, list[ScoredChunk]]    # 策略 → 结果列表
    overlap_matrix: dict[str, dict[str, float]]  # 策略间重叠度
    timing: dict[str, float]                 # 各策略耗时 ms
    total_unique_chunks: int
```

**执行流程**:
1. 接收 query + 策略列表
2. 并行执行各策略（asyncio.gather）
3. 计算策略间 chunk 重叠度（Jaccard 系数）
4. 返回结构化对比数据

**前端渲染**:
- 并排结果表格：每列一个策略，行为 chunk，高亮重叠项
- 分数分布直方图：各策略的 score 分布对比
- 重叠度热力图：策略两两之间的 Jaccard 系数矩阵
- 耗时对比条形图

### 14.2 多轮对话 + 上下文记忆

**目标**: 支持 follow-up 问题，自动引用之前的检索结果，维持对话连贯性。

**数据模型变更**:

```python
# src/models/conversation.py (新增)
class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[str | None]
    title: Mapped[str]              # 自动从首条消息生成
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
    message_count: Mapped[int] = mapped_column(default=0)

# queries 表新增字段
conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id"))
turn_index: Mapped[int] = mapped_column(default=0)
```

**Agent 图变更**:

```
START
  → input_normalizer
  → context_loader (新增)     ← 加载对话历史，生成摘要
  → query_router
  → scope_selector
  → query_rewriter            ← 注入对话摘要，改写为独立查询
  → hybrid_retriever
  → ...（后续不变）
```

`context_loader` 节点逻辑：
1. 从 DB 加载 conversation_id 对应的最近 5 轮 (query, answer, citations)
2. 调用 LLM 生成 ≤200 字的对话摘要
3. 写入 `state.conversation_history` 和 `state.context_summary`
4. `query_rewriter` 使用摘要将 follow-up 改写为独立查询

**SSE 新增事件**:

```
event: conversation  data: {"conversation_id": "uuid", "title": "Airflow task 失败排查"}
```

### 14.3 Agent 决策透明化

**目标**: 实时展示 Agent 每一步的决策理由，让用户理解"为什么这样回答"。

**实现方案**:

每个 Agent 节点在执行后写入 reasoning 事件：

```python
# src/agent/nodes/query_router.py
async def query_router(state: AgentState) -> AgentState:
    route, confidence, reason = await classify_query(state["original_query"])
    state["route"] = route
    state["trace_events"].append({
        "type": "reasoning",
        "node": "query_router",
        "decision": route,
        "confidence": confidence,
        "reason": reason,  # e.g. "用户提到'失败'和'排查'，匹配故障排查模式"
        "timestamp": now_ms(),
    })
    return state
```

**SSE reasoning 事件流**:

```
event: reasoning  data: {"node": "query_router", "decision": "troubleshooting", "confidence": 0.92, "reason": "用户提到'失败'和'排查'，匹配故障排查模式"}
event: reasoning  data: {"node": "scope_selector", "decision": "project_airflow+public_tech", "reason": "故障排查路由，选择项目+公共知识库"}
event: reasoning  data: {"node": "evidence_validator", "decision": "insufficient", "reason": "最高 rerank 分数 0.25 < 阈值 0.3，需要工具补充证据"}
event: reasoning  data: {"node": "tool_planner", "decision": "query_mock_logs", "reason": "需要查看 Airflow worker 最近日志确认错误类型"}
```

**前端渲染**:
- 右侧面板实时追加决策卡片
- 每张卡片：节点图标 + 决策结果 + 理由文本 + 置信度进度条
- 可折叠/展开，默认展示最近 3 步

### 14.4 检索增强（P2 实验性）

以下功能在检索实验室中作为可开关的实验选项：

**Query Decomposition（查询分解）**:
- 复杂问题拆分为 2-3 个子问题
- 各子问题独立检索
- 合并去重后送入 reranker
- 适用场景：多条件问题（"Airflow 在 K8s 上部署时 task 失败如何排查"）

**HyDE（假设文档嵌入）**:
- LLM 先生成一段假设性答案（不需要准确）
- 用假设答案的 embedding 做向量检索
- 适用场景：抽象问题（"微服务架构的最佳实践"）

**Chunk 上下文扩展**:
- 检索到的 chunk 自动关联前后相邻 chunk
- 扩展窗口：前 1 + 后 1（可配置）
- 避免截断导致的上下文丢失

**Parent Document Retrieval**:
- chunk 检索后，回溯到父文档级别
- 返回更完整的段落上下文
- 适用场景：需要完整步骤的 runbook/SOP

---

## 15. 真实知识库构建：公开技术文档获取与入库

### 15.1 文档来源与下载策略

| 来源 | Workspace | 预计文档数 | 格式 | 下载方式 | 许可证 |
|------|-----------|-----------|------|----------|--------|
| Apache Airflow docs | project_airflow | ~80 | RST/MD | git sparse-checkout `docs/apache-airflow/` | Apache-2.0 |
| Backstage docs + ADRs | project_backstage | ~60 | MD | git sparse-checkout `docs/` | Apache-2.0 |
| FastAPI docs (en) | project_fastapi | ~50 | MD | git sparse-checkout `docs/en/docs/` | MIT |
| Kubernetes troubleshooting | public_tech | ~30 | MD | git sparse-checkout `content/en/docs/tasks/debug/` | CC-BY-4.0 |
| PagerDuty Incident Response | public_tech | ~20 | MD | git clone（小仓库） | Apache-2.0 |
| Redis docs (精选) | public_tech | ~15 | MD | git sparse-checkout | BSD-3 |
| Prometheus docs (精选) | public_tech | ~10 | MD | git sparse-checkout | Apache-2.0 |

**总计**: ~265 文档，预计 ~2000 chunks，embedding 成本约 ¥5-10（Qwen text-embedding-v4）

### 15.2 下载脚本设计

```python
# scripts/download_real_docs.py

SOURCES = [
    {
        "name": "airflow",
        "repo": "https://github.com/apache/airflow.git",
        "branch": "main",
        "sparse_paths": ["docs/apache-airflow/"],
        "file_filter": ["*.rst", "*.md"],
        "exclude_patterns": ["_build/", "changelog/", "spelling_wordlist"],
        "output_dir": "data/raw/airflow/",
        "workspace": "project_airflow",
        "max_files": 80,
    },
    {
        "name": "backstage",
        "repo": "https://github.com/backstage/backstage.git",
        "branch": "master",
        "sparse_paths": ["docs/"],
        "file_filter": ["*.md"],
        "exclude_patterns": ["CHANGELOG", "node_modules/"],
        "output_dir": "data/raw/backstage/",
        "workspace": "project_backstage",
        "max_files": 60,
    },
    {
        "name": "fastapi",
        "repo": "https://github.com/fastapi/fastapi.git",
        "branch": "master",
        "sparse_paths": ["docs/en/docs/"],
        "file_filter": ["*.md"],
        "exclude_patterns": ["release-notes.md"],
        "output_dir": "data/raw/fastapi-docs/",
        "workspace": "project_fastapi",
        "max_files": 50,
    },
    {
        "name": "kubernetes-debug",
        "repo": "https://github.com/kubernetes/website.git",
        "branch": "main",
        "sparse_paths": ["content/en/docs/tasks/debug/"],
        "file_filter": ["*.md"],
        "exclude_patterns": [],
        "output_dir": "data/raw/k8s-troubleshooting/",
        "workspace": "public_tech",
        "max_files": 30,
    },
    {
        "name": "pagerduty-ir",
        "repo": "https://github.com/PagerDuty/incident-response-docs.git",
        "branch": "master",
        "sparse_paths": ["docs/"],
        "file_filter": ["*.md"],
        "exclude_patterns": [],
        "output_dir": "data/raw/pagerduty-ir/",
        "workspace": "public_tech",
        "max_files": 20,
    },
    {
        "name": "redis-docs",
        "repo": "https://github.com/redis/redis-doc.git",
        "branch": "master",
        "sparse_paths": ["docs/"],
        "file_filter": ["*.md"],
        "exclude_patterns": [],
        "output_dir": "data/raw/redis-docs/",
        "workspace": "public_tech",
        "max_files": 15,
    },
    {
        "name": "prometheus-docs",
        "repo": "https://github.com/prometheus/docs.git",
        "branch": "main",
        "sparse_paths": ["content/docs/"],
        "file_filter": ["*.md"],
        "exclude_patterns": [],
        "output_dir": "data/raw/prometheus-docs/",
        "workspace": "public_tech",
        "max_files": 10,
    },
]
```

**下载流程**:
1. 对每个 source 执行 git sparse-checkout（避免 clone 整个大仓库）
2. 按 file_filter 筛选，按 exclude_patterns 排除
3. 按 max_files 截断（优先保留文件大小适中的）
4. 复制到 output_dir，保留相对路径结构
5. 生成 `data/raw/manifest.json` 记录来源、版本、文件数

### 15.3 文档处理增强

当前 parser 支持 MD/PDF/DOCX。真实文档引入后需要扩展：

**RST Parser（新增）**:
- Airflow 文档大量使用 reStructuredText
- 使用 `docutils` 或 `rst-to-myst` 转换为 Markdown 后复用现有 chunker
- 保留标题层级、代码块、表格结构

**大文件预处理**:
- 超过 30KB 的文件按 H1/H2 标题预分割为子文档
- 每个子文档独立入库，保留 `parent_doc_id` 关联
- 避免单个 chunk 跨越不相关的 section

**元数据提取增强**:
- 从文件路径推断 `section_path`（如 `airflow/configuration/logging.rst` → `configuration > logging`）
- 从 frontmatter/RST 元数据提取 `title`、`tags`、`version`
- 自动标注 `doc_type`：tutorial / reference / troubleshooting / adr / runbook

**去重策略**:
- 入库前计算 content_hash（SHA-256 of normalized text）
- 同 workspace 内 content_hash 重复则跳过
- 跨 workspace 允许重复（同一文档可能属于多个知识域）

### 15.4 Eval Case 对齐

当前 50 个 eval case 中部分引用了不存在的 chunk_uid。真实文档入库后需要：

**Step 1: 导出实际 chunk 索引**
```bash
python -m scripts.export_chunk_index --output data/eval/chunk_index.json
```

**Step 2: 更新 retrieval_golden.jsonl**
- 将 expected_chunk_uids 映射到实际入库的 chunk
- 对无法映射的 case，手动标注新的 golden chunk

**Step 3: 扩展 eval case**

| 类别 | 当前数量 | 目标数量 | 新增来源 |
|------|---------|---------|---------|
| tech_general | 10 qa + 8 retrieval | 25 qa + 15 retrieval | K8s/Redis/Prometheus 文档 |
| project_specific | 10 qa + 6 retrieval | 25 qa + 15 retrieval | Airflow/Backstage/FastAPI 文档 |
| troubleshooting | 5 qa + 4 retrieval | 15 qa + 10 retrieval | PagerDuty IR + Airflow troubleshooting |
| runbook_generation | 3 qa + 2 retrieval | 8 qa + 5 retrieval | PagerDuty + enterprise SOPs |
| out_of_scope | 2 qa | 7 qa | 明确超出范围的问题 |
| multi_turn (新增) | 0 | 10 qa | 多轮对话场景 |
| **总计** | **50** | ****100+** | — |

**Step 4: 基线指标建立**
- 真实文档入库后立即运行完整 eval
- 记录基线指标作为后续调优的参照
- 目标：hit_rate@5 > 75%, citation_accuracy > 70%

---

## 16. 实施路线图与里程碑

### 16.1 Phase 1: 真实知识库（Day 1-4）

| Day | 任务 | 预计耗时 | 产出 | 验证 |
|-----|------|---------|------|------|
| 1 | 实现 `scripts/download_real_docs.py`（git sparse-checkout） | 2h | 下载脚本 |  |
| 1 | 实现 RST parser（docutils → markdown → 复用 chunker） | 2h | `src/document/rst_parser.py` |  |
| 1 | 执行下载，获取 ~265 文档到 `data/raw/` | 1h | 文档文件 | 文件数 ≥ 200 |
| 2 | 大文件预分割 + 元数据提取增强 | 2h | parser 增强 |  |
| 2 | 批量入库全部文档（分 workspace 执行） | 2h | DB chunks | chunk 数 ≥ 1500 |
| 2 | Chunk 质量抽检（随机 20 条人工检查分割质量） | 1h | 质量报告 |  |
| 3 | 导出 chunk_index + 更新 retrieval_golden.jsonl | 2h | eval fixtures |  |
| 3 | 扩展 eval case 到 80+ 条 | 2h | `data/eval/*.jsonl` | validation 通过 |
| 3 | 运行完整 eval，建立基线指标 | 1h | 基线报告 | hit_rate@5 记录 |
| 4 | 检索参数调优（top_k、chunk_size、RRF k、rerank threshold） | 3h | 参数配置 |  |
| 4 | 重新运行 eval，对比调优前后 | 1h | 对比报告 | hit_rate@5 > 75% |

**Phase 1 里程碑 (M1)**: 200+ 真实文档入库，eval 基线建立，hit_rate@5 > 75%

---

### 16.2 Phase 2: RAG 深化（Day 5-9）

| Day | 任务 | 预计耗时 | 产出 | 验证 |
|-----|------|---------|------|------|
| 5 | 新增 `conversations` 表 + Alembic 迁移 | 1h | migration 005 |  |
| 5 | 实现 `context_loader` 节点 | 2h | `src/agent/nodes/context_loader.py` |  |
| 5 | 更新 `query_rewriter` 注入对话摘要 | 1.5h | rewriter 增强 |  |
| 5 | 更新 chat API 支持 conversation_id | 1.5h | API 变更 | 多轮对话 smoke |
| 6 | 各节点添加 reasoning 事件写入 | 2h | nodes 更新 |  |
| 6 | SSE 新增 reasoning 事件类型 | 1h | streaming 增强 |  |
| 6 | 端到端测试：reasoning 事件可通过 SSE 消费 | 1h | 集成测试 | SSE 事件验证 |
| 7 | 实现 `POST /api/v1/lab/compare` 端点 | 2h | `src/api/routers/lab.py` |  |
| 7 | 实现多策略并行执行逻辑 | 2h | retrieval 增强 |  |
| 7 | 实现重叠度计算 + 响应格式 | 1h | lab 完整 | compare API smoke |
| 8 | 实现 HyDE 检索策略 | 2h | `src/retrieval/hyde.py` |  |
| 8 | 实现 Query Decomposition | 2h | `src/retrieval/decompose.py` |  |
| 8 | 实现 Chunk 上下文扩展 | 1.5h | retriever 增强 |  |
| 9 | 将新策略集成到 lab compare | 1h | lab 扩展 |  |
| 9 | 运行 eval 验证新策略效果 | 2h | eval 报告 | 对比基线 |
| 9 | 新增多轮对话 eval case (10 条) | 2h | eval fixtures | validation 通过 |

**Phase 2 里程碑 (M2)**: 多轮对话可用，reasoning 事件可消费，检索实验室后端完整，eval 指标对比基线有提升

---

### 16.3 Phase 3: Next.js 前端（Day 10-17）

| Day | 任务 | 预计耗时 | 产出 | 验证 |
|-----|------|---------|------|------|
| 10 | Next.js 项目初始化 + shadcn/ui + Tailwind + Docker | 2h | `web/` 骨架 |  |
| 10 | 全局布局（侧边栏 + header + theme toggle） | 2h | layout 组件 |  |
| 10 | API client + SSE client 封装 | 2h | `lib/` 工具 | 连通后端 |
| 11 | Chat 页面：消息列表 + 流式渲染 + 输入框 | 3h | chat 基础 |  |
| 11 | Chat 页面：引用卡片 + 内联编号引用 | 2h | citation 组件 |  |
| 11 | Chat 页面：工具调用折叠面板 | 1.5h | tool-call 组件 | 完整对话流 |
| 12 | Chat 页面：Agent reasoning 右侧面板 | 2h | reasoning 组件 |  |
| 12 | Chat 页面：对话历史列表 + 多轮对话 | 2h | conversation UI |  |
| 12 | Chat 页面：workspace 选择器 + follow-up 建议 | 1.5h | 辅助组件 | Chat 页完整 |
| 13 | 文档管理页：上传区 + 文档表格 + 状态更新 | 3h | documents 页 |  |
| 13 | Trace 页面：查询历史列表 + 筛选 | 2h | traces 列表 |  |
| 13 | Trace 页面：waterfall 时间线 + 节点详情 | 2.5h | trace 详情 | Trace 页完整 |
| 14 | Eval 页面：指标卡 + 趋势折线图 | 2h | eval 概览 |  |
| 14 | Eval 页面：bad case 表格 + 分组视图 | 2h | eval 详情 |  |
| 14 | Eval 页面：策略对比热力图 | 1.5h | comparison 组件 | Eval 页完整 |
| 15 | 检索实验室：查询输入 + 多策略对比表格 | 2.5h | lab 基础 |  |
| 15 | 检索实验室：分数热力图 + 重叠度可视化 | 2h | lab 可视化 |  |
| 15 | 检索实验室：参数调节面板 | 1.5h | lab 交互 | Lab 页完整 |
| 16 | 响应式适配（移动端 / 平板） | 2h | 响应式 |  |
| 16 | 暗色模式完善 | 1.5h | theme |  |
| 16 | 加载状态、错误处理、空状态 | 2h | UX 打磨 |  |
| 17 | 端到端集成测试（全流程 smoke） | 2h | E2E 验证 |  |
| 17 | Demo 数据准备 + 截图 | 1.5h | demo 资产 |  |
| 17 | Docker Compose 全栈启动验证 | 1.5h | 部署验证 | M4 达成 |

**Phase 3 里程碑 (M3/M4)**:
- M3 (Day 13): Chat + Docs + Traces 三页可用
- M4 (Day 17): 5 页全部可用，eval 仪表盘有真实数据，Docker 一键启动

---

### 16.4 里程碑总览

| 里程碑 | 预计完成 | 完成标志 | 依赖 |
|--------|---------|---------|------|
| M1: 真实知识库就绪 | Day 4 | 200+ 文档入库，hit_rate@5 > 75% | — |
| M2: RAG 深化完成 | Day 9 | 多轮对话 + reasoning + 检索实验室后端 | M1 |
| M3: 前端 MVP | Day 13 | Chat + Docs + Traces 三页可用 | M2 |
| M4: 完整交付 | Day 17 | 5 页全部可用，Docker 全栈一键启动 | M3 |

### 16.5 质量门（每个 Phase 结束时执行）

```bash
# 基础质量门
ruff check src tests scripts alembic
pytest -q
python -m scripts.validate_mock_data
python -m scripts.validate_eval_cases

# Phase 1 额外
python -m scripts.ingest_docs --workspace public_tech --dir data/raw/k8s-troubleshooting
python -m scripts.run_eval --output reports/baseline.json

# Phase 2 额外
pytest tests/integration/test_graph_pipeline.py -k "multi_turn or reasoning"
curl -N http://localhost:8000/api/v1/chat/stream  # 验证 reasoning 事件

# Phase 3 额外
cd web && npm run build && npm run lint
docker-compose up --build  # 全栈启动验证
```

### 16.6 风险与降级

| 风险 | 影响 | 降级方案 |
|------|------|----------|
| Next.js 开发周期超预期 | 前端交付延迟 | 优先完成 Chat + Traces 两页核心页面，Lab 页降级为 P2 |
| 真实文档质量差（RST 解析问题） | chunk 质量低 | 跳过 RST，只用 MD 文档（Backstage/FastAPI/K8s/PagerDuty） |
| HyDE/Decomposition 效果不明显 | 检索增强无收益 | 保留为实验室可选项，不影响主流程 |
| 多轮对话摘要质量不稳定 | follow-up 改写失败 | 降级为简单拼接最近 1 轮 query+answer，不做 LLM 摘要 |
| Embedding 成本超预期 | 入库成本上升 | 减少文档数到 150，优先保留与 eval case 对应的文档 |
| 前端 SSE 兼容性问题 | 流式渲染异常 | 降级为轮询模式（每 500ms 拉取最新状态） |