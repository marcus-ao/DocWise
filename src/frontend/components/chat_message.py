"""Streamlit chat rendering helpers."""
from __future__ import annotations

from typing import Any

import streamlit as st


def render_message(role: str, content: str) -> None:
    with st.chat_message(role):
        st.markdown(content or "_")


def render_citations(citations: list[dict[str, Any]]) -> None:
    if not citations:
        return
    st.subheader("引用")
    for citation in citations:
        title = citation.get("document_title") or "Untitled document"
        section = citation.get("section_path") or "未标注章节"
        score = float(citation.get("score") or 0.0)
        quote = citation.get("quote") or ""
        with st.expander(f"[{citation.get('index', '?')}] {title} - {section} - score={score:.2f}"):
            st.write(quote)


def render_tool_events(tool_events: list[dict[str, Any]]) -> None:
    if not tool_events:
        return
    st.subheader("工具调用")
    for event in tool_events:
        st.json(event)

