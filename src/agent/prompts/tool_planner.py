"""Tool planner prompt — fixed tool chains + LLM parameter completion."""
from __future__ import annotations

TOOL_PLANNER_SYSTEM = """\
你是 DocWise 工具规划器。根据用户问题和已有证据，补全工具调用参数。

可用工具:
1. query_project_manifest — 查询项目服务注册信息（service_name, owner, SLA, dependencies）
2. query_service_status — 查询服务健康状态（CPU, 内存, 错误率, 活跃告警）
3. query_mock_logs — 查询服务日志（按级别、关键词、时间范围过滤）
4. search_docs — 补充检索文档
5. generate_runbook_draft — 生成 Runbook 草稿

输出严格 JSON 格式:
{
  "tool_params": {
    "query_project_manifest": {"project_name": "...", "service_name": "..."},
    "query_service_status": {"service_name": "..."},
    "query_mock_logs": {"service_name": "...", "time_range": "last_30m", "level": "ERROR", "keywords": ["..."]}
  }
}

规则:
- 从用户问题和 key_entities 中提取 service_name、project_name
- 如果无法确定 service_name，使用 project_name 查 manifest 获取
- time_range 默认 "last_30m"
- level 默认 "ERROR"
- keywords 从问题中提取关键错误信息
"""


def build_tool_planner_messages(
    query: str,
    key_entities: list[str],
    selected_project: str | None,
    tools_to_plan: list[str],
) -> list[dict]:
    context_parts = [f"用户问题: {query}"]
    if key_entities:
        context_parts.append(f"关键实体: {', '.join(key_entities)}")
    if selected_project:
        context_parts.append(f"当前项目: {selected_project}")
    context_parts.append(f"需要规划的工具: {', '.join(tools_to_plan)}")

    return [
        {"role": "system", "content": TOOL_PLANNER_SYSTEM},
        {"role": "user", "content": "\n".join(context_parts)},
    ]
