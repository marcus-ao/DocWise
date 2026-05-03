"""Query rewriter prompts — route-specific rewriting strategies."""
from __future__ import annotations

_REWRITE_TEMPLATES: dict[str, str] = {
    "tech_general": """\
你是技术文档检索助手。请改写以下用户问题，使其更适合向量检索:
- 保留技术关键词、错误码、框架名
- 扩展同义词（如 K8s = Kubernetes）
- 去除口语化表达
- 输出改写后的检索 query（一句话，不要解释）

用户问题: {query}""",

    "project_specific": """\
你是项目文档检索助手。请改写以下用户问题:
- 保留项目名、服务名、SLA、组件名
- 不要泛化为通用技术问题
- 输出改写后的检索 query（一句话，不要解释）

用户问题: {query}""",

    "troubleshooting": """\
你是故障排查助手。请从以下问题中抽取关键信息并改写为检索 query:
- 抽取: service 名、error 信息、时间范围、症状描述
- 改写为适合检索故障排查文档的 query
- 输出改写后的检索 query（一句话，不要解释）

用户问题: {query}""",

    "runbook_generation": """\
你是 Runbook 生成助手。请改写以下问题为检索 query:
- 改写成"现有 SOP + 技术文档 + 故障类型"的检索 query
- 输出改写后的检索 query（一句话，不要解释）

用户问题: {query}""",
}


def build_rewriter_messages(query: str, route: str) -> list[dict]:
    template = _REWRITE_TEMPLATES.get(route, _REWRITE_TEMPLATES["tech_general"])
    return [
        {"role": "user", "content": template.format(query=query)},
    ]
