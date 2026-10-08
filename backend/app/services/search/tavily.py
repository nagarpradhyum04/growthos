"""Tavily web search (https://tavily.com). Enabled with SEARCH_PROVIDER=tavily + SEARCH_API_KEY."""
import httpx

from app.services.search.base import EvidenceDoc, SearchError, SearchProvider


class TavilySearchProvider(SearchProvider):
    name = "tavily"
    URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str, timeout_seconds: float = 15.0):
        if not api_key:
            raise SearchError("SEARCH_API_KEY is not set")
        self._api_key = api_key
        self._timeout = timeout_seconds

    def search(self, query: str, max_results: int = 5) -> list[EvidenceDoc]:
        try:
            response = httpx.post(
                self.URL,
                json={"api_key": self._api_key, "query": query, "max_results": max_results},
                timeout=self._timeout,
            )
            response.raise_for_status()
            results = response.json().get("results", [])
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchError(f"Search failed: {type(exc).__name__}") from exc
        return [
            EvidenceDoc(url=r["url"], title=r.get("title", ""), text=(r.get("content") or "")[:3000], source_type="search")
            for r in results
            if r.get("url") and r.get("content")
        ]
