from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Protocol

from backend.config import Settings, get_settings
from backend.domain.enums import DeploymentProfile, ModelProvider


@dataclass
class Generation:
    text: str
    structured: dict[str, Any] | None
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class ModelGateway(Protocol):
    provider: str
    generation_model: str

    async def generate(self, prompt: str, *, json_schema: dict | None = None) -> Generation: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    async def rerank(self, query: str, passages: list[str]) -> list[float]: ...
    async def vision_check(self, image_note: str, listing_text: str) -> dict[str, Any]: ...


def fixture_embedding(text: str, dim: int = 1024) -> list[float]:
    vec = [0.0] * dim
    tokens = [t for t in text.lower().replace("\n", " ").split(" ") if t]
    if not tokens:
        tokens = ["empty"]
    for token in tokens:
        digest = hashlib.sha256(token.encode()).digest()
        for i in range(0, min(len(digest), 32)):
            idx = (digest[i] * 13 + i * 7 + len(token)) % dim
            vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


INVENTED_EVIDENCE_ID = "invented-id-not-in-evidence"


class FixtureGateway:
    provider = "fixture"
    generation_model = "fixture-1"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def generate(self, prompt: str, *, json_schema: dict | None = None) -> Generation:
        structured = None
        text = "Insufficient evidence from authorized sources."
        if "INTENT_JSON" in prompt:
            structured = _intent_from_prompt(prompt)
            text = json.dumps(structured)
        elif "QA_JSON" in prompt:
            structured = _qa_from_prompt(prompt)
            text = json.dumps(structured)
        elif "DRAFT_JSON" in prompt:
            structured = _draft_from_prompt(prompt)
            text = json.dumps(structured)
        elif "VERIFY_JSON" in prompt:
            structured = {"supported": True, "unsupported_claims": []}
            text = json.dumps(structured)
        return Generation(
            text=text,
            structured=structured,
            model=self.generation_model,
            input_tokens=max(1, len(prompt) // 4),
            output_tokens=max(1, len(text) // 4),
            cost_usd=0.0,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [fixture_embedding(t, self.settings.embedding_dim) for t in texts]

    async def rerank(self, query: str, passages: list[str]) -> list[float]:
        stop = {
            "the",
            "a",
            "an",
            "of",
            "and",
            "or",
            "to",
            "for",
            "in",
            "on",
            "is",
            "are",
            "what",
            "who",
            "may",
            "can",
            "dengan",
            "dan",
            "yang",
            "untuk",
        }
        q = {t for t in query.lower().split() if t not in stop and len(t) > 2}
        scores = []
        for passage in passages:
            p = {t for t in passage.lower().split() if t not in stop and len(t) > 2}
            scores.append(len(q & p) / max(1, len(q)))
        return scores

    async def vision_check(self, image_note: str, listing_text: str) -> dict[str, Any]:
        consistent = image_note.lower() in listing_text.lower() or "placeholder" in image_note
        return {
            "consistent": consistent,
            "observations": [image_note],
            "unsupported_visual_claims": []
            if consistent
            else ["image does not match listing type"],
        }


def _intent_from_prompt(prompt: str) -> dict[str, Any]:
    lowered = prompt.lower()
    if "spend" in lowered or "belanja" in lowered:
        pattern = "spending_by_period"
    elif "order" in lowered or "pesanan" in lowered:
        pattern = "order_counts_by_status"
    elif "supplier" in lowered or "pemasok" in lowered:
        pattern = "supplier_concentration"
    elif "price variation" in lowered or "harga" in lowered:
        pattern = "price_variation"
    elif "additional" in lowered or "layanan tambahan" in lowered:
        pattern = "additional_service_charges"
    else:
        pattern = "sourcing_outcomes"
    return {
        "pattern": pattern,
        "filters": {"start_date": "2030-01-01", "end_date": "2030-12-31"},
        "group_by": ["month"],
        "presentation": "bar",
    }


_QA_STOP = {
    "the",
    "a",
    "an",
    "of",
    "and",
    "or",
    "to",
    "in",
    "on",
    "for",
    "is",
    "are",
    "who",
    "what",
    "when",
    "how",
    "may",
    "please",
    "with",
    "from",
    "this",
    "that",
    "all",
    "any",
    "not",
    "can",
    "was",
    "will",
    "yang",
    "dan",
    "untuk",
    "dari",
    "pada",
    "dengan",
    "apa",
    "siapa",
    "boleh",
    "json",
    "question",
    "evidence",
}


def _tokens(text: str) -> set[str]:
    cleaned = {token.strip("?.,:;\"'") for token in text.lower().split()}
    return {token for token in cleaned if len(token) > 2 and token not in _QA_STOP}


def _qa_from_prompt(prompt: str) -> dict[str, Any]:
    evidence_rows: list[tuple[str, str]] = []
    if "EVIDENCE:" in prompt:
        lines = prompt.split("EVIDENCE:", 1)[1].splitlines()
        index = 0
        while index < len(lines):
            line = lines[index]
            if line.strip().startswith("- ") and "span=" in line:
                rest = line.strip()[2:]
                eid = rest.split(" ", 1)[0]
                span = rest.split("span=", 1)[1]
                index += 1
                while index < len(lines) and not lines[index].strip().startswith("- "):
                    span += "\n" + lines[index]
                    index += 1
                evidence_rows.append((eid, span))
                continue
            index += 1
    if not evidence_rows:
        return {
            "status": "insufficient_evidence",
            "answer": None,
            "claims": [],
            "limitations": "No authorized evidence was selected.",
        }
    question = prompt
    if "QUESTION:" in prompt:
        question = prompt.split("QUESTION:", 1)[1]
        if "EVIDENCE:" in question:
            question = question.split("EVIDENCE:", 1)[0]
    q_tokens = _tokens(question)
    best_id, snippet, best_score = evidence_rows[0][0], evidence_rows[0][1][:240], 0
    for eid, span in evidence_rows:
        score = len(q_tokens & _tokens(span))
        if score > best_score:
            best_id, snippet, best_score = eid, span[:240], score
    if best_score == 0:
        return {
            "status": "insufficient_evidence",
            "answer": None,
            "claims": [],
            "limitations": "No authorized evidence was selected.",
        }
    answer = snippet or "The authorized procedure is described in the cited section."
    return {
        "status": "answered",
        "answer": answer,
        "claims": [
            {"text": answer, "evidence_id": best_id},
            {
                "text": "This claim is not supported by retrieved evidence.",
                "evidence_id": INVENTED_EVIDENCE_ID,
            },
        ],
        "limitations": None,
    }


def _draft_from_prompt(prompt: str) -> dict[str, Any]:
    evidence_ids = []
    snippets = []
    if '"evidence"' in prompt or "evidence_id" in prompt:
        try:
            blob = prompt.split("DRAFT_JSON", 1)[1]
            payload = json.loads(blob)
            for item in payload.get("evidence") or []:
                eid = str(item.get("evidence_id") or item.get("chunk_id") or "")
                text = str(item.get("text") or "")
                if eid:
                    evidence_ids.append(eid)
                if text:
                    snippets.append(text[:240])
        except Exception:
            evidence_ids = []
    body = (
        snippets[0]
        if snippets
        else "Prepare a reviewed specification from the supplied brief and current policy."
    )
    return {
        "sections": [
            {"heading": "Purpose", "body": body, "evidence_ids": evidence_ids[:1]},
            {
                "heading": "Requirements",
                "body": "Mandatory fields from the brief are copied without invention.",
                "evidence_ids": evidence_ids[:1],
            },
            {
                "heading": "Acceptance",
                "body": "Acceptance conditions remain placeholders when unknown.",
                "evidence_ids": [],
            },
        ],
        "unresolved_assumptions": ["Unknown mandatory values were left as placeholders."],
    }


class OpenAICompatGateway:
    def __init__(
        self, settings: Settings, *, base_url: str, api_key: str, model: str, provider: str
    ):
        from openai import AsyncOpenAI

        self.settings = settings
        self.provider = provider
        self.generation_model = model
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    async def generate(self, prompt: str, *, json_schema: dict | None = None) -> Generation:
        kwargs: dict[str, Any] = {
            "model": self.generation_model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if json_schema is not None:
            kwargs["response_format"] = {"type": "json_object"}
        # Chat Completions is the common denominator supported by hosted
        # OpenAI-compatible services and local vLLM deployments.
        resp = await self.client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content or ""
        structured = None
        if json_schema is not None:
            try:
                structured = json.loads(text)
            except json.JSONDecodeError:
                structured = None
        usage = getattr(resp, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        cost_usd = 0.0
        if self.provider == "hosted":
            cost_usd = (
                input_tokens * self.settings.hosted_input_cost_per_million
                + output_tokens * self.settings.hosted_output_cost_per_million
            ) / 1_000_000
        return Generation(
            text=text,
            structured=structured,
            model=self.generation_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [fixture_embedding(t, self.settings.embedding_dim) for t in texts]

    async def rerank(self, query: str, passages: list[str]) -> list[float]:
        return await FixtureGateway(self.settings).rerank(query, passages)

    async def vision_check(self, image_note: str, listing_text: str) -> dict[str, Any]:
        gen = await self.generate(
            f"VISION_JSON Compare image note {image_note!r} with listing {listing_text!r}. "
            "Return JSON with consistent, observations, unsupported_visual_claims.",
            json_schema={"type": "object"},
        )
        return gen.structured or {
            "consistent": False,
            "observations": [],
            "unsupported_visual_claims": ["unparsed"],
        }


def get_gateway(settings: Settings | None = None) -> ModelGateway:
    settings = settings or get_settings()
    if settings.deployment_profile == DeploymentProfile.PRIVATE and settings.private_egress_blocked:
        if settings.model_provider == ModelProvider.HOSTED:
            raise RuntimeError("hosted provider is forbidden in the private profile")
    if settings.model_provider == ModelProvider.FIXTURE:
        return FixtureGateway(settings)
    key = None
    if settings.model_provider == ModelProvider.HOSTED:
        if settings.hosted_model_api_key is None:
            raise RuntimeError("HOSTED_MODEL_API_KEY is required")
        key = settings.hosted_model_api_key.get_secret_value()
        return OpenAICompatGateway(
            settings,
            base_url=settings.hosted_model_base_url,
            api_key=key,
            model=settings.hosted_generation_model,
            provider="hosted",
        )
    return OpenAICompatGateway(
        settings,
        base_url=settings.private_model_base_url,
        api_key="not-needed",
        model=settings.private_generation_model,
        provider="private",
    )
