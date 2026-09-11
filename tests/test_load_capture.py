from __future__ import annotations

from scripts import load_capture


def test_default_api_matches_local_api_port():
    assert load_capture.DEFAULT_API == "http://127.0.0.1:8130"


def test_mixed_workload_reports_all_routes_and_qps(monkeypatch):
    def fake_request(*_args, **_kwargs):
        return 5.0, b"{}"

    monkeypatch.setattr(load_capture, "request_ms", fake_request)
    report = load_capture._measure_mixed_workload("http://127.0.0.1:8130", "token", 2, 4)

    assert report["total_requests"] == 8
    assert report["achieved_qps"] > 0
    assert set(report) >= {"health", "questions", "search", "analytics", "total_requests"}
    assert all(
        report[name]["errors"] == 0 for name in ("health", "questions", "search", "analytics")
    )
