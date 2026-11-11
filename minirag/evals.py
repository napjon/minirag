"""Quest Level 2 (measure) and Level 9 (time every stage), over the golden set.

Each case runs through the real pipeline, so every evaluated question also leaves
a trace you can open in the monitor.
"""

import json
import time
import uuid

from .pipeline import ANSWER_PATH, Engine
from .store import percentile

_ORDER = ["rewrite", "retrieve", "rerank", "gate", "generate", "ground", "score", "total"]


def _mean(xs: list) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def run_eval(engine: Engine, progress=None) -> dict:
    cases = engine.golden["cases"]
    gates = engine.golden.get("gates", {})
    run_id = "run-" + uuid.uuid4().hex[:8]
    rows, stage_ms = [], {}
    for n, case in enumerate(cases, start=1):
        t = engine.answer(case["q"], history=case.get("history"), kind="eval", run_id=run_id)
        g, out = t["golden"], t["outcome"]
        for st in t["stages"]:
            stage_ms.setdefault(st["name"], []).append(st["ms"])
        stage_ms.setdefault("total", []).append(t["total_ms"])
        if case["type"] == "out_of_scope":
            expected = None                    # any path is fine as long as it ends in a refusal
            traj_ok = t["trajectory"][-1] == "refuse"
        else:
            expected = (["rewrite"] if case["type"] == "follow_up" else []) + ANSWER_PATH
            traj_ok = [x for x in t["trajectory"] if x != "score"] == expected
        rows.append({
            "id": case["id"], "type": case["type"], "q": case["q"], "trace_id": t["id"],
            "status": out["status"], "reason": out["reason"], "answer": out["answer"],
            "passed": g["passed"], "expected": g["expected"],
            "retrieved_rank": g.get("retrieved_rank"), "candidate_rank": g.get("candidate_rank"),
            "cited_expected": g.get("cited_expected"),
            "top_score": t["scores"]["top_score"], "groundedness": t["scores"]["groundedness"],
            "trajectory": t["trajectory"], "trajectory_ok": traj_ok,
            "refused_at_gate": out["reason"] == "below_score_floor", "ms": t["total_ms"],
        })
        if progress:
            progress(n, len(cases))

    scoped = [r for r in rows if r["type"] != "out_of_scope"]
    oos = [r for r in rows if r["type"] == "out_of_scope"]
    answered = [r for r in scoped if r["status"] == "answered"]
    metrics = {
        # retrieval: did the right section reach the model (top k), or at least the candidate pool?
        "recall_at_k": _mean([r["retrieved_rank"] is not None for r in scoped]),
        "candidate_recall": _mean([r["candidate_rank"] is not None for r in scoped]),
        "mrr": _mean([1 / r["retrieved_rank"] if r["retrieved_rank"] else 0 for r in scoped]),
        # answers
        "answer_accuracy": _mean([r["passed"] for r in scoped]),
        "citation_accuracy": _mean([r["cited_expected"] for r in answered]),
        "groundedness": _mean([r["groundedness"] for r in scoped]),
        # refusals
        "refusal_rate": _mean([r["passed"] for r in oos]),
        "refused_at_gate": _mean([r["refused_at_gate"] for r in oos]),
        "false_refusal_rate": _mean([r["status"] != "answered" for r in scoped]),
        # agent path
        "trajectory_match": _mean([r["trajectory_ok"] for r in rows]),
    }
    gate_results = {}
    for name, limit in gates.items():
        is_max = name.endswith("_max")
        value = metrics.get(name.removesuffix("_max"))
        ok = value is not None and (value <= limit if is_max else value >= limit)
        gate_results[name] = {"limit": limit, "value": value, "passed": ok}
    return {
        "id": run_id, "ts": time.time(), "provider": engine.provider.name,
        "models": {"generation": engine.provider.gen_model, "embedding": engine.provider.embed_model},
        "config": {"top_k": engine.s.top_k, "candidates": engine.s.candidates,
                   "score_floor": engine.floor()[0], "support_floor": engine.s.support_floor},
        "counts": {"in_scope": len(scoped), "out_of_scope": len(oos), "total": len(rows)},
        "metrics": metrics, "gates": gate_results,
        "passed": all(g["passed"] for g in gate_results.values()),
        "latency_ms": {name: {"p50": percentile(sorted(xs), 0.5), "p95": percentile(sorted(xs), 0.95), "n": len(xs)}
                       for name, xs in sorted(stage_ms.items(), key=lambda kv: _ORDER.index(kv[0]))},
        "cases": rows,
    }


def calibrate(engine: Engine) -> dict:
    """Pick the score floor from the golden set: retrieval only, no generation.
    The floor sits between the weakest in-scope top score and the strongest out-of-scope one."""
    inside, outside = [], []
    for case in engine.golden["cases"]:
        if case["type"] == "follow_up":
            continue                       # needs the rewrite model; the floor is about retrieval
        cands, _ = engine.retrieve([case["q"]])
        top = cands[0]["rerank_score"] if cands else 0.0
        (outside if case["type"] == "out_of_scope" else inside).append(top)
    lo, hi = max(outside), min(inside)
    if lo < hi:
        floor, separable = (lo + hi) / 2, True
    else:   # they overlap: choose the threshold with the fewest mistakes
        floor = min(sorted(set(inside + outside)),
                    key=lambda th: sum(x < th for x in inside) + sum(x >= th for x in outside))
        separable = False
    cal = {"provider": engine.provider.name, "embed_model": engine.provider.embed_model,
           "floor": round(floor, 4), "separable": separable,
           "in_scope_min": round(hi, 4), "out_of_scope_max": round(lo, 4), "ts": time.time()}
    engine.s.data_dir.mkdir(parents=True, exist_ok=True)
    (engine.s.data_dir / "calibration.json").write_text(json.dumps(cal, indent=2))
    return cal
