import json
import sqlite3

from minirag.corpus import chunk_docs, load_docs
from minirag.grounding import check_claim
from minirag.index import rrf
from minirag.text import numbers


def test_chunks_stay_inside_one_section(engine):
    chunks = engine.index.chunks
    assert len({c["id"] for c in chunks}) == len(chunks)
    for c in chunks:
        assert c["text"].startswith(f"[{c['title']} > {c['section']}]")
        assert len(c["text"]) < 1000


def test_long_section_is_split(tmp_path):
    (tmp_path / "x.md").write_text("---\nid: x\ntitle: X\n---\n# X\n## Only\n" + "\n".join(["word " * 30] * 12))
    chunks = chunk_docs(load_docs(tmp_path))
    assert len(chunks) > 1 and {c["section"] for c in chunks} == {"Only"}


def test_golden_evidence_exists_in_corpus(engine):
    corpus = {d["id"]: d["body"] for d in engine.index.docs}
    for case in engine.golden["cases"]:
        if case["type"] == "out_of_scope":
            continue
        assert case["evidence"] in corpus[case["docs"][0]], case["id"]
        assert case["must"] in case["evidence"], case["id"]


def test_rrf_rewards_agreement():
    fused = rrf([1, 2, 3], [3, 1, 9])
    assert list(fused)[0] == 1 and fused[1] > fused[2] > fused[9]


def test_numbers_normalise_thousands():
    assert numbers("USD 5,000 and 0.45 at 10:00") == {"5000", "0.45", "10", "00"}


def test_ground_check_drops_wrong_number_and_unsupported_text():
    src = "The hotel limit is USD 180 per night."
    assert check_claim("The hotel limit is USD 180 per night.", src, 0.5)["kept"]
    wrong = check_claim("The hotel limit is USD 250 per night.", src, 0.5)
    assert not wrong["kept"] and wrong["reason"] == "number_not_in_source" and wrong["bad_numbers"] == ["250"]
    assert check_claim("Employees get free parking downtown.", src, 0.5)["reason"] == "low_support"
    assert check_claim("anything", None, 0.5)["reason"] == "unknown_source"


def test_answer_is_grounded_cited_and_traced(engine):
    t = engine.answer("What is the cash drawer limit for a teller?")
    assert t["outcome"]["status"] == "answered" and "5,000" in t["outcome"]["answer"]
    assert t["outcome"]["citations"][0]["doc"] == "ops-01"
    assert t["trajectory"] == ["retrieve", "rerank", "gate", "generate", "ground", "answer", "score"]
    assert t["golden"]["passed"] and t["golden"]["retrieved_rank"] == 1
    assert t["scores"]["groundedness"] == 1.0
    assert sum(c["selected"] for c in t["candidates"]) == engine.s.top_k
    assert engine.store.get_trace(t["id"])["question"] == t["question"]


def test_out_of_scope_is_refused_before_the_model_runs(engine):
    t = engine.answer("Give me a recipe for fried rice with chicken.")
    assert t["outcome"]["status"] == "refused" and t["outcome"]["reason"] == "below_score_floor"
    assert t["generation"] is None and t["trajectory"][-1] == "refuse"


def test_follow_up_is_rewritten(engine):
    history = [{"role": "user", "text": "What is the meal limit per day for international travel?"},
               {"role": "assistant", "text": "USD 85."}]
    t = engine.answer("And for domestic travel?", history)
    assert t["trajectory"][0] == "rewrite" and len(t["queries"]) == 2
    assert "60" in t["outcome"]["answer"]


class LyingProvider:
    """Wraps the fixture but makes the model invent a number."""

    def __init__(self, inner):
        self.inner, self.name = inner, inner.name
        self.gen_model, self.embed_model = inner.gen_model, inner.embed_model
        self.embed = inner.embed

    def generate(self, prompt, schema=None, max_tokens=300):
        g = self.inner.generate(prompt, schema, max_tokens)
        g.text = json.dumps({"status": "answered", "claims": [
            {"text": "The hotel limit is USD 999 per night.", "source_id": "S1"}]})
        return g


def test_hallucinated_number_never_reaches_the_user(engine):
    engine.provider = LyingProvider(engine.provider)
    t = engine.answer("What is the hotel limit per night?")
    assert t["outcome"]["status"] == "refused" and t["outcome"]["reason"] == "no_grounded_claims"
    assert "999" not in t["outcome"]["answer"] and t["scores"]["groundedness"] == 0.0


def test_audit_chain_detects_tampering(engine):
    engine.answer("How often are laptops replaced?")
    engine.answer("How long is the probation period for new employees?")
    assert engine.store.verify_chain() == {"ok": True, "rows": 2, "broken_at": None}
    db = sqlite3.connect(engine.store.path)
    db.execute("UPDATE audit SET answer='edited' WHERE id=1")
    db.commit()
    assert engine.store.verify_chain()["ok"] is False


def test_vectors_are_cached_and_keyed_by_content(engine, tmp_path):
    from minirag.index import Index
    assert engine.index.cache_hit is False
    assert Index(engine.s, engine.provider).cache_hit is True
