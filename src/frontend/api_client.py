"""Async client for the local DocWise API."""
from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx

from src.config.settings import settings

API_BASE_URL = os.getenv("DOCWISE_API_BASE_URL", "http://127.0.0.1:8000/api/v1")


class ApiClientError(RuntimeError):
    """Raised when the backend returns a non-successful response."""


def _headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    token = os.getenv("DOCWISE_ADMIN_TOKEN") or os.getenv("ADMIN_API_TOKEN") or settings.admin_api_token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def request_json(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0) as client:
            response = await client.request(method, path, headers=_headers(), **kwargs)
    except httpx.ReadTimeout as exc:
        raise TimeoutError("DocWise API request timed out") from exc
    except httpx.HTTPError as exc:
        raise ApiClientError(str(exc)) from exc
    if response.status_code >= 400:
        detail: object
        try:
            detail = response.json()
        except ValueError:
            detail = response.text
        raise ApiClientError(f"{response.status_code}: {detail}")
    return response.json()


async def post_chat(query: str, workspace_slug: str | None = None) -> dict[str, Any]:
    return await request_json("POST", "/chat", json={"query": query, "workspace_slug": workspace_slug})


async def stream_chat(query: str, workspace_slug: str | None = None) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST",
            f"{API_BASE_URL}/chat/stream",
            headers=_headers(),
            json={"query": query, "workspace_slug": workspace_slug},
        ) as response:
            response.raise_for_status()
            event_type = "message"
            async for line in response.aiter_lines():
                if not line:
                    continue
                if line.startswith("event:"):
                    event_type = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    yield event_type, json.loads(line.split(":", 1)[1].strip())


async def send_feedback(query_id: str, thumbs: str) -> dict[str, Any]:
    return await request_json("POST", f"/chat/{query_id}/feedback", json={"thumbs": thumbs})


async def list_documents(status: str | None = None) -> dict[str, Any]:
    params = {"status": status} if status and status != "All" else {}
    return await request_json("GET", "/documents", params=params)


async def upload_document(
    file_name: str,
    file_bytes: bytes,
    content_type: str,
    workspace_slug: str,
    doc_type: str | None = None,
) -> dict[str, Any]:
    data = {"workspace_slug": workspace_slug}
    if doc_type:
        data["doc_type"] = doc_type
    files = {"file": (file_name, file_bytes, content_type)}
    return await request_json("POST", "/documents/upload", data=data, files=files)


async def retry_document(document_id: str) -> dict[str, Any]:
    return await request_json("POST", f"/documents/{document_id}/retry")


async def delete_document_record(document_id: str) -> dict[str, Any]:
    return await request_json("DELETE", f"/documents/{document_id}/record")


async def delete_document(document_id: str) -> dict[str, Any]:
    return await request_json("DELETE", f"/documents/{document_id}")


async def purge_document(document_id: str) -> dict[str, Any]:
    return await request_json("DELETE", f"/documents/{document_id}/purge")


async def get_trace(run_id: str) -> dict[str, Any]:
    return await request_json("GET", f"/agent/runs/{run_id}/trace")


async def get_eval_count() -> dict[str, Any]:
    return await request_json("GET", "/eval/count")
