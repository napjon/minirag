import json

import httpx
import pytest
from fastapi.testclient import TestClient

from minirag.evals import calibrate, run_eval
from minirag.llm import OllamaProvider, ProviderError


def test_golden_set_passes_its_gates_on_the_fixture(engine):
    run = run_eval(engine)
    assert run["passed"], run["gates"]
    assert run["counts"] == {"in_scope": 27, "out_of_scope": 8, "total": 35}
    assert run["metrics"]["recall_at_k"] == 1.0 and run["metrics"]["refusal_rate"] == 1.0
    assert set(run["latency_ms"]) >= {"retrieve", "generate", "total"}
    assert len(engine.store.list_traces("eval", 100)) == 35


def test_calibration_separates_in_scope_from_out_of_scope(engine):
    cal = calibrate(engine)
    assert cal["separable"] and cal["out_of_scope_max"] < cal["floor"] < cal["in_scope_min"]
    assert engine.floor() == (cal["floor"], "calibration")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PROVIDER", "fixture")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from minirag import app
    app.reset_engine()
    yield TestClient(app.api)
    app.reset_engine()


def test_api_ask_trace_feedback_overview(client):
    assert client.get("/readyz").json()["ready"] is True
    r = client.post("/api/ask", json={"question": "How many characters long must passwords be?"}).json()
    assert r["status"] == "answered" and "14" in r["answer"]
    trace = client.get(f"/api/traces/{r['trace_id']}").json()
    assert [s["name"] for s in trace["stages"]][:3] == ["retrieve", "rerank", "gate"]
    assert client.post("/api/feedback", json={"trace_id": r["trace_id"], "helpful": True}).status_code == 202
    assert client.post("/api/feedback", json={"trace_id": "nope", "helpful": True}).status_code == 404
    o = client.get("/api/overview").json()
    assert o["queries"] == 1 and o["answered"] == 1 and o["audit"]["ok"] and o["feedback"]["helpful"] == 1
    assert client.post("/api/ask", json={"question": "x"}).status_code == 422
    assert "minirag" in client.get("/").text


def fake_ollama(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content) if request.content else {}
    if request.url.path == "/api/embed":
        return httpx.Response(200, json={"embeddings": [[3.0, 4.0] for _ in body["input"]]})
    if request.url.path == "/api/chat":
        assert body["stream"] is False and body["options"]["temperature"] == 0
        assert body["format"]["properties"]["claims"]["items"]["properties"]["source_id"]["enum"] == ["S1"]
        return httpx.Response(200, json={
            "message": {"content": '{"status":"answered","claims":[]}'},
            "prompt_eval_count": 120, "eval_count": 30, "eval_duration": 1_500_000_000, "load_duration": 2_000_000})
    if request.url.path == "/api/tags":
        return httpx.Response(200, json={"models": [{"name": "qwen2.5:0.5b"}, {"name": "all-minilm:latest"}]})
    return httpx.Response(404)


def test_ollama_provider_speaks_the_native_api(engine):
    p = OllamaProvider(engine.s, transport=httpx.MockTransport(fake_ollama))
    vecs = p.embed(["a", "b"])
    assert vecs.shape == (2, 2) and abs(float(vecs[0] @ vecs[0]) - 1.0) < 1e-6      # normalised
    schema = {"properties": {"claims": {"items": {"properties": {"source_id": {"enum": ["S1"]}}}}}}
    g = p.generate("hi", schema=schema)
    assert (g.prompt_tokens, g.output_tokens, g.tokens_per_s, g.load_ms) == (120, 30, 20.0, 2.0)
    assert p.health() == {"ok": True, "detail": "ready"}


def test_ollama_down_is_a_recorded_error_not_a_crash(engine):
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    engine.provider = OllamaProvider(engine.s, transport=httpx.MockTransport(refuse))
    with pytest.raises(ProviderError):
        engine.provider.embed(["x"])
    t = engine.answer("How often are laptops replaced?")
    assert t["outcome"]["status"] == "error" and "cannot reach Ollama" in t["outcome"]["reason"]
    assert engine.store.verify_chain()["rows"] == 1      # still audited
