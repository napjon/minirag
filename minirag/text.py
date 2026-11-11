"""Tokenizing shared by keyword search, the reranker and the ground check."""

import re

STOP = set(
    "a an and are as at be been by can do does for from has have how i if in is it its may me must my of on "
    "or our per that the their there this to was what when where which who will with you your much many "
    "long often should would could about into than then they we us am not no any each every all get".split()
)


def tokenize(s: str) -> list[str]:
    """Keeps tokens such as "hr-01", "p95" and "0.45"; drops punctuation stuck to the edges."""
    return [t.strip(".-") for t in re.findall(r"[\w@%.-]+", s.lower()) if t.strip(".-")]


def stem(token: str) -> str:
    """Deliberately tiny: "days" and "day" should match, nothing cleverer."""
    for suffix in ("ies", "es", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3 and not token[-len(suffix) - 1].isdigit():
            return token[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return token


def terms(s: str) -> list[str]:
    """Content words: tokenized, stop words removed, stemmed."""
    return [stem(t) for t in tokenize(s) if t not in STOP]


def numbers(s: str) -> set[str]:
    """Every number in the text, with thousands separators removed ("5,000" -> "5000")."""
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", s)}
