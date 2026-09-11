from __future__ import annotations

import json
import os
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import httpx

API = os.environ.get("MARKETDESK_API", "http://127.0.0.1:8130")
TOKEN = os.environ.get("MARKETDESK_TOKEN", "")
MANIFEST_PATH = Path(__file__).with_name("mcp_manifest.json")
MANIFEST: dict[str, Any] = json.loads(MANIFEST_PATH.read_text())
ALLOWED_TOOLS: tuple[str, ...] = tuple(tool["name"] for tool in MANIFEST["tools"])

ToolFn = Callable[..., Coroutine[Any, Any, dict[str, Any]]]


async def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
    async with httpx.AsyncClient(base_url=API, timeout=30) as client:
        response = await client.post(path, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()


async def _get(path: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
    async with httpx.AsyncClient(base_url=API, timeout=30) as client:
        response = await client.get(path, headers=headers)
        response.raise_for_status()
        return response.json()


async def search_knowledge(query: str, language: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"question": query}
    if language:
        payload["language"] = language
    return await _post("/v1/questions", payload)


async def read_evidence(document_id: str) -> dict[str, Any]:
    return await _get(f"/v1/documents/{document_id}")


async def query_operational_data(question: str) -> dict[str, Any]:
    return await _post("/v1/analytics/queries", {"question": question})


async def search_products(query: str, category: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"query": query}
    if category:
        payload["category"] = category
    return await _post("/v1/products/search", payload)


async def compare_products(product_ids: list[str]) -> dict[str, Any]:
    return await _post("/v1/products/compare", {"product_ids": product_ids})


async def get_price_references(product_id: str) -> dict[str, Any]:
    return await _get(f"/v1/products/{product_id}/references")


async def get_finding(finding_id: str) -> dict[str, Any]:
    return await _get(f"/v1/findings/{finding_id}")


async def get_draft_status(draft_id: str) -> dict[str, Any]:
    return await _get(f"/v1/drafts/{draft_id}")


TOOL_FUNCTIONS: tuple[ToolFn, ...] = (
    search_knowledge,
    read_evidence,
    query_operational_data,
    search_products,
    compare_products,
    get_price_references,
    get_finding,
    get_draft_status,
)
if tuple(fn.__name__ for fn in TOOL_FUNCTIONS) != ALLOWED_TOOLS:
    raise RuntimeError("MCP tool functions must match mcp_manifest.json")


def create_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise SystemExit("install marketdesk[mcp] to run the MCP server") from exc

    mcp = FastMCP("marketdesk")
    for fn in TOOL_FUNCTIONS:
        mcp.tool()(fn)
    return mcp


def run() -> None:
    create_server().run()


if __name__ == "__main__":
    run()
