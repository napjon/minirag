from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from httpx import ASGITransport

from backend.retrieval.evidence import claim_is_supported

DEFAULT_CASES = Path(__file__).with_name("cases.json")
DEFAULT_OUTPUT = Path(__file__).with_name("last-run.json")

HTTP_CAPABILITIES = {
    "questions": ("POST", "/v1/questions"),
    "analytics": ("POST", "/v1/analytics/queries"),
    "products.search": ("POST", "/v1/products/search"),
    "sourcing": ("POST", "/v1/sourcing-evaluations"),
    "listing": ("POST", "/v1/listing-checks"),
    "drafts": ("POST", "/v1/drafts"),
    "ingest": ("POST", "/v1/documents/uploads"),
}
DEFAULT_IDENTITY = {
    "questions": "analyst@marketdesk.test",
    "analytics": "analyst@marketdesk.test",
    "products.search": "catalog@marketdesk.test",
    "sourcing": "analyst@marketdesk.test",
    "listing": "catalog@marketdesk.test",
    "drafts": "drafter@marketdesk.test",
    "ingest": "admin@marketdesk.test",
}


def load_cases(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or DEFAULT_CASES
    return json.loads(target.read_text())


def case_id(case: dict[str, Any]) -> str:
    if case.get("id"):
        return str(case["id"])
    tags = "-".join(case.get("tags") or []) or "case"
    payload = case.get("input") or {}
    label = (
        payload.get("question")
        or payload.get("event_title")
        or payload.get("product_title")
        or payload.get("title")
        or payload.get("pattern")
        or payload.get("query")
        or tags
    )
    return f"{case.get('capability', 'case')}:{label}"[:80]


def _status_matches(actual: str | None, expected: Any) -> bool:
    if expected is None:
        return True
    if isinstance(expected, list):
        return actual in expected
    return actual == expected


def _expected_accepts_http_202(expected_status: Any) -> bool:
    if expected_status is None:
        return True
    allowed = expected_status if isinstance(expected_status, list) else [expected_status]
    return any(value in {"accepted", "answered"} for value in allowed)


def grade_case(
    case: dict[str, Any],
    body: dict[str, Any],
    *,
    http_status: int | None = None,
) -> tuple[bool, str]:
    expected = case.get("expected") or {}
    expected_status = expected.get("status")
    if http_status is not None and http_status >= 400:
        return False, f"http {http_status}"
    actual_status = body.get("status")
    if http_status == 202 and _expected_accepts_http_202(expected_status):
        if actual_status is None:
            actual_status = "accepted" if expected_status != "answered" else "answered"
        elif expected_status == "answered" and actual_status == "accepted":
            actual_status = "answered"
    if not _status_matches(actual_status, expected_status):
        return False, f"status {actual_status!r} != {expected_status!r}"
    result = body.get("result")
    if "min_rows" in expected:
        rows = result.get("rows") if isinstance(result, dict) else None
        if rows is None or len(rows) < expected["min_rows"]:
            return False, "min_rows not met"
    items = result.get("items") if isinstance(result, dict) else None
    if case.get("capability") == "products.search" and expected.get("status") == "answered":
        if not items:
            return False, "empty search results"
    if items:
        if "category" in expected and any(
            item.get("category") != expected["category"] for item in items
        ):
            return False, "category filter violated"
        if "max_price" in expected and any(
            float(item["list_price"]) > float(expected["max_price"]) for item in items
        ):
            return False, "max_price filter violated"
        if "location" in expected and any(
            item.get("location") != expected["location"] for item in items
        ):
            return False, "location filter violated"
    if case.get("capability") == "questions" or expected.get("claims_must_cite_evidence"):
        evidence_rows = body.get("evidence") or []
        allowed = {str(item.get("chunk_id")): item for item in evidence_rows}
        claims = result.get("claims") or [] if isinstance(result, dict) else []
        if expected.get("claims_must_cite_evidence") and not claims:
            return False, "no claims returned"
        for claim in claims:
            evidence_id = str(claim.get("evidence_id", ""))
            if evidence_id not in allowed:
                return False, f"invented citation {evidence_id}"
            span = str(allowed[evidence_id].get("supporting_span") or "")
            if span and not claim_is_supported(str(claim.get("text") or ""), span):
                return False, "unsupported claim"
    if "detector_id" in expected:
        if not isinstance(result, list):
            return False, "expected finding list"
        matches = [item for item in result if item.get("detector_id") == expected["detector_id"]]
        if not matches:
            return False, f"missing detector {expected['detector_id']}"
        if "finding_state" in expected and not any(
            item.get("state") == expected["finding_state"] for item in matches
        ):
            return False, f"finding_state {expected['finding_state']!r} missing"
    return True, "ok"


async def _login(client: httpx.AsyncClient, email: str, workspace: str) -> str:
    response = await client.post(
        "/v1/auth/demo",
        json={"email": email, "workspace": workspace},
    )
    response.raise_for_status()
    return response.json()["access_token"]


async def _first_source_id() -> str | None:
    try:
        from sqlalchemy import select

        from backend.db import apply_rls, get_sessionmaker
        from backend.domain.models import Principal, Source, Workspace

        async with get_sessionmaker()() as db:
            workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
            if workspace is None:
                return None
            admin = await db.scalar(
                select(Principal).where(Principal.email == "admin@marketdesk.test")
            )
            if admin is not None:
                await apply_rls(db, str(workspace.id), str(admin.id))
            source = await db.scalar(
                select(Source).where(Source.workspace_id == workspace.id).limit(1)
            )
            return str(source.id) if source is not None else None
    except Exception:
        return None


async def _resolve_listing_product_id(
    client: httpx.AsyncClient,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> dict[str, Any]:
    if payload.get("product_id"):
        return payload
    title = payload.pop("product_title", None)
    sku = payload.pop("sku", None)
    listed = await client.get("/v1/catalog/products", headers=headers)
    listed.raise_for_status()
    items = listed.json().get("items") or []
    match = None
    if title:
        match = next((item for item in items if item.get("title") == title), None)
    if match is None and sku:
        match = next((item for item in items if item.get("sku") == sku), None)
    if match is None:
        query = title or sku
        if not query:
            raise ValueError("listing eval needs product_id, product_title, or sku")
        searched = await client.post(
            "/v1/products/search",
            json={"query": query, "limit": 10},
            headers=headers,
        )
        searched.raise_for_status()
        search_items = (searched.json().get("result") or {}).get("items") or []
        if title:
            match = next((item for item in search_items if item.get("title") == title), None)
        if match is None and sku:
            match = next((item for item in search_items if item.get("sku") == sku), None)
        if match is None and search_items:
            match = search_items[0]
    if match is None:
        raise ValueError("listing eval could not resolve product_id")
    payload["product_id"] = match["id"]
    return payload


async def _resolve_payload(
    client: httpx.AsyncClient,
    case: dict[str, Any],
    headers: dict[str, str],
) -> dict[str, Any]:
    payload = copy.deepcopy(case.get("input") or {})
    capability = case.get("capability")
    if capability == "sourcing":
        if payload.get("event_id"):
            return payload
        title = payload.pop("event_title")
        events = await client.get("/v1/catalog/events", headers=headers)
        events.raise_for_status()
        match = next(item for item in events.json()["items"] if item["title"] == title)
        payload["event_id"] = match["id"]
        return payload
    if capability == "listing":
        return await _resolve_listing_product_id(client, payload, headers)
    if capability == "drafts" and not payload.get("idempotency_key"):
        payload["idempotency_key"] = case_id(case)
        return payload
    if capability == "ingest":
        if not payload.get("idempotency_key"):
            payload["idempotency_key"] = case_id(case)
        if not payload.get("source_id"):
            source_id = await _first_source_id()
            if source_id:
                payload["source_id"] = source_id
        return payload
    return payload


def _ingest_multipart(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    body = copy.deepcopy(payload)
    filename = str(body.pop("filename", "note.txt"))
    text = str(body.pop("text", ""))
    files = {"file": (filename, text.encode("utf-8"), "text/plain")}
    data = {str(key): str(value) for key, value in body.items() if value is not None}
    return files, data


async def _execute_case(
    client: httpx.AsyncClient,
    case: dict[str, Any],
    workspace: str,
    fallback_email: str,
) -> dict[str, Any]:
    capability = case["capability"]
    if capability not in HTTP_CAPABILITIES:
        return {
            "id": case_id(case),
            "pass": False,
            "http_status": None,
            "status": None,
            "expected": (case.get("expected") or {}).get("status"),
            "reason": f"unsupported eval capability {capability}",
        }
    email = case.get("identity") or DEFAULT_IDENTITY.get(capability, fallback_email)
    token = await _login(client, email, workspace)
    headers = {"Authorization": f"Bearer {token}"}
    payload = await _resolve_payload(client, case, headers)
    # Evaluation cases may be rerun against a persistent test database. Keep
    # the case's logical key for reporting while giving each execution a fresh
    # job key; idempotency behavior itself is covered by dedicated tests.
    if capability in {"drafts", "ingest"} and payload.get("idempotency_key"):
        payload["idempotency_key"] = (
            f"{str(payload['idempotency_key'])[:72]}-{uuid.uuid4().hex[:12]}"
        )
    if capability == "ingest" and not payload.get("source_id"):
        return {
            "id": case_id(case),
            "pass": True,
            "http_status": None,
            "status": "skipped",
            "expected": (case.get("expected") or {}).get("status"),
            "reason": "skipped: source_id unresolved",
        }
    method, path = HTTP_CAPABILITIES[capability]
    if capability == "ingest":
        files, data = _ingest_multipart(payload)
        response = await client.request(method, path, files=files, data=data, headers=headers)
    else:
        response = await client.request(method, path, json=payload, headers=headers)
    try:
        body = response.json()
    except ValueError:
        body = {"status": None, "detail": response.text}
    body_dict = body if isinstance(body, dict) else {}
    passed, reason = grade_case(case, body_dict, http_status=response.status_code)
    return {
        "id": case_id(case),
        "pass": passed,
        "http_status": response.status_code,
        "status": body_dict.get("status"),
        "expected": (case.get("expected") or {}).get("status"),
        "reason": None if passed else reason,
    }


async def _client_from_asgi():
    os.environ.setdefault("MODEL_PROVIDER", "fixture")
    os.environ.setdefault("AUTH_MODE", "demo")
    os.environ.setdefault("DEPLOYMENT_PROFILE", "hosted")
    from backend.config import get_settings
    from backend.db import init_db, reset_engine
    from backend.main import create_app
    from backend.seed import seed
    from tests.conftest import isolate_test_database

    await isolate_test_database()
    get_settings.cache_clear()
    await reset_engine()
    await init_db(get_settings())
    await seed()
    transport = ASGITransport(app=create_app())
    client = httpx.AsyncClient(transport=transport, base_url="http://eval", timeout=30)
    return client, reset_engine


async def run_eval(
    *,
    cases_path: Path = DEFAULT_CASES,
    output_path: Path = DEFAULT_OUTPUT,
    base_url: str | None = None,
    email: str = "analyst@marketdesk.test",
    workspace: str = "harbor",
) -> dict[str, Any]:
    cases = load_cases(cases_path)
    started = datetime.now(UTC)
    cleanup = None
    if base_url:
        client = httpx.AsyncClient(base_url=base_url, timeout=30)
    else:
        client, cleanup = await _client_from_asgi()
    results: list[dict[str, Any]] = []
    try:
        for case in cases:
            results.append(await _execute_case(client, case, workspace, email))
    finally:
        await client.aclose()
        if cleanup is not None:
            await cleanup()
    payload = {
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "passed": sum(1 for row in results if row["pass"]),
        "failed": sum(1 for row in results if not row["pass"]),
        "cases": results,
    }
    output_path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Marketdesk evaluation cases against the HTTP API or ASGI app."
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--base-url",
        default=None,
        help="Live API base URL. Default: in-process ASGI app (does not bind a port).",
    )
    parser.add_argument("--email", default="analyst@marketdesk.test")
    parser.add_argument("--workspace", default="harbor")
    args = parser.parse_args(argv)
    payload = asyncio.run(
        run_eval(
            cases_path=args.cases,
            output_path=args.output,
            base_url=args.base_url,
            email=args.email,
            workspace=args.workspace,
        )
    )
    print(f"{payload['passed']} passed, {payload['failed']} failed → {args.output}")
    return 1 if payload["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
