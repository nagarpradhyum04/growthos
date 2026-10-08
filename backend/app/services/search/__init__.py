"""Research tool wiring."""
import logging

from app.config import Settings
from app.services.search.base import EvidenceBundle, EvidenceDoc, SearchError, SearchProvider
from app.services.search.website import WebsiteFetcher

logger = logging.getLogger(__name__)


class ResearchTools:
    """Collects evidence for a lead. Individual tool failures are recorded, not fatal."""

    def __init__(self, website_fetcher: WebsiteFetcher | None, search_provider: SearchProvider | None):
        self.website_fetcher = website_fetcher
        self.search_provider = search_provider

    def gather(self, company_name: str, website: str) -> EvidenceBundle:
        bundle = EvidenceBundle()
        if website and self.website_fetcher:
            try:
                bundle.documents += self.website_fetcher.fetch_site(website)
            except SearchError as exc:
                logger.info("Website fetch failed: %s", exc)
                bundle.errors.append(str(exc))
        if self.search_provider and company_name:
            query = f"{company_name} {website}".strip()
            try:
                bundle.documents += self.search_provider.search(query)
            except SearchError as exc:
                logger.info("Search failed: %s", exc)
                bundle.errors.append(str(exc))
        # De-duplicate by URL, keep order.
        seen: set[str] = set()
        bundle.documents = [d for d in bundle.documents if not (d.url in seen or seen.add(d.url))]
        return bundle


class StaticResearchTools(ResearchTools):
    """Returns pre-supplied evidence. Used by tests and the evaluation script."""

    def __init__(self, documents: list[EvidenceDoc], errors: list[str] | None = None):
        super().__init__(None, None)
        self._documents = documents
        self._errors = errors or []

    def gather(self, company_name: str, website: str) -> EvidenceBundle:
        return EvidenceBundle(documents=list(self._documents), errors=list(self._errors))


def build_research_tools(settings: Settings) -> ResearchTools:
    search: SearchProvider | None = None
    if settings.search_provider == "tavily":
        from app.services.search.tavily import TavilySearchProvider

        search = TavilySearchProvider(settings.search_api_key)
    elif settings.search_provider not in ("", "none"):
        raise SearchError(f"Unknown SEARCH_PROVIDER '{settings.search_provider}'")
    return ResearchTools(WebsiteFetcher(settings.research_fetch_timeout_seconds), search)


__all__ = ["EvidenceBundle", "EvidenceDoc", "ResearchTools", "StaticResearchTools", "build_research_tools"]
