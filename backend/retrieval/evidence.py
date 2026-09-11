from __future__ import annotations

import re

_WORD = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_NUMBER = re.compile(r"\b\d+(?:\.\d+)?%?\b")
_NEGATION = {
    "no",
    "not",
    "never",
    "without",
    "cannot",
    "can't",
    "neither",
    "nor",
    "tidak",
    "bukan",
    "tanpa",
    "belum",
}


def content_tokens(text: str) -> list[str]:
    return [
        match.group(0).lower() for match in _WORD.finditer(text or "") if len(match.group(0)) > 3
    ]


def _numbers(text: str) -> set[str]:
    return {match.group(0).lower() for match in _NUMBER.finditer(text or "")}


def _has_negation(text: str) -> bool:
    return any(token in _NEGATION for token in re.findall(r"[a-z']+", text.lower()))


def claim_is_supported(claim_text: str, span: str, *, min_overlap: float = 0.6) -> bool:
    if _has_negation(claim_text) != _has_negation(span):
        return False
    claim_numbers = _numbers(claim_text)
    if claim_numbers and not claim_numbers.issubset(_numbers(span)):
        return False
    tokens = content_tokens(claim_text)
    if not tokens:
        return False
    span_set = set(content_tokens(span))
    if not span_set:
        return False
    overlap = sum(1 for token in tokens if token in span_set)
    return (overlap / len(tokens)) >= min_overlap


def answer_is_supported(answer: str, claims: list[dict], spans: dict[str, str]) -> bool:
    """Require the returned prose to be covered by its cited claim evidence."""

    if not isinstance(answer, str) or not answer.strip() or not claims:
        return False
    cited_spans = [spans.get(str(claim.get("evidence_id")), "") for claim in claims]
    cited_spans = [span for span in cited_spans if span]
    if not cited_spans:
        return False
    claim_text = " ".join(str(claim.get("text") or "") for claim in claims)
    if not claim_is_supported(answer, " ".join(cited_spans), min_overlap=0.6):
        return False
    return claim_is_supported(claim_text, " ".join(cited_spans), min_overlap=0.6)


def supporting_span(text: str, query: str, width: int = 280) -> str:
    if not text:
        return ""
    collapsed = " ".join(text.split())
    if len(collapsed) <= width:
        return collapsed
    haystack = collapsed.lower()
    needles = content_tokens(query) or [token.lower() for token in query.split() if token]
    index = -1
    for needle in needles:
        found = haystack.find(needle)
        if found >= 0:
            index = found
            break
    if index < 0:
        return collapsed[:width]
    start = max(0, index - width // 4)
    return collapsed[start : start + width]
