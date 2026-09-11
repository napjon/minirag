from __future__ import annotations

import json

from scripts.release_ledger import ledger_summary, load_ledger, rubric_ids, validate_ledger
from scripts.synthetic_evidence import GATE_SPECS, build_synthetic_manifest
from scripts.verify_release import build_scorecard


def test_release_ledger_covers_all_rubric_rows_and_four_hard_gates():
    ledger = load_ledger()

    assert validate_ledger(ledger) == []
    assert len(ledger["items"]) == 48
    assert {
        item["criterion_id"] for item in ledger["items"] if item["kind"] == "rubric"
    } == rubric_ids()
    assert sum(item["kind"] == "hard_gate" for item in ledger["items"]) == 4
    assert {week["week"] for week in ledger["weeks"]} == set(range(1, 11))
    assert set(ledger_summary(ledger)["weekly_status"]) == {str(week) for week in range(1, 11)}
    assert ledger_summary(ledger)["open_blockers"]


def test_synthetic_manifest_has_required_populations_and_explicit_warning():
    manifest = build_synthetic_manifest()

    assert manifest["scope"] == "synthetic_contract"
    assert "cannot close" in manifest["warning"]
    assert len(manifest["gates"]) == len(GATE_SPECS)
    assert {gate["gate_id"] for gate in manifest["gates"]} == {
        spec["gate_id"] for spec in GATE_SPECS
    }
    assert all(gate["generated_case_count"] == gate["population"] for gate in manifest["gates"])


def test_scorecard_demo_mode_keeps_production_verdict_open(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.verify_release.run_checks",
        lambda **_: [
            {
                "name": "synthetic_contract",
                "command": "fixture",
                "cwd": ".",
                "status": "passed",
                "returncode": 0,
                "duration_ms": 1,
                "stdout": "",
                "stderr": "",
            }
        ],
    )

    scorecard = build_scorecard(output_dir=tmp_path)

    assert scorecard["verdict"]["demo_ready"] is True
    assert scorecard["verdict"]["production_ready"] is False
    assert scorecard["open_blockers"]
    assert (tmp_path / "scorecard.json").exists()
    assert (tmp_path / "summary.md").exists()
    assert (tmp_path / "synthetic-gates.json").exists()
    assert json.loads((tmp_path / "scorecard.json").read_text())["scope"] == "synthetic_demo"


def test_assumed_synthetic_closeout_covers_all_items_without_promoting_them(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.verify_release.run_checks",
        lambda **_: [
            {
                "name": "synthetic_contract",
                "command": "fixture",
                "cwd": ".",
                "status": "passed",
                "returncode": 0,
                "duration_ms": 1,
                "stdout": "",
                "stderr": "",
            }
        ],
    )

    scorecard = build_scorecard(output_dir=tmp_path, assume_synthetic=True)
    closeout = json.loads((tmp_path / "assumed-closeout.json").read_text())

    assert scorecard["verdict"]["assumed_demo_ready"] is True
    assert scorecard["verdict"]["production_ready"] is False
    assert len(closeout) == 48
    assert {item["status"] for item in closeout} == {"assumed_pass"}
    assert all(item["scope"] == "synthetic_demo" for item in closeout)


def test_scorecard_can_emit_explicit_synthetic_closeout(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.verify_release.run_checks",
        lambda **_: [
            {
                "name": "synthetic_contract",
                "command": "fixture",
                "cwd": ".",
                "status": "passed",
                "returncode": 0,
                "duration_ms": 1,
                "stdout": "",
                "stderr": "",
            }
        ],
    )

    scorecard = build_scorecard(output_dir=tmp_path, assume_synthetic=True)

    assert scorecard["verdict"]["assumed_demo_ready"] is True
    assert scorecard["verdict"]["production_ready"] is False
    assert scorecard["assumed_closeout"]["item_count"] == 48
    closeout = json.loads((tmp_path / "assumed-closeout.json").read_text())
    assert len(closeout) == 48
    assert all(item["status"] == "assumed_pass" for item in closeout)
