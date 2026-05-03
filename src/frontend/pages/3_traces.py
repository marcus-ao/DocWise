"""Trace viewer page."""
from __future__ import annotations

import asyncio

import streamlit as st

from src.frontend import api_client
from src.frontend.components.trace_viewer import render_trace

st.set_page_config(page_title="DocWise Traces", layout="wide")
st.title("Traces")

run_id = st.text_input("Run ID")
if st.button("查看 Trace") and run_id:
    try:
        render_trace(asyncio.run(api_client.get_trace(run_id)))
    except Exception as error:
        st.error(f"加载 Trace 失败: {error}")

