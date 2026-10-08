"""OpenAI implementation of LLMProvider (Chat Completions with JSON mode)."""
import openai

from app.services.llm.provider import (
    LLMProvider,
    LLMProviderError,
    LLMRateLimitError,
    LLMRequest,
    LLMResponse,
    LLMTimeoutError,
)


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, timeout_seconds: float):
        if not api_key:
            raise LLMProviderError("OPENAI_API_KEY is not set")
        # Retries are handled by LLMService so they are visible in agent_runs.
        self._client = openai.OpenAI(api_key=api_key, timeout=timeout_seconds, max_retries=0)

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        messages = [{"role": "system", "content": request.system_prompt}]
        messages += [{"role": m.role, "content": m.content} for m in request.messages]
        try:
            completion = self._client.chat.completions.create(
                model=request.model,
                messages=messages,
                temperature=request.temperature,
                response_format={"type": "json_object"},
            )
        except openai.APITimeoutError as exc:
            raise LLMTimeoutError("LLM request timed out") from exc
        except openai.RateLimitError as exc:
            raise LLMRateLimitError("LLM rate limit exceeded") from exc
        except openai.APIConnectionError as exc:
            raise LLMTimeoutError("Could not reach LLM provider") from exc
        except openai.InternalServerError as exc:
            raise LLMTimeoutError(f"LLM provider server error ({exc.status_code})") from exc
        except openai.APIError as exc:
            # Do not include the raw exception: it can echo request content.
            raise LLMProviderError(f"LLM provider rejected the request: {type(exc).__name__}") from exc

        choice = completion.choices[0]
        usage = {}
        if completion.usage:
            usage = {
                "prompt_tokens": completion.usage.prompt_tokens,
                "completion_tokens": completion.usage.completion_tokens,
            }
        return LLMResponse(content=choice.message.content or "", model=completion.model, usage=usage)
