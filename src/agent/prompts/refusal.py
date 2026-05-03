"""Refusal prompt templates."""
from __future__ import annotations

REFUSAL_TEMPLATES: dict[str, str] = {
    "out_of_scope": (
        "抱歉，您的问题超出了 DocWise 的知识范围。DocWise 专注于技术文档查询、项目知识问答和故障排查，"
        "无法回答与此无关的问题。"
    ),
    "no_evidence": (
        "抱歉，我在当前知识库中未找到与您问题相关的可靠信息。"
        "建议您检查问题描述是否准确，或联系相关团队获取帮助。"
    ),
    "low_confidence": (
        "抱歉，我对这个问题的理解置信度较低，且未找到足够的证据来给出可靠回答。"
        "建议您提供更多上下文或换一种方式描述问题。"
    ),
}


def get_refusal_answer(reason_key: str) -> str:
    return REFUSAL_TEMPLATES.get(reason_key, REFUSAL_TEMPLATES["no_evidence"])
