"""Eval page."""
from __future__ import annotations

import asyncio

import streamlit as st

from src.frontend import api_client

st.set_page_config(page_title="DocWise Eval", layout="wide")
st.title("Eval")

try:
    count = asyncio.run(api_client.get_eval_count())
    st.metric("Eval cases", count.get("total_cases", 0))
except Exception as error:
    st.error(f"加载 Eval 信息失败: {error}")

