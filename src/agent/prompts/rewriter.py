"""Query rewriter prompts — route-specific rewriting strategies."""
from __future__ import annotations

_REWRITE_TEMPLATES: dict[str, str] = {
    "tech_general": """\
你是技术文档检索助手。请改写以下用户问题，使其更适合向量检索:
- 保留技术关键词、错误码、框架名
- 扩展同义词（如 K8s = Kubernetes）
- 去除口语化表达
- 如当前问题是承接式追问，可使用给定历史补全主语或对象
- 输出改写后的检索 query（一句话，不要解释）

用户问题:
{query}

{history_block}""",

    "project_specific": """\
你是项目文档检索助手。请改写以下用户问题:
- 保留项目名、服务名、SLA、组件名
- 不要泛化为通用技术问题
- 如当前问题是承接式追问，可使用给定历史补全主语或对象
- 输出改写后的检索 query（一句话，不要解释）

用户问题:
{query}

{history_block}""",

    "troubleshooting": """\
你是故障排查助手。请从以下问题中抽取关键信息并改写为检索 query:
- 抽取: service 名、error 信息、时间范围、症状描述
- 改写为适合检索故障排查文档的 query
- 如当前问题省略了 service 或症状对象，可使用给定历史补全
- 输出改写后的检索 query（一句话，不要解释）

用户问题:
{query}

{history_block}""",

    "runbook_generation": """\
你是 Runbook 生成助手。请改写以下问题为检索 query:
- 改写成"现有 SOP + 技术文档 + 故障类型"的检索 query
- 如当前问题省略了对象，可使用给定历史补全
- 输出改写后的检索 query（一句话，不要解释）

用户问题:
{query}

{history_block}""",
}


def build_rewriter_messages(
    query: str,
    route: str,
    *,
    recent_turns: list[dict] | None = None,
    context_summary: str | None = None,
    use_history: bool = True,
) -> list[dict]:
    template = _REWRITE_TEMPLATES.get(route, _REWRITE_TEMPLATES["tech_general"])
    history_lines: list[str] = []
    if use_history and recent_turns:
        for turn in recent_turns:
            turn_index = turn.get("turn_index")
            turn_query = str(turn.get("query") or "").strip()
            turn_answer = str(turn.get("answer") or "").strip()
            prefix = f"[turn {turn_index}] " if turn_index is not None else ""
            if turn_query:
                history_lines.append(f"{prefix}User: {turn_query}")
            if turn_answer:
                history_lines.append(f"{prefix}Assistant: {turn_answer}")
    if use_history and context_summary:
        history_lines.append(f"Summary: {context_summary}")
    history_block = "历史上下文:\n" + "\n".join(history_lines) if history_lines else "历史上下文: (none)"
    return [
        {"role": "user", "content": template.format(query=query, history_block=history_block)},
    ]
