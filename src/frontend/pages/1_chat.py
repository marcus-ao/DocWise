"""Chat page."""
from __future__ import annotations

import asyncio

import streamlit as st

from src.frontend import api_client
from src.frontend.components.chat_message import render_citations, render_message, render_tool_events

st.set_page_config(page_title="DocWise Chat", layout="wide")
st.title("Chat")

workspace_slug = st.selectbox(
    "Workspace",
    [None, "public_tech", "project_airflow", "project_backstage", "project_fastapi"],
    format_func=lambda value: value or "Auto",
)
if "messages" not in st.session_state:
    st.session_state.messages = []
if "last_query_id" not in st.session_state:
    st.session_state.last_query_id = None

for message in st.session_state.messages:
    render_message(message["role"], message["content"])

prompt = st.chat_input("请输入问题")
if prompt is not None:
    st.session_state.messages.append({"role": "user", "content": prompt})
    render_message("user", prompt)
    answer_box = st.empty()
    status_box = st.empty()
    tool_box = st.empty()
    citation_box = st.empty()
    stream_state: dict[str, object] = {"answer": "", "citations": [], "tools": [], "statuses": [], "query_id": None}

    def render_answer() -> None:
        answer_box.chat_message("assistant").markdown(str(stream_state["answer"] or "正在生成回复..."))

    def render_statuses() -> None:
        statuses = stream_state["statuses"]
        if isinstance(statuses, list) and statuses:
            lines = [f"- `{item['event']}`: `{item['payload']}`" for item in statuses]
            status_box.info("处理过程\n\n" + "\n".join(lines))

    def render_tools_live() -> None:
        tools = stream_state["tools"]
        if isinstance(tools, list) and tools:
            with tool_box.container():
                render_tool_events(tools)

    def render_citations_live() -> None:
        citations = stream_state["citations"]
        if isinstance(citations, list) and citations:
            with citation_box.container():
                render_citations(citations)

    async def consume() -> None:
        async for event_type, payload in api_client.stream_chat(prompt, workspace_slug):
            if event_type == "token":
                content = payload.get("content", "")
                if content:
                    stream_state["answer"] = f"{stream_state['answer']}{content}"
                    render_answer()
            elif event_type == "answer":
                content = str(payload.get("content") or "")
                if content:
                    stream_state["answer"] = content
                    render_answer()
            elif event_type in {"route", "retrieval", "rerank"}:
                statuses = stream_state["statuses"]
                if isinstance(statuses, list):
                    statuses.append({"event": event_type, "payload": payload})
                    render_statuses()
            elif event_type in {"tool_call", "tool_result"}:
                tools = stream_state["tools"]
                if isinstance(tools, list):
                    tools.append({"event": event_type, **payload})
                    render_tools_live()
            elif event_type == "citation":
                stream_state["citations"] = payload.get("citations") or []
                render_citations_live()
            elif event_type == "done":
                stream_state["query_id"] = payload.get("query_id")
                st.session_state.last_query_id = payload.get("query_id")
                if not stream_state["answer"] and payload.get("answer"):
                    stream_state["answer"] = str(payload["answer"])
                    render_answer()
            elif event_type == "error":
                status_box.error(payload.get("message", "连接出错"))
                return

    try:
        asyncio.run(consume())
        st.session_state.messages.append({"role": "assistant", "content": str(stream_state["answer"])})
        if stream_state.get("query_id"):
            cols = st.columns(2)
            if cols[0].button("有帮助", key=f"up-{stream_state['query_id']}"):
                asyncio.run(api_client.send_feedback(str(stream_state["query_id"]), "up"))
                st.success("感谢反馈")
            if cols[1].button("需改进", key=f"down-{stream_state['query_id']}"):
                asyncio.run(api_client.send_feedback(str(stream_state["query_id"]), "down"))
                st.success("感谢反馈")
        st.markdown("<div style='height: 7rem'></div>", unsafe_allow_html=True)
    except TimeoutError:
        st.error("连接超时，请重试")
    except Exception as error:
        st.error(f"请求失败: {error}")

