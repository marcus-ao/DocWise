"""Phase A multi-turn SSE smoke test.

This script validates the Phase A runtime chain end-to-end against a live
backend. It focuses on the conversation semantics that unit tests cannot prove
alone: conversation reuse, turn ordering, and history-aware runtime nodes
showing up in the SSE stream.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass, field

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_WORKSPACE = "auto"
DEFAULT_TURN_QUERIES = [
    "Airflow scheduler 卡住了，应该先排查什么？",
    "那 task 超时呢？",
    "如果是 worker 侧资源不足呢？",
    "日志里出现 ECONNRESET 怎么办？",
    "最后给我总结一个排查顺序。",
]


@dataclass(slots=True)
class TurnReport:
    query: str
    events: list[str] = field(default_factory=list)
    run_payload: dict | None = None
    done_payload: dict | None = None
    route_payloads: list[dict] = field(default_factory=list)
    reasoning_payloads: list[dict] = field(default_factory=list)


def normalize_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if normalized.endswith("/api/v1"):
        return normalized
    if normalized.endswith("/api"):
        return f"{normalized}/v1"
    return f"{normalized}/api/v1"


def build_chat_payload(query: str, workspace: str, conversation_id: str | None) -> dict:
    payload: dict[str, object] = {"query": query}
    if workspace != DEFAULT_WORKSPACE:
        payload["workspace_slug"] = workspace
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    return payload


async def stream_turn(
    client: httpx.AsyncClient,
    *,
    api_base_url: str,
    query: str,
    workspace: str,
    conversation_id: str | None,
) -> TurnReport:
    url = f"{api_base_url}/chat/stream"
    payload = build_chat_payload(query, workspace, conversation_id)
    report = TurnReport(query=query)
    buffer = ""

    try:
        async with client.stream("POST", url, json=payload, headers={"Accept": "text/event-stream"}) as response:
            response.raise_for_status()
            async for chunk in response.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    frame, buffer = buffer.split("\n\n", 1)
                    _consume_sse_frame(frame, report)
    except httpx.ConnectError as exc:
        raise RuntimeError(
            f"无法连接 DocWise 后端：{url}。请先启动 API 服务后再运行 smoke。原始错误：{exc}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        body = exc.response.text.strip()
        suffix = f" 响应体：{body}" if body else ""
        raise RuntimeError(f"后端返回 HTTP {exc.response.status_code}，multi-turn smoke 终止。{suffix}") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"请求 SSE 流失败：{exc}") from exc

    if buffer.strip():
        _consume_sse_frame(buffer, report)
    return report


def _consume_sse_frame(frame: str, report: TurnReport) -> None:
    if not frame.strip():
        return
    event_name = ""
    data_chunks: list[str] = []
    for line in frame.splitlines():
        if line.startswith("event: "):
            event_name = line.removeprefix("event: ").strip()
        elif line.startswith("data: "):
            data_chunks.append(line.removeprefix("data: ").strip())
    if not event_name:
        return
    report.events.append(event_name)
    payload = {}
    if data_chunks:
        try:
            payload = json.loads("".join(data_chunks))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"SSE 事件 {event_name} 的 JSON 无法解析：{data_chunks!r}") from exc
    if event_name == "run":
        report.run_payload = payload
    elif event_name == "done":
        report.done_payload = payload
    elif event_name == "route":
        report.route_payloads.append(payload)
    elif event_name == "reasoning":
        report.reasoning_payloads.append(payload)


def assert_turn_report(
    report: TurnReport,
    *,
    expected_turn_index: int,
    expected_conversation_id: str | None,
    expected_parent_run_id: str | None,
    require_history: bool,
) -> tuple[str, str]:
    if report.run_payload is None:
        raise AssertionError(f"turn={expected_turn_index} 缺少 run 事件")
    if report.done_payload is None:
        raise AssertionError(f"turn={expected_turn_index} 缺少 done 事件")

    conversation_id = str(report.run_payload.get("conversation_id") or "")
    run_id = str(report.run_payload.get("run_id") or "")
    raw_turn_index = report.run_payload.get("turn_index")
    turn_index = int(raw_turn_index) if raw_turn_index is not None else -1
    parent_run_id = report.run_payload.get("parent_run_id")

    if not conversation_id:
        raise AssertionError(f"turn={expected_turn_index} 的 run 事件缺少 conversation_id")
    if not run_id:
        raise AssertionError(f"turn={expected_turn_index} 的 run 事件缺少 run_id")
    if turn_index != expected_turn_index:
        raise AssertionError(
            f"turn={expected_turn_index} 的 run.turn_index={turn_index}，与期望不一致"
        )
    if expected_conversation_id is not None and conversation_id != expected_conversation_id:
        raise AssertionError(
            f"turn={expected_turn_index} 的 conversation_id={conversation_id}，期望复用 {expected_conversation_id}"
        )
    if expected_parent_run_id is None:
        if parent_run_id is not None:
            raise AssertionError(f"turn=0 不应带 parent_run_id，实际为 {parent_run_id}")
    else:
        if str(parent_run_id or "") != expected_parent_run_id:
            raise AssertionError(
                f"turn={expected_turn_index} 的 parent_run_id={parent_run_id}，期望 {expected_parent_run_id}"
            )

    reasoning_nodes = {str(item.get("node") or "") for item in report.reasoning_payloads}
    for required in ("context_loader", "scope_selector", "query_rewriter"):
        if required not in reasoning_nodes:
            raise AssertionError(f"turn={expected_turn_index} 缺少 reasoning 节点 {required}")

    if require_history:
        loader_payloads = [
            item for item in report.reasoning_payloads if str(item.get("node")) == "context_loader"
        ]
        if not loader_payloads:
            raise AssertionError(f"turn={expected_turn_index} 缺少 context_loader reasoning")
        turns_loaded = max(
            (_parse_loaded_turn_count(str(item.get("reason") or "")) for item in loader_payloads),
            default=0,
        )
        if turns_loaded <= 0:
            raise AssertionError(
                "turn="
                f"{expected_turn_index} 的 context_loader 未显示有效历史载入，"
                f"reasonings={[item.get('reason') for item in loader_payloads]!r}"
            )

    return conversation_id, run_id


def _parse_loaded_turn_count(reason: str) -> int:
    match = re.search(r"加载\s+(\d+)\s+轮历史上下文", reason)
    return int(match.group(1)) if match else 0


async def run_smoke(*, base_url: str, workspace: str, timeout: float) -> None:
    api_base_url = normalize_base_url(base_url)
    timeout_config = httpx.Timeout(timeout)
    conversation_id: str | None = None
    previous_run_id: str | None = None

    async with httpx.AsyncClient(timeout=timeout_config) as client:
        for turn_index, query in enumerate(DEFAULT_TURN_QUERIES):
            report = await stream_turn(
                client,
                api_base_url=api_base_url,
                query=query,
                workspace=workspace,
                conversation_id=conversation_id,
            )
            conversation_id, previous_run_id = assert_turn_report(
                report,
                expected_turn_index=turn_index,
                expected_conversation_id=conversation_id,
                expected_parent_run_id=previous_run_id,
                require_history=turn_index > 0,
            )
            print(
                f"[turn {turn_index}] ok conversation_id={conversation_id} run_id={previous_run_id} "
                f"events={' -> '.join(report.events)}"
            )

    print("MULTI-TURN SMOKE PASS: Phase A conversation runtime is behaving as expected.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the DocWise Phase A multi-turn SSE smoke test.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="DocWise backend base URL, default http://127.0.0.1:8000")
    parser.add_argument(
        "--workspace",
        default=DEFAULT_WORKSPACE,
        help="Workspace slug to send. Use 'auto' to omit workspace_slug and exercise Auto scope.",
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="Per-request timeout in seconds.")
    return parser.parse_args(argv)


async def main_async(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        await run_smoke(base_url=args.base_url, workspace=args.workspace, timeout=args.timeout)
    except (AssertionError, RuntimeError) as exc:
        print(f"MULTI-TURN SMOKE FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(main_async(argv))


if __name__ == "__main__":
    raise SystemExit(main())
