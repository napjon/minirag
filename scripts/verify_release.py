"""Run available checks and write an explicit release scorecard.

The default command proves that the fictional demo is runnable.  It does not
pretend that a generated fixture set is representative release evidence.  Use
``--strict`` when a CI/release job should fail while any ledger blocker remains
open.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.release_ledger import ledger_summary, load_ledger, validate_ledger
from scripts.synthetic_evidence import write_synthetic_manifest

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "artifacts" / "release"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _path_reference(path: Path) -> str:
    """Use a workspace-relative artifact reference when possible."""

    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _digest_tree() -> str:
    digest = hashlib.sha256()
    ignored_parts = {
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        "artifacts",
    }
    ignored_names = {"last-run.json", "release"}
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if (
            relative.parts[:1] == ("artifacts",)
            or any(part in ignored_parts for part in relative.parts)
            or path.name in ignored_names
        ):
            continue
        digest.update(str(relative).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _run(
    name: str,
    command: Sequence[str],
    *,
    cwd: Path = ROOT,
    skip: bool = False,
) -> dict[str, Any]:
    command_text = shlex.join(command)
    if skip:
        return {
            "name": name,
            "command": command_text,
            "cwd": str(cwd.relative_to(ROOT)),
            "status": "skipped",
            "returncode": None,
            "duration_ms": 0,
            "stdout": "",
            "stderr": "",
        }
    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
    except OSError as exc:
        return {
            "name": name,
            "command": command_text,
            "cwd": str(cwd.relative_to(ROOT)),
            "status": "unavailable",
            "returncode": None,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "stdout": "",
            "stderr": str(exc),
        }
    return {
        "name": name,
        "command": command_text,
        "cwd": str(cwd.relative_to(ROOT)),
        "status": "passed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "stdout": completed.stdout[-6000:],
        "stderr": completed.stderr[-6000:],
    }


def run_checks(*, skip_tests: bool = False, skip_web: bool = False) -> list[dict[str, Any]]:
    """Run repository checks that are available without production services."""

    checks = [
        _run("python_tests", ["uv", "run", "pytest"], skip=skip_tests),
        _run(
            "synthetic_eval_runner",
            [
                "uv",
                "run",
                "python",
                "evals/runner.py",
                "--output",
                "artifacts/release/evals.json",
            ],
            skip=skip_tests,
        ),
        _run("ruff", ["uv", "run", "ruff", "check", "."]),
        _run(
            "ruff_format",
            ["uv", "run", "ruff", "format", "--check", "backend", "evals", "scripts", "tests"],
        ),
        _run(
            "compileall",
            [
                "uv",
                "run",
                "python",
                "-m",
                "compileall",
                "-q",
                "backend",
                "evals",
                "scripts",
                "tests",
            ],
        ),
        _run("alembic_check", ["uv", "run", "alembic", "check"]),
        _run("compose_config", ["docker", "compose", "config", "--quiet"]),
        _run(
            "private_compose_config",
            ["docker", "compose", "-f", "infra/compose.private.yml", "config", "--quiet"],
        ),
        _run("restore_shell_syntax", ["bash", "-n", "scripts/restore.sh"]),
    ]
    if skip_web:
        checks.extend(
            [
                _run("web_tests", ["bun", "test"], cwd=ROOT / "web", skip=True),
                _run("web_build", ["bun", "run", "build"], cwd=ROOT / "web", skip=True),
            ]
        )
    else:
        checks.extend(
            [
                _run("web_tests", ["bun", "test"], cwd=ROOT / "web"),
                _run("web_build", ["bun", "run", "build"], cwd=ROOT / "web"),
            ]
        )
    return checks


def _status_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    statuses = ("implemented_tested", "implemented_unverified", "planned", "blocked")
    return {status: sum(item.get("status") == status for item in items) for status in statuses}


def _assumed_closeout(ledger: dict[str, Any], *, artifact: str) -> list[dict[str, Any]]:
    """Return an explicit demo-only closeout for every ledger item.

    This is intentionally separate from the production ledger.  It records that
    the executable demo checks cover each item under synthetic assumptions; it
    never changes the source ledger's production verification status.
    """

    return [
        {
            "finding_id": item["finding_id"],
            "criterion_id": item.get("criterion_id"),
            "week": item["week"],
            "status": "assumed_pass",
            "scope": "synthetic_demo",
            "evidence_artifact": artifact,
            "assumption": item["assumption"],
            "warning": "Synthetic contract coverage is not representative production evidence.",
        }
        for item in ledger["items"]
    ]


def _markdown(scorecard: dict[str, Any]) -> str:
    verdict = scorecard["verdict"]
    checks = scorecard["checks"]
    summary = scorecard["ledger_summary"]
    lines = [
        "# Release verification scorecard",
        "",
        "This scorecard is for an organization-neutral, fictional RAG demo.",
        "Generated synthetic evidence exercises contracts and scorecard plumbing; it does not "
        "close representative-data or production-scale gates.",
        "",
        f"- Generated: `{scorecard['generated_at']}`",
        f"- Build ID: `{scorecard['build_id']}`",
        f"- Synthetic dataset: `{scorecard['synthetic_dataset_version']}`",
        f"- Demo checks: **{'PASS' if verdict['demo_ready'] else 'FAIL'}**",
        "- Assumed 48-item demo closeout: **"
        f"{'PASS' if verdict['assumed_demo_ready'] else 'OFF'}**",
        f"- Serious release: **{'PASS' if verdict['production_ready'] else 'OPEN'}**",
        f"- Open blocking items: **{len(summary['open_blockers'])} / {summary['total']}**",
        "",
        "## Available checks",
        "",
        "| Check | Status | Duration (ms) | Command |",
        "|---|---|---:|---|",
    ]
    for check in checks:
        lines.append(
            f"| {check['name']} | {check['status']} | {check['duration_ms']} | "
            f"`{check['command']}` |"
        )
    lines.extend(
        [
            "",
            "## Ledger status",
            "",
            "| Status | Count |",
            "|---|---:|",
        ]
    )
    for status, count in summary["status_counts"].items():
        lines.append(f"| {status} | {count} |")
    lines.extend(
        [
            "",
            "## Weekly status",
            "",
            "| Week | Status |",
            "|---:|---|",
        ]
    )
    for week, status in summary["weekly_status"].items():
        lines.append(f"| {week} | {status} |")
    lines.extend(
        [
            "",
            "The serious-release verdict stays open until every blocking item has a closeout "
            "record with representative data, build/configuration identity, an executed "
            "command, an artifact, an owner, and an independent review. A synthetic pass is "
            "intentionally not promoted to `verified`.",
            "",
            "See `release/ledger.json` for the 44 rubric rows plus four cross-cutting release "
            "gates, and `synthetic-gates.json` for the deterministic population manifest.",
            "When `--assume-synthetic` is supplied, `assumed-closeout.json` records all 48 "
            "items as exercised by the demo under explicit synthetic assumptions; that file "
            "does not promote the production verdict.",
            "",
        ]
    )
    return "\n".join(lines)


def build_scorecard(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    skip_tests: bool = False,
    skip_web: bool = False,
    assume_synthetic: bool = False,
) -> dict[str, Any]:
    """Run checks and write JSON/Markdown scorecard artifacts."""

    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger = load_ledger()
    errors = validate_ledger(ledger)
    if errors:
        raise ValueError("invalid release ledger: " + "; ".join(errors))
    synthetic_path = output_dir / "synthetic-gates.json"
    synthetic = write_synthetic_manifest(synthetic_path)
    checks = run_checks(skip_tests=skip_tests, skip_web=skip_web)
    check_failures = [check for check in checks if check["status"] == "failed"]
    unavailable = [check for check in checks if check["status"] == "unavailable"]
    skipped = [check for check in checks if check["status"] == "skipped"]
    summary = ledger_summary(ledger)
    checks_passed = not check_failures and not unavailable and not skipped
    assumed_closeout_path = output_dir / "assumed-closeout.json"
    assumed_closeout = None
    if assume_synthetic:
        assumed_closeout = _assumed_closeout(ledger, artifact=_path_reference(synthetic_path))
        assumed_closeout_path.write_text(
            json.dumps(assumed_closeout, indent=2) + "\n", encoding="utf-8"
        )
    scorecard: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": _utc_now(),
        "build_id": f"working-tree-{_digest_tree()[:16]}",
        "synthetic_dataset_version": synthetic["manifest_id"],
        "mode": "synthetic_demo",
        "scope": "synthetic_demo",
        "checks": checks,
        "synthetic_evidence": {
            "artifact": _path_reference(synthetic_path),
            "scope": synthetic["scope"],
            "warning": synthetic["warning"],
            "gate_count": len(synthetic["gates"]),
        },
        "assumed_closeout": {
            "enabled": assume_synthetic,
            "artifact": (_path_reference(assumed_closeout_path) if assume_synthetic else None),
            "item_count": len(assumed_closeout or []),
            "scope": "synthetic_demo",
            "warning": "Assumed closeout is demo evidence only and never closes production gates.",
        },
        "ledger_summary": summary,
        "verdict": {
            "demo_ready": checks_passed,
            "assumed_demo_ready": bool(assume_synthetic and checks_passed),
            "production_ready": not summary["open_blockers"]
            and not check_failures
            and not unavailable,
            "blocking_reason": (
                "All executable checks passed, but release blockers remain unverified."
                if checks_passed and summary["open_blockers"]
                else None
            ),
        },
        "assumptions": [
            "The corpus and catalog are synthetic and organization-neutral.",
            "Synthetic labels are internally consistent by construction.",
            "No representative authorized corpus, human adjudication, private egress run, "
            "serious-scale load test, restore drill, or 14-day soak was supplied.",
            "A green demo check cannot establish a production quality, security, latency, "
            "cost, or resilience threshold.",
        ],
        "open_blockers": summary["open_blockers"],
        "next_evidence": [
            "Replace synthetic gate manifests with versioned representative data and "
            "independent adjudication.",
            "Run serious-scale mixed-load, cost, recovery, private-profile, and soak jobs.",
            "Attach signed closeout records before changing any item to verified.",
        ],
    }
    json_path = output_dir / "scorecard.json"
    json_path.write_text(json.dumps(scorecard, indent=2) + "\n", encoding="utf-8")
    (output_dir / "summary.md").write_text(_markdown(scorecard), encoding="utf-8")
    print(
        f"release verification: demo={'PASS' if scorecard['verdict']['demo_ready'] else 'FAIL'}; "
        f"production={'PASS' if scorecard['verdict']['production_ready'] else 'OPEN'}; "
        f"blockers={len(summary['open_blockers'])}; artifact={_path_reference(json_path)}"
    )
    return scorecard


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Explicitly select synthetic demo mode (the default); production gates remain open",
    )
    parser.add_argument(
        "--no-tests", action="store_true", help="Skip pytest and the HTTP eval runner"
    )
    parser.add_argument("--skip-web", action="store_true", help="Skip web tests and build")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero while any release blocker or check failure remains",
    )
    parser.add_argument(
        "--assume-synthetic",
        action="store_true",
        help="Write an explicit demo-only closeout for all 48 items using synthetic assumptions",
    )
    args = parser.parse_args(argv)
    scorecard = build_scorecard(
        output_dir=args.output_dir,
        skip_tests=args.no_tests,
        skip_web=args.skip_web,
        assume_synthetic=args.assume_synthetic,
    )
    if args.strict and (
        not scorecard["verdict"]["production_ready"]
        or any(check["status"] != "passed" for check in scorecard["checks"])
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
