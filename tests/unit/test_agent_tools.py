import pytest

from src.agent.tools.query_mock_logs import query_mock_logs
from src.agent.tools.query_project_manifest import query_project_manifest
from src.agent.tools.query_service_status import query_service_status


@pytest.mark.asyncio
async def test_project_manifest_matches_generic_airflow_alias() -> None:
    result = await query_project_manifest(service_name="airflow")

    service_names = {item["service_name"] for item in result["matched_services"]}
    assert {"airflow-scheduler", "airflow-worker"}.issubset(service_names)
    assert result["confidence"] == 1.0


@pytest.mark.asyncio
async def test_service_status_resolves_generic_airflow_to_most_severe_service() -> None:
    result = await query_service_status("airflow")

    assert result["service_name"] == "airflow-worker"
    assert result["status"] == "down"
    assert any(alert["name"] == "TaskFailureRateHigh" for alert in result["active_alerts"])


@pytest.mark.asyncio
async def test_mock_logs_resolve_generic_airflow_and_phrase_keywords() -> None:
    result = await query_mock_logs("airflow", level="ERROR", keywords=["task failed"])

    assert result["matched_count"] > 0
    assert any(entry["service_name"] == "airflow-worker" for entry in result["entries"])
    assert "No log file found" not in result["summary"]
