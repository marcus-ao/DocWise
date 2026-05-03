"""Trace rendering helpers."""
from __future__ import annotations

from typing import Any

import plotly.express as px
import streamlit as st


def render_trace(trace: dict[str, Any]) -> None:
    st.subheader("Trace 概览")
    st.write(f"状态: {trace.get('status')} - 路由: {trace.get('route')}")
    events = trace.get("trace_events") or []
    if events:
        fig = px.bar(events, x="node_name", y="latency_ms", color="status", title="节点耗时")
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(events, use_container_width=True)
    st.subheader("检索结果")
    st.dataframe(trace.get("retrieval_results") or [], use_container_width=True)
    st.subheader("工具调用")
    st.dataframe(trace.get("tool_calls") or [], use_container_width=True)
    st.subheader("引用")
    st.dataframe(trace.get("citations") or [], use_container_width=True)

