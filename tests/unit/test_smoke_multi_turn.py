from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from scripts import smoke_multi_turn


def test_normalize_base_url_appends_api_v1_when_missing() -> None:
    assert smoke_multi_turn.normalize_base_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000/api/v1"
    assert smoke_multi_turn.normalize_base_url("http://127.0.0.1:8000/api") == "http://127.0.0.1:8000/api/v1"
    assert smoke_multi_turn.normalize_base_url("http://127.0.0.1:8000/api/v1/") == "http://127.0.0.1:8000/api/v1"


@pytest.mark.asyncio
async def test_main_async_reports_clear_backend_failure(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        smoke_multi_turn,
        "run_smoke",
        AsyncMock(side_effect=RuntimeError("无法连接 DocWise 后端：http://127.0.0.1:8000/api/v1/chat/stream。")),
    )

    exit_code = await smoke_multi_turn.main_async(["--base-url", "http://127.0.0.1:8000"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "MULTI-TURN SMOKE FAIL" in captured.err
    assert "无法连接 DocWise 后端" in captured.err
