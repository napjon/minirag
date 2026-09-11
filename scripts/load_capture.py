#!/usr/bin/env python3
"""Capture p50/p95 latency against a live Marketdesk API.

Client only: does not start a server and never binds 3000 or 8000.

Default MARKETDESK_API is http://127.0.0.1:8130. Login:
analyst@marketdesk.test / harbor.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

DEFAULT_API = "http://127.0.0.1:8130"
FORBIDDEN_PORTS = {3000, 8000}


def percentile_ms(samples: list[float], p: float) -> float:
    ordered = sorted(samples)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    if p == 50:
        return round(statistics.median(ordered), 2)
    idx = min(len(ordered) - 1, max(0, int(p / 100 * (len(ordered) - 1))))
    return round(ordered[idx], 2)


def summarize(samples: list[float]) -> dict[str, float | int]:
    return {
        "n": len(samples),
        "p50_ms": percentile_ms(samples, 50),
        "p95_ms": percentile_ms(samples, 95),
    }


def request_ms(
    api: str,
    method: str,
    path: str,
    body: dict | None = None,
    token: str | None = None,
) -> tuple[float, bytes]:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(api + path, data=data, headers=headers, method=method)
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = resp.read()
    return (time.perf_counter() - start) * 1000, payload


def _safe_request_ms(
    api: str,
    method: str,
    path: str,
    body: dict | None = None,
    token: str | None = None,
) -> tuple[float, bool]:
    """Capture latency without aborting a mixed workload on one HTTP error."""

    started = time.perf_counter()
    try:
        request_ms(api, method, path, body, token)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return (time.perf_counter() - started) * 1000, False
    return (time.perf_counter() - started) * 1000, True


def _measure_mixed_workload(api: str, token: str, n: int, workers: int) -> dict:
    workloads = {
        "health": ("GET", "/health", None),
        "questions": ("POST", "/v1/questions", {"question": "Who may run operational queries?"}),
        "search": ("POST", "/v1/products/search", {"query": "network", "limit": 10}),
        "analytics": (
            "POST",
            "/v1/analytics/queries",
            {
                "pattern": "spending_by_period",
                "filters": {"start_date": "2030-01-01", "end_date": "2030-06-30"},
                "group_by": ["month"],
            },
        ),
    }
    started = time.perf_counter()
    results: dict[str, list[tuple[float, bool]]] = {name: [] for name in workloads}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(
                _safe_request_ms, api, method, path, body, None if name == "health" else token
            ): name
            for name, (method, path, body) in workloads.items()
            for _ in range(n)
        }
        for future in as_completed(futures):
            results[futures[future]].append(future.result())
    elapsed = max(time.perf_counter() - started, 0.001)
    report = {}
    for name, samples in results.items():
        latencies = [latency for latency, _ok in samples]
        report[name] = {
            **summarize(latencies),
            "errors": sum(not ok for _latency, ok in samples),
        }
    report["total_requests"] = sum(len(samples) for samples in results.values())
    report["elapsed_s"] = round(elapsed, 3)
    report["achieved_qps"] = round(report["total_requests"] / elapsed, 2)
    return report


def api_port(api: str) -> int | None:
    parsed = urllib.parse.urlparse(api)
    if parsed.port is not None:
        return parsed.port
    if parsed.scheme == "https":
        return 443
    if parsed.scheme == "http":
        return 80
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Live API p50/p95 capture (client only).")
    parser.add_argument("--n", type=int, default=int(os.environ.get("MARKETDESK_LOAD_N", "20")))
    parser.add_argument(
        "--workers", type=int, default=int(os.environ.get("MARKETDESK_LOAD_WORKERS", "4"))
    )
    parser.add_argument("--api", default=os.environ.get("MARKETDESK_API", DEFAULT_API))
    args = parser.parse_args()
    if args.n < 1:
        print("n must be >= 1", file=sys.stderr)
        return 2
    api = args.api.rstrip("/")
    port = api_port(api)
    if port in FORBIDDEN_PORTS:
        print(f"refusing API port {port}; never bind or target 3000/8000", file=sys.stderr)
        return 2

    try:
        login_ms, login_body = request_ms(
            api,
            "POST",
            "/v1/auth/demo",
            {"email": "analyst@marketdesk.test", "workspace": "harbor"},
        )
        token = json.loads(login_body)["access_token"]
        report = {
            "api": api,
            "login_ms": round(login_ms, 2),
            "mixed_workload": _measure_mixed_workload(api, token, args.n, args.workers),
        }

        def burst():
            return request_ms(api, "GET", "/health")[0]

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futs = [pool.submit(burst) for _ in range(args.n)]
            report["health_concurrent"] = summarize([f.result() for f in as_completed(futs)])
            report["workers"] = args.workers
    except urllib.error.URLError as exc:
        reason = exc.reason if getattr(exc, "reason", None) is not None else exc
        print(json.dumps({"ok": False, "api": api, "error": str(reason)}), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
