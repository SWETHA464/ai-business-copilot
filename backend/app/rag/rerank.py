"""Second-stage reranking: a cross-encoder when available, otherwise a lexical scorer.

Scores are only comparable within one call; they are used for ordering, not as absolute probabilities.
"""
from __future__ import annotations

import math
import threading
from collections import Counter

from app.config import get_settings
from app.rag.text_utils import tokenize
from app.utils.logging import get_logger

log = get_logger("rerank")


class LexicalReranker:
    name = "lexical"

    def score(self, query: str, passages: list[str]) -> list[float]:
        q = list(dict.fromkeys(tokenize(query)))
        if not q or not passages:
            return [0.0] * len(passages)
        docs = [tokenize(p) for p in passages]
        n = len(docs)
        df = {t: sum(1 for d in docs if t in d) for t in q}
        scores = []
        for d in docs:
            tf = Counter(d)
            s = 0.0
            for t in q:
                if tf[t]:
                    idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                    s += idf * (tf[t] * 2.2) / (tf[t] + 1.2 * (0.25 + 0.75 * len(d) / 120))
            text = " ".join(d)
            bigrams = [f"{a} {b}" for a, b in zip(q, q[1:])]
            s += 0.5 * sum(1 for b in bigrams if b in text)
            scores.append(s)
        top = max(scores) or 1.0
        return [x / top for x in scores]


class CrossEncoderReranker:
    def __init__(self, model_name: str):
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(model_name)
        self.name = model_name

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        raw = self._model.predict([(query, p) for p in passages], show_progress_bar=False)
        return [1.0 / (1.0 + math.exp(-float(x))) for x in raw]


_lock = threading.Lock()
_reranker = None


def get_reranker():
    global _reranker
    with _lock:
        if _reranker is not None:
            return _reranker
        s = get_settings()
        backend = s.rerank_backend.lower()
        if backend in ("auto", "cross_encoder"):
            try:
                _reranker = CrossEncoderReranker(s.rerank_model)
                log.info("rerank backend: cross-encoder (%s)", s.rerank_model)
                return _reranker
            except Exception as exc:
                if backend == "cross_encoder":
                    raise
                log.warning("cross-encoder unavailable (%s); using lexical reranker", type(exc).__name__)
        _reranker = LexicalReranker()
        return _reranker


def reset_reranker() -> None:
    global _reranker
    with _lock:
        _reranker = None
