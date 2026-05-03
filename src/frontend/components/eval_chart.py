"""Evaluation chart helpers."""
from __future__ import annotations

from typing import Any

import plotly.express as px
import streamlit as st


def render_eval_summary(items: list[dict[str, Any]]) -> None:
    if not items:
        st.info("暂无评估结果")
        return
    fig = px.bar(items, x="run_id", y="bad_case_count", title="Bad cases by eval run")
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(items, use_container_width=True)

