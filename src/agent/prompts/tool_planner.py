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


def compose_tool_planner_user_prompt(
    *,
    query: str,
    key_entities: list[str],
    selected_project: str | None,
    tools_to_plan: list[str],
    retrieval_lines: list[str] | None = None,
    recent_tool_failures: list[str] | None = None,
    recent_turns: list[dict] | None = None,
    context_summary: str | None = None,
    route: str | None = None,
    compaction_summary: str | None = None,
) -> str:
    context_parts = [f"用户问题: {query}"]
    if route:
        context_parts.append(f"路由: {route}")
    if key_entities:
        context_parts.append(f"关键实体: {', '.join(key_entities)}")
    if selected_project:
        context_parts.append(f"当前项目: {selected_project}")
    context_parts.append(f"需要规划的工具: {', '.join(tools_to_plan)}")
    if recent_turns:
        rendered_turns = []
        for turn in recent_turns:
            user_query = str(turn.get('query') or turn.get('user') or '').strip()
            answer = str(turn.get('answer') or turn.get('assistant') or '').strip()
            tool_facts = turn.get("tool_facts") or []
            if user_query:
                rendered_turns.append(f"User: {user_query}")
            if answer:
                rendered_turns.append(f"Assistant: {answer}")
            if tool_facts:
                rendered_turns.append(f"Tool facts: {'; '.join(str(item) for item in tool_facts)}")
        if rendered_turns:
            context_parts.append(f"最近对话:\n{chr(10).join(rendered_turns)}")
    if context_summary:
        context_parts.append(f"上下文摘要:\n{context_summary}")
    if retrieval_lines:
        context_parts.append(f"证据元数据:\n{chr(10).join(retrieval_lines)}")
    if recent_tool_failures:
        context_parts.append(f"最近工具失败:\n{chr(10).join(recent_tool_failures)}")
    if compaction_summary:
        context_parts.append(f"压缩后的溢出事实:\n{compaction_summary}")
    return "\n".join(context_parts)


def build_tool_planner_messages(
    query: str,
    key_entities: list[str],
    selected_project: str | None,
    tools_to_plan: list[str],
) -> list[dict]:
    return [
        {"role": "system", "content": TOOL_PLANNER_SYSTEM},
        {
            "role": "user",
            "content": compose_tool_planner_user_prompt(
                query=query,
                key_entities=key_entities,
                selected_project=selected_project,
                tools_to_plan=tools_to_plan,
            ),
        },
    ]
