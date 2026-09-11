"""Metrics and tracing helpers."""

from prometheus_client import Counter, Histogram

REQUESTS = Counter("marketdesk_requests_total", "API requests", ["capability", "status"])
LATENCY = Histogram("marketdesk_stage_seconds", "Workflow stage latency", ["stage"])
UNAUTHORIZED_SURVIVORS = Counter(
    "marketdesk_unauthorized_candidates_total",
    "Candidates dropped by canonical permission recheck",
)
