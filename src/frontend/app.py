"""DocWise Streamlit entrypoint."""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="DocWise", page_icon="DW", layout="wide")
st.title("DocWise")
st.markdown("企业开发者知识工作流 Agent：文档入库、流式问答、Trace 回放与评估看板。")
st.info("请使用左侧页面导航进入 Chat、Documents、Traces 或 Eval。")

