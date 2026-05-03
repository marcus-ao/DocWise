"""Documents page."""
from __future__ import annotations

import asyncio

import pandas as pd
import streamlit as st

from src.frontend import api_client

st.set_page_config(page_title="DocWise Documents", layout="wide")
st.title("Documents")

status_filter = st.selectbox("状态筛选", ["All", "pending", "processing", "ready", "error"])
if "hidden_document_ids" not in st.session_state:
    st.session_state.hidden_document_ids = set()

cols = st.columns([1, 1, 4])
if cols[0].button("刷新文档列表"):
    st.session_state.hidden_document_ids = set()
if cols[1].button("取消隐藏"):
    st.session_state.hidden_document_ids = set()

try:
    data = asyncio.run(api_client.list_documents(status_filter))
    items = [item for item in data.get("items", []) if item.get("id") not in st.session_state.hidden_document_ids]
    if items:
        st.dataframe(pd.DataFrame(items), use_container_width=True, hide_index=True)
        for item in items:
            doc_id = item["id"]
            title = item.get("title") or item.get("file_name")
            with st.expander(f"{title} - {item.get('status')}"):
                st.json(item)
                left, middle, right = st.columns(3)
                if left.button("Retry/Reindex", key=f"retry-{doc_id}"):
                    st.json(asyncio.run(api_client.retry_document(doc_id)))
                if middle.button("删除记录", key=f"hide-{doc_id}"):
                    asyncio.run(api_client.delete_document_record(doc_id))
                    st.session_state.hidden_document_ids.add(doc_id)
                    st.rerun()
                if right.button("真正删除", key=f"delete-{doc_id}"):
                    st.json(asyncio.run(api_client.delete_document(doc_id)))
                    st.rerun()
    else:
        st.info("暂无文档")
except Exception as error:
    st.error(f"加载文档失败: {error}")

