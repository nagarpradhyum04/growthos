"""Provider-agnostic LLM interface.

Nothing outside services/llm/ talks to a concrete provider: agents go through LLMService,
which talks to whichever LLMProvider is configured (LLM_PROVIDER env var).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMMessage:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class LLMRequest:
    agent_name: str
    system_prompt: str
    messages: list[LLMMessage]
    model: str
    temperature: float = 0.2
    # The structured input the prompt was built from. Real providers ignore it;
    # the offline mock adapter uses it to produce deterministic output.
    input_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)


class LLMError(Exception):
    """Base class for provider errors."""

    retryable = False


class LLMTimeoutError(LLMError):
    retryable = True


class LLMRateLimitError(LLMError):
    retryable = True


class LLMProviderError(LLMError):
    """Non-retryable provider failure (bad credentials, invalid request, ...)."""


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def complete_json(self, request: LLMRequest) -> LLMResponse:
        """Return a completion whose content is expected to be a JSON object."""
