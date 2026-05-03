"""Agent tool registry."""
from src.agent.tools.generate_runbook_draft import generate_runbook_draft
from src.agent.tools.query_mock_logs import query_mock_logs
from src.agent.tools.query_project_manifest import query_project_manifest
from src.agent.tools.query_service_status import query_service_status
from src.agent.tools.search_docs import search_docs

TOOL_REGISTRY = {
    "search_docs": search_docs,
    "query_project_manifest": query_project_manifest,
    "query_service_status": query_service_status,
    "query_mock_logs": query_mock_logs,
    "generate_runbook_draft": generate_runbook_draft,
}

__all__ = ["TOOL_REGISTRY"]

