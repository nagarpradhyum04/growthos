"""Scripted LLM provider for testing LLMService behaviour (retries, corrections, failures)."""
import json

from app.services.llm.provider import LLMProvider, LLMRequest, LLMResponse


class ScriptedProvider(LLMProvider):
    """Returns queued responses in order. Items may be dicts (JSON-encoded), strings, or exceptions."""

    name = "scripted"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[LLMRequest] = []

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        content = item if isinstance(item, str) else json.dumps(item)
        return LLMResponse(content=content, model="scripted-model")
