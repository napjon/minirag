"""Quest Level 12: the pipeline as a local service, plus the monitoring API.
One port serves both the API and the pages:  http://127.0.0.1:8130
"""

import threading

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import ROOT, settings
from .evals import calibrate, run_eval
from .pipeline import Engine

api = FastAPI(title="minirag", version="2.0.0")
_engine: Engine | None = None
_engine_lock = threading.Lock()
_eval = {"running": False, "done": 0, "total": 0, "run_id": None, "error": None}


def engine() -> Engine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = Engine()
        return _engine


def reset_engine() -> None:
    global _engine
    _engine = None


class Turn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    text: str = Field(max_length=2000)


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    history: list[Turn] = Field(default_factory=list, max_length=12)


class FeedbackIn(BaseModel):
    trace_id: str
    helpful: bool
    note: str = Field(default="", max_length=1000)


@api.post("/api/ask")
def ask(body: AskIn):
    try:
        t = engine().answer(body.question, [h.model_dump() for h in body.history])
    except Exception as e:      # index not built, audit log not writable, ...: no log, no answer
        raise HTTPException(503, f"cannot answer: {e}") from e
    return {"trace_id": t["id"], "status": t["outcome"]["status"], "reason": t["outcome"]["reason"],
            "answer": t["outcome"]["answer"], "citations": t["outcome"]["citations"], "ms": t["total_ms"]}


@api.post("/api/feedback", status_code=202)
def feedback(f: FeedbackIn):
    if not engine().store.get_trace(f.trace_id):
        raise HTTPException(404, "unknown trace")
    engine().store.add_feedback(f.trace_id, f.helpful, f.note)
    return {"status": "accepted"}


@api.get("/api/traces")
def traces(kind: str | None = None, limit: int = 50):
    return engine().store.list_traces(kind, min(limit, 500))


@api.get("/api/traces/{trace_id}")
def trace(trace_id: str):
    t = engine().store.get_trace(trace_id)
    if not t:
        raise HTTPException(404, "unknown trace")
    return t


@api.get("/api/overview")
def overview():
    e = engine()
    floor, source = e.floor()
    return {**e.store.overview(), "provider": e.provider.name,
            "models": {"generation": e.provider.gen_model, "embedding": e.provider.embed_model},
            "corpus": {"documents": len(e.index.docs), "chunks": len(e.index.chunks)},
            "score_floor": floor, "score_floor_source": source}


@api.get("/api/corpus")
def corpus():
    e = engine()
    return [{"id": d["id"], "title": d["title"], "version": d.get("version"), "owner": d.get("owner"),
             "chunks": sum(c["doc"] == d["id"] for c in e.index.chunks)} for d in e.index.docs]


@api.get("/api/golden")
def golden():
    return [{"id": c["id"], "type": c["type"], "q": c["q"], "history": c.get("history", [])}
            for c in engine().golden["cases"]]


def _run_eval_job():
    try:
        e = engine()

        def progress(n, total):
            _eval.update(done=n, total=total)

        run = run_eval(e, progress)
        e.store.save_eval_run(run)
        _eval.update(run_id=run["id"])
    except Exception as ex:
        _eval.update(error=str(ex))
    finally:
        _eval.update(running=False)


@api.post("/api/evals/run", status_code=202)
def evals_run():
    if _eval["running"]:
        raise HTTPException(409, "an evaluation is already running")
    _eval.update(running=True, done=0, total=len(engine().golden["cases"]), run_id=None, error=None)
    threading.Thread(target=_run_eval_job, daemon=True).start()
    return _eval


@api.get("/api/evals/status")
def evals_status():
    return _eval


@api.get("/api/evals")
def evals_list():
    return engine().store.list_eval_runs()


@api.get("/api/evals/{run_id}")
def evals_get(run_id: str):
    run = engine().store.get_eval_run(run_id)
    if not run:
        raise HTTPException(404, "unknown run")
    return run


@api.post("/api/calibrate")
def calibrate_floor():
    return calibrate(engine())


@api.get("/healthz")      # liveness: the process runs
def healthz():
    return {"ok": True}


@api.get("/readyz")       # readiness: it can really answer
def readyz(response: Response):
    try:
        e = engine()
        health = e.provider.health()
        out = {"ready": health["ok"], "provider": e.provider.name, "detail": health["detail"],
               "chunks": len(e.index.chunks)}
    except Exception as ex:
        out = {"ready": False, "provider": settings().provider, "detail": str(ex), "chunks": 0}
    if not out["ready"]:
        response.status_code = 503
    return out


WEB = ROOT / "web"


@api.get("/")
def home():
    return FileResponse(WEB / "index.html")


api.mount("/static", StaticFiles(directory=WEB), name="static")
