"""Tokenisation helpers shared by BM25, the lexical embedder/reranker and evidence checks."""
from __future__ import annotations

import re

STOPWORDS = frozenset("""
a an and are as at be been but by can could did do does for from had has have how i if in into is it its
me my of on or our please should so than that the their them then there these they this those to us was we
were what when where which who whom why will with would you your tell show give about any all also not no
""".split())

_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*")


def stem(tok: str) -> str:
    """Very light suffix stripping so 'refunds'/'refunded'/'refunding' match."""
    for suf in ("ing", "ed", "es", "s"):
        if len(tok) > len(suf) + 3 and tok.endswith(suf):
            return tok[: -len(suf)]
    return tok


def tokenize(text: str, *, drop_stop: bool = True) -> list[str]:
    toks = [t.lower() for t in _TOKEN.findall(text)]
    if drop_stop:
        toks = [t for t in toks if t not in STOPWORDS]
    return [stem(t) for t in toks]


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if p and p.strip()]
