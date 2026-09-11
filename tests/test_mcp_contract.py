from __future__ import annotations

import inspect
import json
from pathlib import Path

import httpx
import pytest

import backend.integrations.mcp_server as mcp_server
from backend.integrations.mcp_server import (
    ALLOWED_TOOLS,
    MANIFEST,
    compare_products,
    get_draft_status,
    get_finding,
    get_price_references,
    query_operational_data,
    read_evidence,
    search_knowledge,
    search_products,
)

FORBIDDEN_TOOLS = {"approve_draft", "execute_sql", "send_email"}
EXPECTED_TOOLS = (
    "search_knowledge",
    "read_evidence",
    "query_operational_data",
    "search_products",
    "compare_products",
    "get_price_references",
    "get_finding",
    "get_draft_status",
)
IMPORTED_TOOLS = (
    search_knowledge,
    read_evidence,
    query_operational_data,
    search_products,
    compare_products,
    get_price_references,
    get_finding,
    get_draft_status,
)


def test_manifest_lists_only_allowed_tools():
    manifest_path = Path(mcp_server.__file__).with_name("mcp_manifest.json")
    on_disk = json.loads(manifest_path.read_text())
    names = tuple(tool["name"] for tool in on_disk["tools"])
    assert names == EXPECTED_TOOLS
    assert ALLOWED_TOOLS == EXPECTED_TOOLS
    assert tuple(tool["name"] for tool in MANIFEST["tools"]) == EXPECTED_TOOLS
    assert FORBIDDEN_TOOLS.isdisjoint(names)
    cannot = " ".join(on_disk["cannot"]).lower()
    phrases = (
        "approve drafts",
        "publish",
        "change permissions",
        "run sql",
        "access the network",
    )
    for phrase in phrases:
        assert phrase in cannot


def test_mcp_module_exposes_tool_functions_and_omits_forbidden():
    exported = {
        name
        for name, obj in inspect.getmembers(mcp_server, inspect.iscoroutinefunction)
        if not name.startswith("_")
    }
    assert set(EXPECTED_TOOLS) <= exported
    assert FORBIDDEN_TOOLS.isdisjoint(exported)
    for name in FORBIDDEN_TOOLS:
        assert getattr(mcp_server, name, None) is None
    assert [fn.__name__ for fn in IMPORTED_TOOLS] == list(EXPECTED_TOOLS)
    assert [fn.__name__ for fn in mcp_server.TOOL_FUNCTIONS] == list(EXPECTED_TOOLS)


def test_create_server_registers_manifest_tools_only():
    pytest.importorskip("mcp.server.fastmcp")
    server = mcp_server.create_server()
    manager = getattr(server, "_tool_manager", None)
    tools = getattr(manager, "_tools", None) if manager is not None else None
    if not isinstance(tools, dict):
        pytest.skip("FastMCP tool manager layout is not available")
    names = set(tools)
    assert names == set(EXPECTED_TOOLS)
    assert FORBIDDEN_TOOLS.isdisjoint(names)


@pytest.mark.asyncio
async def test_mcp_tools_forward_bearer_to_http_api(monkeypatch, httpx_mock):
    monkeypatch.setattr(mcp_server, "API", "http://mcp.test")
    monkeypatch.setattr(mcp_server, "TOKEN", "tok-123")
    httpx_mock.add_response(
        url="http://mcp.test/v1/questions",
        method="POST",
        json={"status": "answered", "result": {"claims": []}},
    )
    body = await search_knowledge("Who may run operational queries?")
    assert body["status"] == "answered"
    request = httpx_mock.get_request()
    assert request.method == "POST"
    assert request.url.path == "/v1/questions"
    assert request.headers["Authorization"] == "Bearer tok-123"
    assert json.loads(request.content)["question"] == "Who may run operational queries?"


@pytest.mark.asyncio
async def test_mcp_get_finding_propagates_http_errors(monkeypatch, httpx_mock):
    monkeypatch.setattr(mcp_server, "API", "http://mcp.test")
    monkeypatch.setattr(mcp_server, "TOKEN", "tok-123")
    httpx_mock.add_response(
        url="http://mcp.test/v1/findings/11111111-1111-1111-1111-111111111111",
        method="GET",
        status_code=403,
        json={"detail": "missing capability sourcing"},
    )
    with pytest.raises(httpx.HTTPStatusError) as exc:
        await get_finding("11111111-1111-1111-1111-111111111111")
    assert exc.value.response.status_code == 403
    request = httpx_mock.get_request()
    assert request.headers["Authorization"] == "Bearer tok-123"
