"""External research agent (Tavily). Optional: without TAVILY_API_KEY it reports a setup message and never fabricates results.

Web content is untrusted: instruction-like lines are neutralised and snippets are length-limited before they reach any prompt.
"""
from __future__ import annotations

import httpx

from app.config import get_settings
from app.security.prompt_guard import neutralize
from app.utils.logging import get_logger

log = get_logger("research")
TAVILY_URL = "https://api.tavily.com/search"
SETUP_MESSAGE = ("External research is not configured. Create a free key at https://tavily.com and set "
                 "TAVILY_API_KEY in your .env file, then restart the backend.")


class ResearchAgent:
    def __init__(self, api_key: str | None = None, client: httpx.Client | None = None):
        self.api_key = get_settings().tavily_api_key if api_key is None else api_key
        self.client = client

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str, max_results: int = 5) -> dict:
        base = {"status": "ok", "query": query[:300], "results": [], "message": ""}
        if not self.configured:
            return {**base, "status": "not_configured", "message": SETUP_MESSAGE}
        try:
            client = self.client or httpx.Client(timeout=20)
            r = client.post(TAVILY_URL, json={"query": query[:400], "max_results": max_results,
                                              "search_depth": "basic", "include_answer": False},
                            headers={"Authorization": f"Bearer {self.api_key}"})
            r.raise_for_status()
            raw = r.json().get("results", [])
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("external search failed: %s", type(exc).__name__)
            return {**base, "status": "error", "message":
                    "The external search service could not be reached, so no web sources are included."}
        results = []
        for item in raw[:max_results]:
            url = str(item.get("url", ""))
            if not url.startswith(("http://", "https://")):
                continue
            content, removed = neutralize(str(item.get("content", ""))[:700])
            results.append({"title": str(item.get("title", url))[:200], "url": url, "snippet": content,
                            "flagged": removed > 0})
        if not results:
            return {**base, "status": "no_results", "message": "The web search returned no usable results."}
        return {**base, "results": results}
