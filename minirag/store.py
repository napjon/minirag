"""SQLite storage: traces (what the monitor shows), the hash-chained audit log
(Quest Level 7), feedback and evaluation runs. One file: .data/minirag.db
"""

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS trace(
  id TEXT PRIMARY KEY, ts REAL, kind TEXT, run_id TEXT, question TEXT, status TEXT, reason TEXT,
  total_ms REAL, top_score REAL, groundedness REAL, golden_pass INTEGER, model TEXT, body TEXT);
CREATE INDEX IF NOT EXISTS trace_ts ON trace(ts);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY, ts REAL, trace_id TEXT, question TEXT, answer TEXT,
  sources TEXT, model TEXT, prev_hash TEXT, hash TEXT);
CREATE TABLE IF NOT EXISTS feedback(trace_id TEXT PRIMARY KEY, helpful INTEGER, note TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS eval_run(
  id TEXT PRIMARY KEY, ts REAL, provider TEXT, model TEXT, embed_model TEXT, passed INTEGER, body TEXT);
"""


class Store:
    def __init__(self, data_dir: Path):
        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "minirag.db"
        with self._db() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    # ---- audit log: each row's hash covers the previous row's hash -----------------
    def log_audit(self, trace_id: str, question: str, answer: str, sources: list[str], model: str) -> dict:
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")            # one writer at a time: the chain stays linear
            last = db.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
            prev = last["hash"] if last else "start"
            row = [time.time(), trace_id, question, answer, json.dumps(sources), model, prev]
            h = hashlib.sha256(json.dumps(row).encode()).hexdigest()
            db.execute("INSERT INTO audit(ts,trace_id,question,answer,sources,model,prev_hash,hash) "
                       "VALUES (?,?,?,?,?,?,?,?)", row + [h])
            db.execute("COMMIT")                     # if this raises, the caller must not answer
        return {"hash": h, "prev_hash": prev}

    def verify_chain(self) -> dict:
        prev, n = "start", 0
        with self._db() as db:
            for r in db.execute("SELECT id,ts,trace_id,question,answer,sources,model,prev_hash,hash "
                                "FROM audit ORDER BY id"):
                row = [r["ts"], r["trace_id"], r["question"], r["answer"], r["sources"], r["model"], r["prev_hash"]]
                if r["prev_hash"] != prev or hashlib.sha256(json.dumps(row).encode()).hexdigest() != r["hash"]:
                    return {"ok": False, "rows": n, "broken_at": r["id"]}
                prev, n = r["hash"], n + 1
        return {"ok": True, "rows": n, "broken_at": None}

    # ---- traces ---------------------------------------------------------------------
    def save_trace(self, t: dict) -> None:
        golden = t.get("golden") or {}
        with self._db() as db:
            db.execute(
                "INSERT OR REPLACE INTO trace VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (t["id"], t["ts"], t["kind"], t.get("run_id"), t["question"], t["outcome"]["status"],
                 t["outcome"]["reason"], t["total_ms"], t["scores"].get("top_score"),
                 t["scores"].get("groundedness"),
                 None if golden.get("passed") is None else int(golden["passed"]),
                 t["models"]["generation"], json.dumps(t)))

    def get_trace(self, trace_id: str) -> dict | None:
        with self._db() as db:
            r = db.execute("SELECT body FROM trace WHERE id=?", (trace_id,)).fetchone()
            if not r:
                return None
            t = json.loads(r["body"])
            f = db.execute("SELECT helpful, note FROM feedback WHERE trace_id=?", (trace_id,)).fetchone()
            t["feedback"] = {"helpful": bool(f["helpful"]), "note": f["note"]} if f else None
            return t

    def list_traces(self, kind: str | None = None, limit: int = 50) -> list[dict]:
        sql = ("SELECT t.id,t.ts,t.kind,t.run_id,t.question,t.status,t.reason,t.total_ms,t.top_score,"
               "t.groundedness,t.golden_pass,t.model,f.helpful FROM trace t "
               "LEFT JOIN feedback f ON f.trace_id=t.id")
        args: list = []
        if kind:
            sql += " WHERE t.kind=?"
            args.append(kind)
        with self._db() as db:
            return [dict(r) for r in db.execute(sql + " ORDER BY t.ts DESC LIMIT ?", args + [limit])]

    def overview(self) -> dict:
        """Numbers for live traffic only; evaluation runs are reported on their own page."""
        with self._db() as db:
            rows = db.execute("SELECT status,reason,total_ms,groundedness FROM trace WHERE kind='live'").fetchall()
            fb = db.execute("SELECT COALESCE(SUM(helpful),0) up, COUNT(*) n FROM feedback").fetchone()
        ms = sorted(r["total_ms"] for r in rows)
        grounded = [r["groundedness"] for r in rows if r["groundedness"] is not None]
        reasons: dict[str, int] = {}
        for r in rows:
            if r["status"] != "answered":
                reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
        n = len(rows)
        return {
            "queries": n,
            "answered": sum(r["status"] == "answered" for r in rows),
            "refused": sum(r["status"] == "refused" for r in rows),
            "errors": sum(r["status"] == "error" for r in rows),
            "refusal_reasons": reasons,
            "p50_ms": percentile(ms, 0.5), "p95_ms": percentile(ms, 0.95),
            "groundedness": round(sum(grounded) / len(grounded), 3) if grounded else None,
            "feedback": {"helpful": fb["up"], "total": fb["n"]},
            "audit": self.verify_chain(),
        }

    # ---- feedback and evaluation runs -----------------------------------------------
    def add_feedback(self, trace_id: str, helpful: bool, note: str) -> None:
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO feedback VALUES (?,?,?,?)", (trace_id, int(helpful), note, time.time()))

    def save_eval_run(self, run: dict) -> None:
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO eval_run VALUES (?,?,?,?,?,?,?)",
                       (run["id"], run["ts"], run["provider"], run["models"]["generation"],
                        run["models"]["embedding"], int(run["passed"]), json.dumps(run)))

    def list_eval_runs(self, limit: int = 30) -> list[dict]:
        with self._db() as db:
            rows = db.execute("SELECT body FROM eval_run ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            run = json.loads(r["body"])
            run.pop("cases", None)
            out.append(run)
        return out

    def get_eval_run(self, run_id: str) -> dict | None:
        with self._db() as db:
            r = db.execute("SELECT body FROM eval_run WHERE id=?", (run_id,)).fetchone()
        return json.loads(r["body"]) if r else None


def percentile(sorted_xs: list[float], q: float) -> float | None:
    if not sorted_xs:
        return None
    return round(sorted_xs[min(len(sorted_xs) - 1, int(q * len(sorted_xs)))], 1)
