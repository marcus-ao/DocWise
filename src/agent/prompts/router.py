"""Query router prompt — rule-based + LLM JSON classification."""
from __future__ import annotations

ROUTER_SYSTEM_PROMPT = """\
你是 DocWise 的查询路由器。根据用户问题判断路由类型，输出严格 JSON。

路由类型:
- tech_general: 通用技术/框架/部署问题（K8s、Docker、数据库、编程语言等）
- project_specific: 项目内部资料、架构、SOP、负责人、SLA 等
- troubleshooting: 故障排查、异常诊断、日志分析、错误码排查
- runbook_generation: 生成 SOP/Runbook 草稿
- out_of_scope: 非技术问题、闲聊、危险请求、与项目完全无关

输出格式（严格 JSON，不要多余文字）:
{
  "route": "tech_general|project_specific|troubleshooting|runbook_generation|out_of_scope",
  "confidence": 0.0-1.0,
  "workspace_policy": "public_only|selected_project_only|selected_project_plus_public|none",
  "needs_tools": true|false,
  "key_entities": ["entity1", "entity2"],
  "reason": "简短理由"
}

workspace_policy 规则:
- tech_general → public_only
- project_specific → selected_project_only
- troubleshooting → selected_project_plus_public
- runbook_generation → selected_project_plus_public
- out_of_scope → none

needs_tools 规则:
- troubleshooting → true
- runbook_generation → 可选 true
- 其他 → false
"""


def build_router_messages(query: str) -> list[dict]:
    return [
        {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ]
