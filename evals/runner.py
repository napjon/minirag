"""Run the golden set and print the scorecard.

  uv run python evals/runner.py              run, save, exit 1 if a gate fails
  uv run python evals/runner.py --no-gate    report only
  uv run python evals/runner.py --calibrate  set the score floor from the golden set
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from minirag.evals import calibrate, run_eval  # noqa: E402
from minirag.pipeline import Engine  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-gate", action="store_true")
    ap.add_argument("--calibrate", action="store_true")
    args = ap.parse_args()
    engine = Engine()
    print(f"provider={engine.provider.name}  generation={engine.provider.gen_model}  "
          f"embedding={engine.provider.embed_model}  chunks={len(engine.index.chunks)}")

    if args.calibrate:
        cal = calibrate(engine)
        print(f"score floor = {cal['floor']}  (weakest in-scope {cal['in_scope_min']}, "
              f"strongest out-of-scope {cal['out_of_scope_max']}, separable={cal['separable']})")
        return 0

    def progress(n, total):
        if sys.stdout.isatty():
            print(f"\r  case {n}/{total}", end="", flush=True)

    run = run_eval(engine, progress)
    engine.store.save_eval_run(run)
    out = engine.s.data_dir / "last-eval.json"
    out.write_text(json.dumps(run, indent=2))
    print(f"\n\n{'metric':24s} {'value':>8s}   gate")
    for name, value in run["metrics"].items():
        gate = run["gates"].get(name) or run["gates"].get(name + "_max")
        mark = "" if not gate else (f"{'PASS' if gate['passed'] else 'FAIL'} "
                                    f"({'<=' if name + '_max' in run['gates'] else '>='} {gate['limit']})")
        print(f"{name:24s} {'-' if value is None else f'{value:.3f}':>8s}   {mark}")
    print(f"\n{'stage':12s} {'p50 ms':>9s} {'p95 ms':>9s} {'n':>4s}")
    for name, lat in run["latency_ms"].items():
        print(f"{name:12s} {lat['p50']:>9.1f} {lat['p95']:>9.1f} {lat['n']:>4d}")
    fails = [c for c in run["cases"] if not c["passed"]]
    if fails:
        print(f"\n{len(fails)} failing case(s):")
        for c in fails:
            print(f"  {c['id']}  [{c['reason']}]  {c['q']}\n       expected {c['expected']!r}, got: {c['answer'][:110]}")
    print(f"\nrun {run['id']} saved to {out}.  Gates: {'PASS' if run['passed'] else 'FAIL'}")
    return 0 if run["passed"] or args.no_gate else 1


if __name__ == "__main__":
    sys.exit(main())
