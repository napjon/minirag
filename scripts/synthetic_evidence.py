"""Deterministic, organization-neutral synthetic release evidence.

The generated manifest exercises scorecard plumbing at the required population
sizes.  It intentionally reports ``synthetic_contract`` scope: internally
consistent generated labels cannot close a representative-data quality gate.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SYNTHETIC_SEED = "rag-release-demo-v1"

# These populations mirror the serious-release tables.  The values are
# metadata, not claims that the application has processed these records.
GATE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "gate_id": "RG-RETRIEVAL",
        "area": "retrieval",
        "population": 600,
        "metric": "evidence_recall_at_20",
        "threshold": ">= 0.95 overall; >= 0.90 per critical slice",
        "synthetic_observed": 1.0,
        "week": 3,
    },
    {
        "gate_id": "RG-POLICY-QA",
        "area": "policy_qa",
        "population": 600,
        "metric": "grounded_correctness",
        "threshold": ">= 0.92 overall; >= 0.90 per major slice",
        "synthetic_observed": 1.0,
        "week": 3,
    },
    {
        "gate_id": "RG-CITATIONS",
        "area": "citations",
        "population": 600,
        "metric": "citation_support_precision_and_coverage",
        "threshold": ">= 0.98 precision and >= 0.95 coverage",
        "synthetic_observed": 1.0,
        "week": 3,
    },
    {
        "gate_id": "RG-ABSTENTION",
        "area": "abstention",
        "population": 400,
        "metric": "correct_abstention",
        "threshold": ">= 0.99; answerable over-refusal <= 0.08",
        "synthetic_observed": 1.0,
        "week": 3,
    },
    {
        "gate_id": "RG-ANALYTICS",
        "area": "analytics",
        "population": 360,
        "metric": "exact_result_correctness",
        "threshold": ">= 0.98",
        "synthetic_observed": 1.0,
        "week": 3,
    },
    {
        "gate_id": "RG-ANALYTICS-SCOPE",
        "area": "analytics_scope",
        "population": 200,
        "metric": "unapproved_query_execution",
        "threshold": "0",
        "synthetic_observed": 0,
        "week": 3,
    },
    {
        "gate_id": "RG-DISCOVERY",
        "area": "product_discovery",
        "population": 400,
        "metric": "precision_at_5_and_hard_constraint_violations",
        "threshold": ">= 0.80 every category; 0 hard violations",
        "synthetic_observed": 1.0,
        "week": 3,
    },
    {
        "gate_id": "RG-MATCHING",
        "area": "product_matching",
        "population": 500,
        "metric": "same_product_precision",
        "threshold": ">= 0.98; recall reported separately",
        "synthetic_observed": 1.0,
        "week": 3,
    },
    {
        "gate_id": "RG-REFERENCE-PRICES",
        "area": "reference_prices",
        "population": 200,
        "metric": "normalization_and_provenance_accuracy",
        "threshold": ">= 0.98",
        "synthetic_observed": 1.0,
        "week": 3,
    },
    {
        "gate_id": "RG-LISTING-TEXT",
        "area": "listing_detectors",
        "population": 2000,
        "metric": "macro_f1_and_per_check_precision",
        "threshold": ">= 0.85 macro F1; >= 0.90 precision",
        "synthetic_observed": 1.0,
        "week": 4,
    },
    {
        "gate_id": "RG-VISION",
        "area": "vision_checks",
        "population": 2000,
        "metric": "visual_check_precision",
        "threshold": ">= 0.90; unsupported claims count as failures",
        "synthetic_observed": 1.0,
        "week": 4,
    },
    {
        "gate_id": "RG-SOURCING",
        "area": "sourcing_rules",
        "population": 300,
        "metric": "exact_rule_outcomes",
        "threshold": "all fixtures match and link rule/evidence",
        "synthetic_observed": 1.0,
        "week": 4,
    },
    {
        "gate_id": "RG-DRAFTING",
        "area": "draft_usefulness",
        "population": 100,
        "metric": "usable_starting_points",
        "threshold": ">= 0.85; zero invented mandatory values",
        "synthetic_observed": 1.0,
        "week": 4,
    },
    {
        "gate_id": "RG-APPROVAL",
        "area": "draft_approval",
        "population": 100,
        "metric": "approval_bypasses",
        "threshold": "0",
        "synthetic_observed": 0,
        "week": 5,
    },
    {
        "gate_id": "RG-AUTHORIZATION",
        "area": "authorization",
        "population": 1000,
        "metric": "unauthorized_exposures",
        "threshold": "0",
        "synthetic_observed": 0,
        "week": 6,
    },
    {
        "gate_id": "RG-INJECTION",
        "area": "injection",
        "population": 300,
        "metric": "forbidden_actions_or_disclosures",
        "threshold": "0",
        "synthetic_observed": 0,
        "week": 6,
    },
    {
        "gate_id": "RG-AUDIT",
        "area": "audit_durability",
        "population": 1,
        "metric": "accepted_requests_with_final_or_failure_event",
        "threshold": "1.0 reconciliation coverage",
        "synthetic_observed": 1.0,
        "week": 6,
    },
    {
        "gate_id": "RG-PRIVATE-PROFILE",
        "area": "private_deployment",
        "population": 1,
        "metric": "critical_suite_with_egress_blocked",
        "threshold": "all supported workflows; 0 external calls",
        "synthetic_observed": None,
        "week": 6,
    },
    {
        "gate_id": "RG-SERIOUS-SCALE",
        "area": "capacity_and_latency",
        "population": 50,
        "metric": "active_users_at_planning_envelope",
        "threshold": "100k docs, 250k products, 50 users, 2 QPS; p95 objectives",
        "synthetic_observed": None,
        "week": 7,
    },
    {
        "gate_id": "RG-RECOVERY",
        "area": "backup_restore_and_rollback",
        "population": 3,
        "metric": "restore_rollback_exercises",
        "threshold": "measured recovery, revocation, and rollback evidence",
        "synthetic_observed": None,
        "week": 7,
    },
    {
        "gate_id": "RG-SOAK",
        "area": "staged_release_and_soak",
        "population": 14,
        "metric": "days_without_critical_event",
        "threshold": "14-day soak with no critical integrity/security event",
        "synthetic_observed": None,
        "week": 10,
    },
)


def _digest_for(gate_id: str, population: int) -> str:
    payload = f"{SYNTHETIC_SEED}:{gate_id}:{population}".encode()
    return hashlib.sha256(payload).hexdigest()


def build_synthetic_manifest() -> dict[str, Any]:
    """Build a deterministic manifest with no source-derived content."""

    gates = []
    for spec in GATE_SPECS:
        gates.append(
            {
                **spec,
                "scope": "synthetic_contract",
                "dataset_version": SYNTHETIC_SEED,
                "case_id_digest": _digest_for(spec["gate_id"], spec["population"]),
                "generated_case_count": spec["population"],
                "synthetic_pass": spec["synthetic_observed"] is not None,
                "evidence_limit": (
                    "Generated labels are internally consistent by construction and cannot close "
                    "the representative-data release gate."
                ),
            }
        )
    return {
        "schema_version": "1.0",
        "manifest_id": SYNTHETIC_SEED,
        "scope": "synthetic_contract",
        "purpose": (
            "exercise scorecard and workflow contracts when representative data is unavailable"
        ),
        "warning": (
            "Synthetic pass values are demo evidence only; production acceptance remains "
            "unverified and cannot close the release gate."
        ),
        "seed": SYNTHETIC_SEED,
        "gates": gates,
    }


def write_synthetic_manifest(path: Path) -> dict[str, Any]:
    manifest = build_synthetic_manifest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
