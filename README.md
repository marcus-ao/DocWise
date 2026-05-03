# DocWise

DocWise 是一个面向企业开发者知识工作的 Agent 项目：用技术文档 RAG、故障排查工具、结构化 trace 和 eval，把“查文档、看状态、问原因、生成处理建议”串成一条可验证的工作流。

## 当前运行边界

| 层级 | 当前实现 |
| --- | --- |
| Python | 3.11，推荐使用仓库内 `.venv` |
| API | FastAPI，入口 `src.api.app:app` |
| Worker | `arq + Redis`，入口 `src.tasks.worker.WorkerSettings` |
| Frontend | Streamlit，入口 `src/frontend/app.py` |
| 数据库 | PostgreSQL + pgvector + tsvector |
| 对象存储 | MinIO，默认 bucket 为 `docwise-documents` |
| 模型 | DeepSeek-compatible chat；DashScope/Qwen embedding 与 rerank |
| 可观测与评估 | 本地 DB trace/eval 为主，Langfuse 可选 |

本地调试推荐：Docker 只跑 `postgres`、`redis`、`minio`；FastAPI、worker、Streamlit 使用 Windows `.venv` 启动。

## 快速启动

先准备 `.env`。本地 `.venv` 调试使用 `.env.local.example`，不要把本地 API/worker 的基础设施地址写成 Docker 服务名：

```powershell
Copy-Item .env.local.example .env
```

真实入库、检索和 Chat 需要在 `.env` 中配置：

```dotenv
DEEPSEEK_API_KEY=...
DASHSCOPE_API_KEY=...
```

启动基础设施、迁移、种子数据和本地服务：

```powershell
docker compose up -d postgres redis minio
.\.venv\Scripts\python.exe -m alembic -c alembic\alembic.ini upgrade head
.\.venv\Scripts\python.exe -m scripts.seed_demo
.\scripts\dev_start.ps1
```

常用地址：

| 服务 | 地址 |
| --- | --- |
| API | http://127.0.0.1:8000 |
| Swagger | http://127.0.0.1:8000/docs |
| Streamlit | http://127.0.0.1:8501 |
| MinIO Console | http://localhost:9001 |

停止本地 API、worker、frontend：

```powershell
.\scripts\dev_stop.ps1
```

## 基础验证

健康检查：

```powershell
curl.exe http://127.0.0.1:8000/healthz
curl.exe http://127.0.0.1:8000/readyz
```

导入 demo 文档：

```powershell
.\.venv\Scripts\python.exe -m scripts.ingest_docs --workspace public_tech --dir data\raw\airflow
```

异步入队模式需要 worker 正在运行：

```powershell
.\.venv\Scripts\python.exe -m scripts.ingest_docs --workspace public_tech --dir data\raw\airflow --enqueue
```

运行 API smoke：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_api.ps1
```

## 质量门

Windows 上如果系统临时目录有权限问题，先使用仓库内临时目录：

```powershell
New-Item -ItemType Directory -Force .\.tmp\pytest | Out-Null
$env:TMP=(Resolve-Path .\.tmp\pytest)
$env:TEMP=$env:TMP
```

运行完整质量门：

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

## 当前已验证状态

- Docker `postgres`、`redis`、`minio` healthy。
- Alembic 当前版本为 `004 (head)`。
- `scripts.seed_demo` 可创建/确认 MinIO bucket、workspace、demo docs、mock/eval 数据。
- `scripts.ingest_docs --workspace public_tech --dir data\raw\airflow` 可将两份 Airflow demo 文档处理到 `ready`。
- `--enqueue` 对已有文档可返回 succeeded job。
- Qwen embedding 返回 2048 维，Qwen rerank 可用，DeepSeek-compatible chat smoke 可用。

## 文档入口

| 需求 | 文档 |
| --- | --- |
| 本地运行、Windows 调试、全功能验收 | `docs/GUIDE.md` |
| 架构、恢复状态、路线图、任务工作包 | `docs/PLAN.md` |
| 编码规范、文件责任边界、Agent 协作规则 | `docs/AGENT.md` |
