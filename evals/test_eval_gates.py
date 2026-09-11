from __future__ import annotations

import pytest

from evals.runner import (
    HTTP_CAPABILITIES,
    _execute_case,
    case_id,
    grade_case,
    load_cases,
)

CASES = load_cases()
HTTP_CASES = [case for case in CASES if case.get("capability") in HTTP_CAPABILITIES]
CASE_IDS = [case_id(case) for case in HTTP_CASES] or ["empty"]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", HTTP_CASES, ids=CASE_IDS)
async def test_eval_cases_execute(client, case):
    if not HTTP_CASES:
        pytest.skip("eval cases not generated yet")
    result = await _execute_case(client, case, "harbor", "analyst@marketdesk.test")
    if result.get("status") == "skipped" or str(result.get("reason") or "").startswith("skipped"):
        pytest.skip(result.get("reason") or "skipped")
    assert result["pass"], result.get("reason")


def test_invented_citation_grader_fails_without_stripping():
    case = {
        "id": "invented_citation",
        "capability": "questions",
        "expected": {"status": "answered", "claims_must_cite_evidence": True},
    }
    body = {
        "status": "answered",
        "evidence": [{"chunk_id": "real-id"}],
        "result": {
            "claims": [
                {"text": "supported", "evidence_id": "real-id"},
                {
                    "text": "hallucinated",
                    "evidence_id": "invented-id-not-in-evidence",
                },
            ]
        },
    }
    ok, reason = grade_case(case, body)
    assert ok is False
    assert "invented citation" in reason
