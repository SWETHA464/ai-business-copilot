"""LLM provider abstraction: local Ollama, any OpenAI-compatible hosted API, or disabled.

The rest of the app only calls `get_llm().generate(...)` and must handle `LLMUnavailable`
(every feature has a deterministic fallback so the app still works without a model).
Prompts/responses are never logged; only provider, model, latency and token counts.
"""
from __future__ import annotations

import json
import threading
import time

import httpx

from app.config import Settings, get_settings
from app.utils.logging import get_logger

log = get_logger("llm")


class LLMUnavailable(Exception):
    """Raised when the configured LLM cannot be used (disabled, unreachable, error response)."""


def extract_json(text: str) -> dict | None:
    """Pull the first balanced JSON object out of model output (handles ```json fences)."""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        return obj if isinstance(obj, dict) else None
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


class LLMClient:
    def __init__(self, settings: Settings | None = None):
        self.s = settings or get_settings()
        self._health: tuple[float, dict] | None = None
        self.last_usage: dict = {}

    @property
    def provider(self) -> str:
        return (self.s.llm_provider or "none").lower()

    @property
    def model(self) -> str:
        return self.s.llm_model

    def configured(self) -> bool:
        if self.provider == "ollama":
            return bool(self.s.ollama_base_url)
        if self.provider == "openai_compatible":
            return bool(self.s.llm_api_key and self.s.llm_base_url)
        return False

    # ------------------------------------------------------------------ generation
    def generate(self, system: str, prompt: str, *, temperature: float = 0.1,
                 json_mode: bool = False, max_tokens: int = 1024) -> str:
        if not self.configured():
            raise LLMUnavailable("No LLM is configured (LLM_PROVIDER=none or missing settings).")
        start = time.perf_counter()
        try:
            if self.provider == "ollama":
                text, usage = self._ollama(system, prompt, temperature, json_mode, max_tokens)
            else:
                text, usage = self._openai(system, prompt, temperature, json_mode, max_tokens)
        except (httpx.HTTPError, KeyError, ValueError, IndexError) as exc:
            log.warning("llm call failed provider=%s model=%s error=%s", self.provider, self.model,
                        type(exc).__name__)
            raise LLMUnavailable(f"The language model is not reachable ({type(exc).__name__}).") from exc
        self.last_usage = usage
        log.info("llm call provider=%s model=%s ms=%.0f tokens=%s", self.provider, self.model,
                 (time.perf_counter() - start) * 1000, usage)
        return text

    def _ollama(self, system, prompt, temperature, json_mode, max_tokens):
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_mode:
            body["format"] = "json"
        r = httpx.post(f"{self.s.ollama_base_url.rstrip('/')}/api/chat", json=body,
                       timeout=self.s.llm_timeout_seconds)
        r.raise_for_status()
        data = r.json()
        return data["message"]["content"], {
            "prompt_tokens": data.get("prompt_eval_count"), "completion_tokens": data.get("eval_count")}

    def _openai(self, system, prompt, temperature, json_mode, max_tokens):
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "temperature": temperature, "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        r = httpx.post(f"{self.s.llm_base_url.rstrip('/')}/chat/completions", json=body,
                       headers={"Authorization": f"Bearer {self.s.llm_api_key}"},
                       timeout=self.s.llm_timeout_seconds)
        r.raise_for_status()
        data = r.json()
        u = data.get("usage") or {}
        return data["choices"][0]["message"]["content"], {
            "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens")}

    # ------------------------------------------------------------------ health
    def health(self, force: bool = False) -> dict:
        now = time.monotonic()
        if not force and self._health and now - self._health[0] < 30:
            return self._health[1]
        info = {"provider": self.provider, "model": self.model, "configured": self.configured(),
                "reachable": False, "detail": ""}
        if not info["configured"]:
            info["detail"] = ("LLM disabled or not configured. Set LLM_PROVIDER=ollama and run "
                              "`ollama pull " + self.model + "`." if self.provider != "openai_compatible"
                              else "Set LLM_API_KEY and LLM_BASE_URL.")
        elif self.provider == "ollama":
            try:
                r = httpx.get(f"{self.s.ollama_base_url.rstrip('/')}/api/tags", timeout=3)
                r.raise_for_status()
                names = [m.get("name", "") for m in r.json().get("models", [])]
                have = any(n == self.model or n.split(":")[0] == self.model.split(":")[0] for n in names)
                info["reachable"] = have
                info["detail"] = "ok" if have else f"Ollama is running but model '{self.model}' is not pulled."
            except (httpx.HTTPError, ValueError):
                info["detail"] = f"Cannot reach Ollama at {self.s.ollama_base_url}. Is it running?"
        else:
            info["reachable"] = True  # cannot probe hosted APIs without spending tokens
            info["detail"] = "configured (not probed)"
        self._health = (now, info)
        return info


_lock = threading.Lock()
_llm: LLMClient | None = None


def get_llm() -> LLMClient:
    global _llm
    with _lock:
        if _llm is None:
            _llm = LLMClient()
        return _llm


def reset_llm() -> None:
    global _llm
    with _lock:
        _llm = None
