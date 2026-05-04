# DocWise AGENT

本文合并 `docs/CODING_STANDARDS.md` 与 `docs/FILE_OWNERSHIP.md`，是当前 Agent/开发者在 DocWise 仓库内协作时的编码规范、文件边界和验证规则。旧文件保留为历史来源，但当前执行以本文为准。

## 1. 工作原则

- 以当前 `src/` 和测试为事实来源，旧规划只做参考。
- 改动要贴近现有模块边界，避免无关重构。
- `.env` 可能含密钥，严禁打印、提交或写入日志。
- 不删除 `data/mock/`、`data/eval/`、env templates、migrations、docs contracts。
- 公共 API、SSE、JSONB、schema 字段使用 `snake_case`。
- 使用绝对 import：`from src...`。
- Windows/PowerShell 命令优先使用 `.venv\Scripts\python.exe -m ...`。

## 2. 异常与错误处理

共享异常定义在 `src/common/exceptions.py`，并由 `src.agent.state` re-export：

| 异常 | 使用场景 |
| --- | --- |
| `RetryableError(backoff_seconds)` | API timeout、429、临时网络/DB/Redis 错误 |
| `NonRetryableError` | schema 错误、embedding 维度不匹配、不支持的 route 或文档类型 |
| `ToolExecutionError(tool_name, message)` | 单个工具失败，不应拖垮整个 Agent run |

Agent 节点应通过 `safe_node` 或等价降级逻辑消化可恢复错误，把错误写入 state/trace，而不是让单个节点异常破坏整个 run。API 路由应返回明确 HTTP 错误或 SSE `error` event。

## 3. Async 规则

| 场景 | 模式 |
| --- | --- |
| 独立 I/O | `asyncio.gather()` |
| 有先后依赖 | 串行 `await` |
| 同步 SDK | `asyncio.to_thread()`，例如 MinIO Python client |
| 外部调用 | 显式 timeout、retry 或降级 |
| 非关键观测 | 内部捕获异常，不能影响主链路 |

示例：

```python
vector_results, keyword_results = await asyncio.gather(
    vector_search.search(...),
    keyword_search.search(...),
)
```

## 4. Import 与文件组织

每个 Python 文件结构：

```python
"""模块简述。"""
from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.models.document import Document
```

规则：

- 标准库、第三方、本项目三段排序。
- 不使用相对 import。
- 避免在模块 import 时发起网络、DB、Redis、MinIO 连接。
- 只在确实能降低复杂度时新增抽象。

## 5. 日志与脱敏

使用 `structlog`：

```python
import structlog

logger = structlog.get_logger(__name__)
```

日志应结构化，避免整段文档内容、API key、token、password、Authorization header。对可能包含敏感信息的字符串使用：

```python
from src.config.redactor import redact_secrets
```

运行日志写入：

- `logs/api/`
- `logs/worker/`
- `logs/web/`
- `logs/scripts/` 如脚本需要

`logs/` 是本地运行产物，应保持 ignored。

## 6. 类型与数据契约

- API 请求/响应使用 Pydantic schema。
- ORM 使用 SQLAlchemy `Mapped`。
- Agent state 使用 `TypedDict`。
- 工具 I/O 使用 Pydantic model 或明确 dict contract。
- 不在 API/SSE/JSONB 里引入 camelCase。
- `DocumentChunk` 是 citation、trace、eval 的最小证据单元。
- embedding 维度为 2048，改维度必须 migration + reindex。

## 7. 测试规范

测试框架为 `pytest` + `pytest-asyncio`。命名：

- 文件：`test_{module_name}.py`
- 函数：`test_{scenario}_{expected_behavior}`

常用质量门：

```powershell
.\.venv\Scripts\python.exe -m scripts.validate_mock_data
.\.venv\Scripts\python.exe -m scripts.validate_eval_cases
.\.venv\Scripts\python.exe -m ruff check src tests scripts alembic
.\.venv\Scripts\python.exe -m pytest -q
```

