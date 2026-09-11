"""Load and validate the anonymized release closeout ledger.

The ledger is deliberately separate from the runtime scorecard.  A design or a
passing unit test can show that an implementation exists, but it cannot close a
production acceptance gate.  The verifier therefore keeps implementation and
verification status as two independent fields.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = ROOT / "release" / "ledger.json"
RUBRIC_DOC = ROOT / "docs" / "eval-rubric.md"

REQUIRED_FIELDS = {
    "finding_id",
    "kind",
    "criterion_id",
    "week",
    "area",
    "description",
    "acceptance",
    "implementation_status",
    "verification_status",
    "status",
    "evidence_command",
    "evidence_artifact",
    "owner_role",
    "release_impact",
    "assumption",
}
VALID_KINDS = {"rubric", "hard_gate"}
VALID_IMPLEMENTATION = {"implemented", "planned"}
VALID_VERIFICATION = {"tested", "unverified"}
VALID_STATUS = {
    "implemented_tested",
    "implemented_unverified",
    "planned",
    "blocked",
}
STATUS_ORDER = ("implemented_tested", "implemented_unverified", "planned", "blocked")


def load_ledger(path: Path | None = None) -> dict[str, Any]:
    """Read a release ledger from JSON."""

    target = path or DEFAULT_LEDGER
    return json.loads(target.read_text(encoding="utf-8"))


def rubric_ids(path: Path | None = None) -> set[str]:
    """Return the 44 criterion IDs declared by the rubric document."""

    text = (path or RUBRIC_DOC).read_text(encoding="utf-8")
    return set(re.findall(r"\| ([A-D]-T\d-\d{2}) \|", text))


def validate_ledger(
    ledger: dict[str, Any],
    *,
    expected_rubric_ids: set[str] | None = None,
) -> list[str]:
    """Return human-readable validation errors; an empty list means valid."""

    errors: list[str] = []
    if ledger.get("schema_version") != "1.0":
        errors.append("schema_version must be 1.0")
    items = ledger.get("items")
    if not isinstance(items, list):
        return ["items must be a list"]
    weeks = ledger.get("weeks")
    if not isinstance(weeks, list) or {
        week.get("week") for week in weeks if isinstance(week, dict)
    } != set(range(1, 11)):
        errors.append("weeks must contain exactly week numbers 1 through 10")
    else:
        for index, week in enumerate(weeks):
            prefix = f"weeks[{index}]"
            for field in ("title", "exit_evidence", "owner_role", "assumption"):
                if not isinstance(week.get(field), str) or not week[field].strip():
                    errors.append(f"{prefix}.{field} must be a non-empty string")
            if week.get("status") not in VALID_STATUS:
                errors.append(f"{prefix}.status is invalid")
            if week.get("release_impact") != "blocking":
                errors.append(f"{prefix}.release_impact must be blocking")

    seen_finding_ids: set[str] = set()
    seen_criteria: set[str] = set()
    for index, item in enumerate(items):
        prefix = f"items[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        missing = REQUIRED_FIELDS - set(item)
        errors.extend(f"{prefix} missing {field}" for field in sorted(missing))
        finding_id = item.get("finding_id")
        if not isinstance(finding_id, str) or not finding_id:
            errors.append(f"{prefix}.finding_id must be a non-empty string")
        elif finding_id in seen_finding_ids:
            errors.append(f"duplicate finding_id: {finding_id}")
        else:
            seen_finding_ids.add(finding_id)
        kind = item.get("kind")
        if kind not in VALID_KINDS:
            errors.append(f"{prefix}.kind must be one of {sorted(VALID_KINDS)}")
        criterion_id = item.get("criterion_id")
        if kind == "rubric":
            if not isinstance(criterion_id, str) or not re.fullmatch(
                r"[A-D]-T\d-\d{2}", criterion_id
            ):
                errors.append(f"{prefix}.criterion_id must be a rubric ID")
            elif criterion_id in seen_criteria:
                errors.append(f"duplicate rubric criterion: {criterion_id}")
            else:
                seen_criteria.add(criterion_id)
        elif criterion_id is not None:
            errors.append(f"{prefix}.criterion_id must be null for a hard gate")
        if item.get("implementation_status") not in VALID_IMPLEMENTATION:
            errors.append(f"{prefix}.implementation_status is invalid")
        if item.get("verification_status") not in VALID_VERIFICATION:
            errors.append(f"{prefix}.verification_status is invalid")
        expected_status = {
            ("implemented", "tested"): "implemented_tested",
            ("implemented", "unverified"): "implemented_unverified",
            ("planned", "unverified"): "planned",
        }.get((item.get("implementation_status"), item.get("verification_status")))
        if item.get("status") not in VALID_STATUS:
            errors.append(f"{prefix}.status is invalid")
        elif expected_status and item["status"] != expected_status and item["status"] != "blocked":
            errors.append(
                f"{prefix}.status must be {expected_status!r} for the "
                "implementation/verification pair"
            )
        if item.get("release_impact") not in {"blocking", "non_blocking"}:
            errors.append(f"{prefix}.release_impact must be blocking or non_blocking")
        if not isinstance(item.get("week"), int) or not 1 <= item["week"] <= 10:
            errors.append(f"{prefix}.week must be an integer from 1 to 10")
        for field in (
            "description",
            "acceptance",
            "evidence_command",
            "evidence_artifact",
            "owner_role",
        ):
            if not isinstance(item.get(field), str) or not item[field].strip():
                errors.append(f"{prefix}.{field} must be a non-empty string")

    if len(items) != 48:
        errors.append(f"expected exactly 48 release items, found {len(items)}")
    expected = expected_rubric_ids if expected_rubric_ids is not None else rubric_ids()
    missing_criteria = sorted(expected - seen_criteria)
    extra_criteria = sorted(seen_criteria - expected)
    errors.extend(f"missing rubric criterion: {criterion}" for criterion in missing_criteria)
    errors.extend(f"unknown rubric criterion: {criterion}" for criterion in extra_criteria)
    hard_gates = [item for item in items if item.get("kind") == "hard_gate"]
    if len(hard_gates) != 4:
        errors.append(f"expected exactly 4 hard gates, found {len(hard_gates)}")
    return errors


def ledger_summary(ledger: dict[str, Any]) -> dict[str, Any]:
    """Summarize status without turning synthetic checks into release approval."""

    items = ledger.get("items", [])
    status_counts = {
        status: sum(item.get("status") == status for item in items) for status in STATUS_ORDER
    }
    return {
        "total": len(items),
        "rubric_total": sum(item.get("kind") == "rubric" for item in items),
        "hard_gate_total": sum(item.get("kind") == "hard_gate" for item in items),
        "weekly_status": {
            str(week.get("week")): week.get("status") for week in ledger.get("weeks", [])
        },
        "status_counts": status_counts,
        "open_blockers": [
            item["finding_id"]
            for item in items
            if item.get("release_impact") == "blocking"
            and item.get("status") in {"planned", "implemented_unverified", "blocked"}
        ],
    }
