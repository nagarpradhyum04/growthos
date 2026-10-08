"""Shared helpers for agents.

An agent = one specialized prompt + its allowed tools + an output schema + deterministic checks,
all running on the same LLMService. Agents never touch the database or send email; the workflow
services and orchestrator do that.
"""
import re

from app.services.llm.service import LLMService

_STOPWORDS = {
    "about", "their", "there", "which", "would", "these", "those", "company", "companies", "with",
    "from", "that", "this", "have", "your", "into", "they", "them", "were", "been", "being",
}
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def significant_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{4,}", text.lower()) if w not in _STOPWORDS}


def ungrounded_items(items: list[str], corpus: str, min_overlap: float = 0.5) -> list[str]:
    """Return items whose significant words mostly do not appear in the corpus (likely fabricated)."""
    corpus_words = significant_words(corpus)
    bad = []
    for item in items:
        words = significant_words(item)
        if words and len(words & corpus_words) / len(words) < min_overlap:
            bad.append(item)
    return bad


def contains_email_address(text: str) -> bool:
    return bool(_EMAIL_RE.search(text))


class BaseAgent:
    name: str
    prompt_name: str

    def __init__(self, llm: LLMService):
        self.llm = llm
