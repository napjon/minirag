"""Model providers behind one interface (Quest Level 13: one interface, two providers).

ollama   real local models through Ollama's native API, which also reports
         token counts and timings that the monitor shows.
fixture  deterministic stand-ins, so tests and CI run with no model at all.
There is no silent fallback: the provider is whatever PROVIDER says.
"""

import hashlib
import json
import re
import time
from dataclasses import dataclass

import httpx
import numpy as np

from .config import Settings
from .text import terms, tokenize


@dataclass
class Generation:
    text: str
    model: str
    prompt_tokens: int = 0
    output_tokens: int = 0
    gen_ms: float = 0.0      # time spent producing tokens
    load_ms: float = 0.0     # time spent loading the model into memory (first call)

    @property
    def tokens_per_s(self) -> float:
        return round(self.output_tokens / (self.gen_ms / 1000), 1) if self.gen_ms else 0.0


class ProviderError(RuntimeError):
    pass


def _normalize(v: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.where(norm == 0, 1, norm)


class OllamaProvider:
    name = "ollama"

    def __init__(self, s: Settings, transport: httpx.BaseTransport | None = None):
        self.gen_model, self.embed_model = s.gen_model, s.embed_model
        self.http = httpx.Client(base_url=s.ollama_url, timeout=s.budget_s, transport=transport)

    def _post(self, path: str, body: dict) -> dict:
        try:
            r = self.http.post(path, json=body)
            r.raise_for_status()
            return r.json()
        except httpx.TimeoutException as e:
            raise ProviderError(f"timeout calling Ollama {path}") from e
        except httpx.HTTPStatusError as e:
            raise ProviderError(f"Ollama {path} returned {e.response.status_code}: {e.response.text[:200]}") from e
        except httpx.HTTPError as e:
            raise ProviderError(f"cannot reach Ollama at {self.http.base_url} ({e}). Is `ollama serve` running?") from e

    def embed(self, texts: list[str]) -> np.ndarray:
        out = []
        for i in range(0, len(texts), 32):
            data = self._post("/api/embed", {"model": self.embed_model, "input": texts[i:i + 32]})
            out.extend(data["embeddings"])
        return _normalize(np.asarray(out, dtype=np.float32))

    def generate(self, prompt: str, schema: dict | None = None, max_tokens: int = 300) -> Generation:
        body = {
            "model": self.gen_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0, "num_predict": max_tokens, "num_ctx": 4096},
        }
        if schema:
            body["format"] = schema      # structured output: the reply must match this JSON schema
        d = self._post("/api/chat", body)
        return Generation(
            text=d.get("message", {}).get("content", ""),
            model=self.gen_model,
            prompt_tokens=d.get("prompt_eval_count", 0),
            output_tokens=d.get("eval_count", 0),
            gen_ms=d.get("eval_duration", 0) / 1e6,
            load_ms=d.get("load_duration", 0) / 1e6,
        )

    def health(self) -> dict:
        try:
            r = self.http.get("/api/tags", timeout=3)
            r.raise_for_status()
            have = {m["name"] for m in r.json().get("models", [])}
        except httpx.HTTPError as e:
            return {"ok": False, "detail": f"Ollama not reachable: {e}"}

        def present(model: str) -> bool:
            return model in have or f"{model}:latest" in have

        missing = [m for m in (self.gen_model, self.embed_model) if not present(m)]
        return {"ok": not missing, "detail": f"missing models: {missing}" if missing else "ready"}


class FixtureProvider:
    """No model. Embeddings are hashed bags of words; generation quotes the best-matching source line."""

    name = "fixture"
    DIM = 512

    def __init__(self, s: Settings):
        self.gen_model, self.embed_model = "fixture-extractive", "fixture-hash-512"

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.DIM), dtype=np.float32)
        for row, text in enumerate(texts):
            for term in terms(text):
                h = int.from_bytes(hashlib.md5(term.encode()).digest()[:4], "little")
                out[row, h % self.DIM] += 1.0
        return _normalize(out)

    def generate(self, prompt: str, schema: dict | None = None, max_tokens: int = 300) -> Generation:
        t0 = time.perf_counter()
        text = self._ground(prompt) if schema else self._rewrite(prompt)
        ms = max((time.perf_counter() - t0) * 1000, 0.01)
        return Generation(text, self.gen_model, len(tokenize(prompt)), len(tokenize(text)), gen_ms=ms)

    @staticmethod
    def _ground(prompt: str) -> str:
        question = prompt.rsplit("QUESTION:", 1)[-1]
        q = set(terms(question))
        sources = re.findall(r"^\[(S\d+)\] (.*?)(?=^\[S\d+\] |^QUESTION:)", prompt, flags=re.S | re.M)
        best, best_score = None, 0.0
        for sid, body in sources:
            for line in body.strip().splitlines()[1:]:      # skip the "[title > section]" line
                found = q & set(terms(line))
                score = len(found) / max(len(q), 1)
                if score > best_score:
                    best, best_score = {"text": line.strip(), "source_id": sid}, score
        if best is None or best_score < 0.5:
            return json.dumps({"status": "not_in_sources", "claims": []})
        return json.dumps({"status": "answered", "claims": [best]})

    @staticmethod
    def _rewrite(prompt: str) -> str:
        history = re.findall(r"^user: (.*)$", prompt, flags=re.M)
        last = prompt.rsplit("LAST:", 1)[-1].strip()
        return f"{history[-1]} {last}" if history else last

    def health(self) -> dict:
        return {"ok": True, "detail": "fixture provider (no model)"}


def get_provider(s: Settings):
    if s.provider == "ollama":
        return OllamaProvider(s)
    if s.provider == "fixture":
        return FixtureProvider(s)
    raise ValueError(f"PROVIDER must be 'ollama' or 'fixture', got {s.provider!r}")
