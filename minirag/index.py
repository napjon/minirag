"""Quest Level 1 (embed), Level 4 (hybrid search + RRF) and Level 5 (rerank)."""

import hashlib
import math

import numpy as np
from rank_bm25 import BM25Okapi

from .config import Settings
from .corpus import chunk_docs, load_docs
from .text import terms


def rrf(*ranked_lists: list[int], k: int = 60) -> dict[int, float]:
    """Reciprocal rank fusion: a chunk scores 1/(k+rank) in every list it appears in."""
    score: dict[int, float] = {}
    for lst in ranked_lists:
        for rank, idx in enumerate(lst, start=1):
            score[idx] = score.get(idx, 0.0) + 1.0 / (k + rank)
    return dict(sorted(score.items(), key=lambda kv: -kv[1]))


class Index:
    def __init__(self, s: Settings, provider):
        self.provider = provider
        self.docs = load_docs(s.corpus_dir)
        self.chunks = chunk_docs(self.docs)
        if not self.chunks:
            raise RuntimeError(f"no chunks: is there any .md file in {s.corpus_dir}?")
        tokenized = [terms(c["text"]) for c in self.chunks]
        self.bm25 = BM25Okapi(tokenized)
        self.term_sets = [set(t) for t in tokenized]
        n = len(self.chunks)
        df: dict[str, int] = {}
        for ts in self.term_sets:
            for t in ts:
                df[t] = df.get(t, 0) + 1
        self.idf = {t: math.log(1 + n / d) for t, d in df.items()}
        self.idf_unseen = math.log(1 + n)
        self.vecs, self.cache_hit = self._embed_chunks(s)

    def _embed_chunks(self, s: Settings) -> tuple[np.ndarray, bool]:
        """Vectors are cached on disk, keyed by the embedding model and the exact chunk texts.
        Change a document or the model and the key changes, so stale vectors can never be used."""
        key = hashlib.sha256(
            "\x00".join([self.provider.embed_model] + [c["text"] for c in self.chunks]).encode()
        ).hexdigest()[:16]
        path = s.data_dir / f"vectors-{key}.npy"
        if path.exists():
            return np.load(path), True
        vecs = self.provider.embed([c["text"] for c in self.chunks])
        s.data_dir.mkdir(parents=True, exist_ok=True)
        np.save(path, vecs)
        return vecs, False

    def keyword_search(self, q: str, k: int) -> list[tuple[int, float]]:
        scores = self.bm25.get_scores(terms(q))
        return [(int(i), float(scores[i])) for i in np.argsort(-scores)[:k] if scores[i] > 0]

    def vector_search(self, qv: np.ndarray, k: int) -> list[tuple[int, float]]:
        sims = self.vecs @ qv
        return [(int(i), float(sims[i])) for i in np.argsort(-sims)[:k]]

    def coverage(self, q: str, idx: int) -> float:
        """Share of the question's content words (weighted by rarity) that the chunk contains."""
        q_terms = set(terms(q))
        if not q_terms:
            return 0.0
        weight = {t: self.idf.get(t, self.idf_unseen) for t in q_terms}
        return sum(w for t, w in weight.items() if t in self.term_sets[idx]) / sum(weight.values())

    def rerank(self, q: str, qv: np.ndarray, ids: list[int]) -> list[float]:
        """A light reranker: half meaning (cosine), half exact wording (coverage), both in 0..1.
        Level 5 uses a cross-encoder; that needs a 2 GB download, so local dev starts with this."""
        return [0.5 * max(float(self.vecs[i] @ qv), 0.0) + 0.5 * self.coverage(q, i) for i in ids]
