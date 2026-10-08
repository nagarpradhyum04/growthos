"""Research tools: gather public evidence about a company before the Research Agent runs.

Tools never invent content: they only return text fetched from public URLs, each tagged with its
source URL so the agent can cite it.
"""
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field


@dataclass
class EvidenceDoc:
    url: str
    title: str
    text: str
    source_type: str  # "website" | "search"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvidenceBundle:
    documents: list[EvidenceDoc] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def urls(self) -> set[str]:
        return {d.url for d in self.documents}


class SearchProvider(ABC):
    name: str

    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> list[EvidenceDoc]:
        """Raise SearchError on failure."""


class SearchError(Exception):
    pass
