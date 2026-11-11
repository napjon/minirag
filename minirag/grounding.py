"""Quest Level 6: keep a claim only if its cited source really supports it."""

from .text import numbers, terms


def check_claim(text: str, source_text: str | None, support_floor: float) -> dict:
    """Two checks that need no model:
    numbers  every number in the claim must appear in the cited source
    support  enough of the claim's content words must appear in the cited source
    """
    if source_text is None:
        return {"kept": False, "reason": "unknown_source", "numbers_ok": False, "support": 0.0, "bad_numbers": []}
    bad = sorted(numbers(text) - numbers(source_text))
    claim_terms = set(terms(text))
    support = len(claim_terms & set(terms(source_text))) / len(claim_terms) if claim_terms else 0.0
    if bad:
        reason = "number_not_in_source"
    elif support < support_floor:
        reason = "low_support"
    else:
        reason = "supported"
    return {"kept": reason == "supported", "reason": reason, "numbers_ok": not bad,
            "support": round(support, 3), "bad_numbers": bad}