按风险选择测试范围：

| 改动 | 至少运行 |
| --- | --- |
| chunk/parser/ingestion | `tests/unit/test_chunker.py`, `tests/unit/test_parsers.py`, `tests/integration/test_ingestion_pipeline.py` |
| retrieval/agent | `tests/unit/test_hybrid_retrieval.py`, `tests/unit/test_query_router.py`, 相关 integration |
| API/frontend client | `tests/integration/test_api_endpoints.py` |
| eval/mock | `scripts.validate_mock_data`, `scripts.validate_eval_cases`, `tests/eval/` |
| env/Docker/scripts | 对应 smoke 或 `docs/GUIDE.md` 中运行路径 |

## 8. 当前文件责任边界

这个边界用于减少冲突。它不是禁止协作，而是要求跨边界改动时说明原因、同步契约和补测试。

| 责任域 | 主要路径 | 维护重点 |
| --- | --- | --- |
| Infra/Foundation | `pyproject.toml`, `.gitignore`, `Makefile`, `Dockerfile*`, `docker-compose.yml`, `alembic/`, `src/config/`, `src/db/`, `src/models/`, `src/schemas/` | 环境、schema、迁移、基础连接 |
| LLM/Document/Tasks | `src/llm/`, `src/document/`, `src/tasks/`, `scripts/ingest_docs.py`, `scripts/download_docs.py`, `data/raw/` | 模型封装、文档解析、chunk、embedding、入库、worker |
| Retrieval/Agent | `src/retrieval/`, `src/agent/` | 检索、路由、LangGraph、工具、prompt |
| API/Frontend | `src/api/`, `src/api/client.py`, `web/`, `scripts/smoke_api.ps1` | REST/SSE、依赖注入、前端接口契约、Next.js 客户端 |
| Observability/Eval/Data | `src/observability/`, `data/mock/`, `data/eval/`, `scripts/generate_mock_data.py`, `scripts/validate_*`, `scripts/export_chunk_index.py` | trace、metrics、eval、fixtures |
| Docs/Contracts | `docs/`, `docs/contracts/` | 当前事实、接口契约、恢复记录 |

## 9. 共享文件规则

- `src/__init__.py` 和各目录 `__init__.py` 只保留必要导出，不制造循环 import。
- `pyproject.toml` 新增依赖要说明用途、版本范围、替代方案和测试影响。
- `.env.example`、`.env.local.example`、`.env.docker.example` 改动必须同步 `docs/GUIDE.md`。
- Alembic migration 只能前进，不手改已被使用的历史 migration，除非是当前恢复未提交状态下的明确修复。
- `docs/contracts/` 变更要同时检查消费者：API、frontend、agent、eval、tests。

## 10. 跨边界改动流程

如果需要修改非本责任域文件：

1. 先确认是否真的需要修改，优先使用已有接口。
2. 在提交说明或最终报告中写清楚原因。
3. 同步更新契约、文档或测试。
4. 跑受影响路径的最小测试。
5. 不回退他人已有改动；遇到冲突先读懂再整合。

## 11. Git 与提交信息

推荐格式：

```text
<type>(<scope>): <subject>

<body>
```

type：`feat` / `fix` / `refactor` / `test` / `docs` / `chore`

scope 示例：`models` / `schemas` / `retrieval` / `agent` / `api` / `frontend` / `eval` / `infra`

示例：

```text
fix(document): ensure MinIO bucket before ingestion upload
docs(guide): merge Windows local recovery flow into guide
test(eval): lock mock fixture validation
```

## 12. 完成前自检

- 是否只改了必要文件？
- 是否没有泄露 `.env` 或日志中的 secret？
- 是否保持 API/SSE/JSONB 字段为 `snake_case`？
- 是否同步了 `docs/GUIDE.md`、`docs/PLAN.md` 或 contracts？
- 是否运行了与改动风险匹配的测试？
- 是否在最终说明中列出无法验证的部分？
