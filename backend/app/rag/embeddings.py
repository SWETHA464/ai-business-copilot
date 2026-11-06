"""Embedding backends.

* sentence_transformers: real semantic embeddings (optional dependency, see requirements-ml.txt).
* hash: deterministic feature-hashing embeddings. Lexical rather than semantic, but dependency-free, fast and
  good enough for the app to run (and be tested) offline. `EMBEDDING_BACKEND=auto` prefers sentence-transformers
  and falls back to hash with a logged warning.
"""
from __future__ import annotations

import math
import threading
import zlib
from collections import Counter

import numpy as np

from app.config import get_settings
from app.rag.text_utils import tokenize
from app.utils.logging import get_logger

log = get_logger("embeddings")
HASH_DIM = 384


class HashEmbedder:
    name = "hash-384-v1"
    dim = HASH_DIM

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            toks = tokenize(text)
            feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
            for f, c in Counter(feats).items():
                h = zlib.crc32(f.encode("utf-8"))
                sign = 1.0 if (h >> 31) & 1 else -1.0
                out[i, h % self.dim] += sign * (1.0 + math.log(c))
            norm = float(np.linalg.norm(out[i]))
            if norm > 0:
                out[i] /= norm
        return out


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self.name = model_name
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts: list[str]) -> np.ndarray:
        vecs = self._model.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vecs, dtype=np.float32)


_lock = threading.Lock()
_embedder = None


def get_embedder():
    global _embedder
    with _lock:
        if _embedder is not None:
            return _embedder
        s = get_settings()
        backend = s.embedding_backend.lower()
        if backend in ("auto", "sentence_transformers"):
            try:
                _embedder = SentenceTransformerEmbedder(s.embedding_model)
                log.info("embedding backend: sentence-transformers (%s)", s.embedding_model)
                return _embedder
            except Exception as exc:  # ImportError, download failure, ...
                if backend == "sentence_transformers":
                    raise
                log.warning("sentence-transformers unavailable (%s); using hash embeddings", type(exc).__name__)
        _embedder = HashEmbedder()
        return _embedder


def reset_embedder() -> None:
    global _embedder
    with _lock:
        _embedder = None


def to_bytes(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_bytes(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)
