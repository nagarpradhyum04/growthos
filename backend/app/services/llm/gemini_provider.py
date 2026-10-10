"""Google Gemini implementation of LLMProvider (generateContent with JSON output).

Lets one GEMINI_API_KEY power both the agents (LLM_PROVIDER=gemini) and the social media
generation (MEDIA_PROVIDER=gemini).
"""
import httpx

from app.services.llm.provider import (
    LLMProvider,
    LLMProviderError,
    LLMRateLimitError,
    LLMRequest,
    LLMResponse,
    LLMTimeoutError,
)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiLLMProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, timeout_seconds: float, transport: httpx.BaseTransport | None = None,
                 base_url: str = BASE_URL):
        if not api_key:
            raise LLMProviderError("GEMINI_API_KEY is not set")
        self.base_url = base_url
        # Retries are handled by LLMService so they are visible in agent_runs.
        self._client = httpx.Client(timeout=timeout_seconds, transport=transport,
                                    headers={"x-goog-api-key": api_key})

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        body = {
            "systemInstruction": {"parts": [{"text": request.system_prompt}]},
            "contents": [{"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
                         for m in request.messages],
            "generationConfig": {"temperature": request.temperature, "responseMimeType": "application/json",
                                 "maxOutputTokens": 8192},
        }
        try:
            r = self._client.post(f"{self.base_url}/models/{request.model}:generateContent", json=body)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError("LLM request timed out") from exc
        except httpx.HTTPError as exc:
            raise LLMTimeoutError("Could not reach LLM provider") from exc
        if r.status_code == 429:
            raise LLMRateLimitError("LLM rate limit exceeded")
        if r.status_code >= 500:
            raise LLMTimeoutError(f"LLM provider server error ({r.status_code})")
        if r.status_code >= 400:
            # Only the provider's status/message, never the request content.
            message = (r.json().get("error", {}) if r.headers.get("content-type", "").startswith("application/json")
                       else {}).get("message", "")
            raise LLMProviderError(f"LLM provider rejected the request (HTTP {r.status_code}) {message[:200]}".strip())
        data = r.json()
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise LLMProviderError(f"LLM returned no answer ({reason})")
        finish = candidates[0].get("finishReason", "")
        # Skip "thought" parts (thinking models); only the answer text is the JSON.
        text = "".join(p.get("text", "") for p in candidates[0].get("content", {}).get("parts", []) if not p.get("thought"))
        if not text.strip():
            raise LLMProviderError(f"LLM returned an empty answer (finishReason={finish or 'unknown'})")
        if finish in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "RECITATION"):
            raise LLMProviderError(f"LLM answer was blocked by the provider (finishReason={finish})")
        meta = data.get("usageMetadata") or {}
        usage = {"prompt_tokens": meta.get("promptTokenCount", 0), "completion_tokens": meta.get("candidatesTokenCount", 0)}
        return LLMResponse(content=text, model=data.get("modelVersion") or request.model, usage=usage)
